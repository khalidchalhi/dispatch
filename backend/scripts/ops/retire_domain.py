from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.types.json import Json

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from libs.core.config import get_settings  # noqa: E402


@dataclass(frozen=True, slots=True)
class RetireDomainResult:
    domain_id: str
    domain_name: str
    dns_records_deactivated: int
    sender_profiles_paused: int
    queued_messages_paused: int
    campaigns_paused: int
    campaign_runs_paused: int
    reason: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Retire a sending domain and stop all sends on it."
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

    domain_name = args.domain.strip().lower().rstrip(".")
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
        f"dns_records_deactivated={result.dns_records_deactivated}; "
        f"sender_profiles_paused={result.sender_profiles_paused}; "
        f"queued_messages_paused={result.queued_messages_paused}; "
        f"campaigns_paused={result.campaigns_paused}; "
        f"campaign_runs_paused={result.campaign_runs_paused}; "
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
                SELECT id::text, name, reputation_status, verification_status
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
            reputation_before = str(domain_row[2])
            verification_before = str(domain_row[3])

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

            cursor.execute(
                """
                UPDATE domain_dns_records
                SET is_active = FALSE
                WHERE domain_id = %s
                  AND is_active = TRUE
                """,
                (domain_id,),
            )
            dns_records_deactivated = int(cursor.rowcount or 0)

            pause_reason = f"domain_retired:{reason}"[:2000]
            cursor.execute(
                """
                UPDATE sender_profiles
                SET is_active = FALSE,
                    paused_at = COALESCE(paused_at, %s),
                    paused_reason = COALESCE(paused_reason, %s),
                    updated_at = %s
                WHERE domain_id = %s
                  AND is_active = TRUE
                """,
                (now, pause_reason, now, domain_id),
            )
            sender_profiles_paused = int(cursor.rowcount or 0)

            cursor.execute(
                """
                UPDATE messages
                SET status = 'paused',
                    error_code = 'domain_retired',
                    error_message = %s
                WHERE domain_id = %s
                  AND status = 'queued'
                """,
                (f"Domain retired: {reason}"[:4000], domain_id),
            )
            queued_messages_paused = int(cursor.rowcount or 0)

            cursor.execute(
                """
                WITH updated_campaigns AS (
                    UPDATE campaigns c
                    SET status = 'paused',
                        updated_at = %s
                    FROM sender_profiles sp
                    WHERE c.sender_profile_id = sp.id
                      AND sp.domain_id = %s
                      AND c.status = 'running'
                    RETURNING c.id
                ),
                updated_runs AS (
                    UPDATE campaign_runs
                    SET status = 'paused'
                    WHERE status = 'running'
                      AND campaign_id IN (SELECT id FROM updated_campaigns)
                    RETURNING id
                )
                SELECT
                    (SELECT COUNT(*) FROM updated_campaigns),
                    (SELECT COUNT(*) FROM updated_runs)
                """,
                (now, domain_id),
            )
            campaign_counts = cursor.fetchone()
            campaigns_paused = int(campaign_counts[0] if campaign_counts is not None else 0)
            campaign_runs_paused = int(campaign_counts[1] if campaign_counts is not None else 0)

            cursor.execute(
                """
                SELECT id::text, state
                FROM circuit_breaker_state
                WHERE scope_type = 'domain'
                  AND scope_id = %s
                FOR UPDATE
                """,
                (domain_id,),
            )
            state_row = cursor.fetchone()
            if state_row is None:
                cursor.execute(
                    """
                    INSERT INTO circuit_breaker_state (
                        id,
                        scope_type,
                        scope_id,
                        state,
                        bounce_rate_24h,
                        complaint_rate_24h,
                        tripped_at,
                        tripped_reason,
                        auto_reset_at,
                        manually_reset_by,
                        updated_at
                    )
                    VALUES (%s, 'domain', %s, 'open', NULL, NULL, %s, %s, NULL, %s, %s)
                    """,
                    (
                        str(uuid4()),
                        domain_id,
                        now,
                        "domain_retired",
                        actor_id,
                        now,
                    ),
                )
            else:
                cursor.execute(
                    """
                    UPDATE circuit_breaker_state
                    SET state = 'open',
                        tripped_at = %s,
                        tripped_reason = 'domain_retired',
                        auto_reset_at = NULL,
                        manually_reset_by = %s,
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (now, actor_id, now, str(state_row[0])),
                )

            before_state = {
                "reputation_status": reputation_before,
                "verification_status": verification_before,
            }
            after_state = {
                "reputation_status": "retired",
                "verification_status": "disabled",
                "reason": reason,
                "retired_at": now.isoformat(),
                "dns_records_deactivated": dns_records_deactivated,
                "sender_profiles_paused": sender_profiles_paused,
                "queued_messages_paused": queued_messages_paused,
                "campaigns_paused": campaigns_paused,
                "campaign_runs_paused": campaign_runs_paused,
            }
            cursor.execute(
                """
                INSERT INTO audit_log (
                    actor_type,
                    actor_id,
                    action,
                    resource_type,
                    resource_id,
                    before_state,
                    after_state,
                    ip_address,
                    user_agent
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    actor_type,
                    actor_id,
                    "domain.retire",
                    "domain",
                    domain_id,
                    Json(before_state),
                    Json(after_state),
                    ip_address,
                    user_agent,
                ),
            )

    return RetireDomainResult(
        domain_id=domain_id,
        domain_name=found_name,
        dns_records_deactivated=dns_records_deactivated,
        sender_profiles_paused=sender_profiles_paused,
        queued_messages_paused=queued_messages_paused,
        campaigns_paused=campaigns_paused,
        campaign_runs_paused=campaign_runs_paused,
        reason=reason,
    )


if __name__ == "__main__":
    raise SystemExit(main())
