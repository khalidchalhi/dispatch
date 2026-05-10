from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Json

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from libs.core.config import get_settings  # noqa: E402
from libs.core.domains.provisioning import Boto3SesDomainProvisioner  # noqa: E402
from libs.dns_provisioner.base import (  # noqa: E402
    AwsSecretsManagerSecretProvider,
    DNSProvisioner,
    DNSZone,
)
from libs.dns_provisioner.cloudflare import CloudflareDNSProvisioner  # noqa: E402
from libs.dns_provisioner.route53 import Route53DNSProvisioner  # noqa: E402


@dataclass(frozen=True, slots=True)
class RetireDomainResult:
    domain_id: str
    domain_name: str
    dns_records_removed: int
    ses_identity_deleted: bool
    reason: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Retire a sending domain and remove DNS + SES identity."
    )
    parser.add_argument(
        "--domain",
        required=True,
        help="Domain name to retire (for example: m47.sendbrand.com).",
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="Retirement reason (written to domain state and audit log).",
    )
    parser.add_argument(
        "--actor-id",
        default=None,
        help="Optional user UUID responsible for this operation.",
    )
    parser.add_argument(
        "--ip-address",
        default=None,
        help="Optional source IP for audit logging.",
    )
    parser.add_argument(
        "--user-agent",
        default="ops-script:retire_domain",
        help="User agent string for audit logging.",
    )
    args = parser.parse_args()

    domain_name = _normalize_domain_name(args.domain)
    reason = args.reason.strip()
    if not domain_name:
        raise SystemExit("`--domain` must not be empty.")
    if not reason:
        raise SystemExit("`--reason` must not be empty.")

    result = retire_domain(
        domain_name=domain_name,
        reason=reason,
        actor_id=args.actor_id,
        ip_address=args.ip_address,
        user_agent=args.user_agent,
    )

    print(
        f"Retired domain {result.domain_name} ({result.domain_id}); "
        f"dns_records_removed={result.dns_records_removed}; "
        f"ses_identity_deleted={result.ses_identity_deleted}; "
        f"reason={result.reason}"
    )
    return 0


def retire_domain(
    *,
    domain_name: str,
    reason: str,
    actor_id: str | None,
    ip_address: str | None,
    user_agent: str | None,
) -> RetireDomainResult:
    settings = get_settings()
    dsn = settings.database_url.replace("+asyncpg", "")
    actor_type = "user" if actor_id else "system"
    now = datetime.now(UTC)

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id::text, name, dns_provider, metadata
                FROM domains
                WHERE lower(name) = lower(%s)
                FOR UPDATE
                """,
                (domain_name,),
            )
            domain_row = cursor.fetchone()
            if domain_row is None:
                raise SystemExit(f"Domain not found: {domain_name}")

            domain_id = str(domain_row[0])
            found_name = str(domain_row[1])
            dns_provider = str(domain_row[2])
            metadata_json = domain_row[3] if isinstance(domain_row[3], dict) else {}

            cursor.execute(
                """
                SELECT provider_record_id
                FROM domain_dns_records
                WHERE domain_id = %s
                  AND is_active = TRUE
                  AND provider_record_id IS NOT NULL
                ORDER BY created_at ASC
                """,
                (domain_id,),
            )
            provider_record_ids = [str(row[0]) for row in cursor.fetchall() if row and row[0]]

            dns_records_removed = asyncio.run(
                _remove_dns_records(
                    provider=dns_provider,
                    domain_name=found_name,
                    metadata_json=metadata_json,
                    provider_record_ids=provider_record_ids,
                )
            )
            ses_identity_deleted = asyncio.run(_delete_ses_identity(domain_name=found_name))

            cursor.execute(
                """
                UPDATE domain_dns_records
                SET is_active = FALSE
                WHERE domain_id = %s
                  AND is_active = TRUE
                """,
                (domain_id,),
            )

            cursor.execute(
                """
                UPDATE domains
                SET reputation_status = 'retired',
                    verification_status = 'disabled',
                    retired_at = %s,
                    retirement_reason = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (now, reason, now, domain_id),
            )

            after_state = {
                "reputation_status": "retired",
                "verification_status": "disabled",
                "reason": reason,
                "retired_at": now.isoformat(),
                "dns_records_removed": dns_records_removed,
                "ses_identity_deleted": ses_identity_deleted,
            }
            cursor.execute(
                """
                INSERT INTO audit_log (
                    actor_type,
                    actor_id,
                    action,
                    resource_type,
                    resource_id,
                    after_state,
                    ip_address,
                    user_agent
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    actor_type,
                    actor_id,
                    "domain.retire",
                    "domain",
                    domain_id,
                    Json(after_state),
                    ip_address,
                    user_agent,
                ),
            )

    return RetireDomainResult(
        domain_id=domain_id,
        domain_name=found_name,
        dns_records_removed=dns_records_removed,
        ses_identity_deleted=ses_identity_deleted,
        reason=reason,
    )


async def _delete_ses_identity(*, domain_name: str) -> bool:
    ses = Boto3SesDomainProvisioner(get_settings())
    try:
        await ses.delete_identity(domain_name=domain_name)
    except Exception:
        return False
    return True


async def _remove_dns_records(
    *,
    provider: str,
    domain_name: str,
    metadata_json: dict[str, Any],
    provider_record_ids: list[str],
) -> int:
    normalized_provider = provider.strip().lower()
    if normalized_provider not in {"cloudflare", "route53"}:
        return 0
    if not provider_record_ids:
        return 0

    provisioner = _build_dns_provisioner(normalized_provider)
    zone_id = await _resolve_zone_id(
        provider=normalized_provider,
        domain_name=domain_name,
        metadata_json=metadata_json,
        provisioner=provisioner,
    )
    if not zone_id:
        return 0

    removed = 0
    for record_id in provider_record_ids:
        try:
            await provisioner.delete_record(zone_id=zone_id, record_id=record_id)
            removed += 1
        except Exception:
            continue
    return removed


def _build_dns_provisioner(provider: str) -> DNSProvisioner:
    settings = get_settings()
    if provider == "cloudflare":
        return CloudflareDNSProvisioner(
            settings,
            secret_provider=AwsSecretsManagerSecretProvider(settings),
        )
    return Route53DNSProvisioner(settings)


async def _resolve_zone_id(
    *,
    provider: str,
    domain_name: str,
    metadata_json: dict[str, Any],
    provisioner: DNSProvisioner,
) -> str | None:
    if provider == "cloudflare":
        explicit = metadata_json.get("cloudflare_zone_id")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
    if provider == "route53":
        explicit = metadata_json.get("route53_hosted_zone_id")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
        default_zone = get_settings().route53_default_hosted_zone_id
        if default_zone and default_zone.strip():
            return default_zone.strip()

    zones = await provisioner.list_zones()
    return _find_best_zone_id(domain_name=domain_name, zones=zones)


def _find_best_zone_id(*, domain_name: str, zones: list[DNSZone]) -> str | None:
    normalized_domain = _normalize_domain_name(domain_name)
    if not normalized_domain:
        return None

    exact = [zone for zone in zones if zone.name == normalized_domain]
    if exact:
        return exact[0].id

    suffix_matches = [zone for zone in zones if normalized_domain.endswith(zone.name)]
    if not suffix_matches:
        return None
    suffix_matches.sort(key=lambda zone: len(zone.name), reverse=True)
    return suffix_matches[0].id


def _normalize_domain_name(value: str) -> str:
    return value.strip().lower().rstrip(".")


if __name__ == "__main__":
    raise SystemExit(main())
