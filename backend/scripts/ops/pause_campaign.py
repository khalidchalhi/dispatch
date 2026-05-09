from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.types.json import Json

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from libs.core.config import get_settings  # noqa: E402

_PAUSABLE_STATUS = "running"
_TERMINAL_STATUSES = {"completed", "cancelled", "failed"}


@dataclass(frozen=True, slots=True)
class PauseCampaignResult:
    campaign_id: str
    campaign_status_before: str
    campaign_status_after: str
    campaign_runs_paused: int
    reason: str


def main() -> int:
    parser = argparse.ArgumentParser(description="Pause a running campaign immediately.")
    parser.add_argument("--campaign-id", required=True, help="Campaign UUID.")
    parser.add_argument(
        "--reason",
        required=True,
        help="Reason for the manual pause (written to audit log).",
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
        default="ops-script:pause_campaign",
        help="User agent string for audit logging.",
    )
    args = parser.parse_args()

    reason = args.reason.strip()
    if not reason:
        raise SystemExit("`--reason` must not be empty.")

    result = pause_campaign(
        campaign_id=args.campaign_id,
        reason=reason,
        actor_id=args.actor_id,
        ip_address=args.ip_address,
        user_agent=args.user_agent,
    )

    print(
        "Paused campaign "
        f"{result.campaign_id} "
        f"({result.campaign_status_before} -> {result.campaign_status_after}); "
        f"runs_paused={result.campaign_runs_paused}; reason={result.reason}"
    )
    return 0


def pause_campaign(
    *,
    campaign_id: str,
    reason: str,
    actor_id: str | None,
    ip_address: str | None,
    user_agent: str | None,
) -> PauseCampaignResult:
    settings = get_settings()
    dsn = settings.database_url.replace("+asyncpg", "")
    actor_type = "user" if actor_id else "system"
    now = datetime.now(UTC)

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id::text, status
                FROM campaigns
                WHERE id = %s
                FOR UPDATE
                """,
                (campaign_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise SystemExit(f"Campaign not found: {campaign_id}")

            found_campaign_id = str(row[0])
            status_before = str(row[1])

            if status_before in _TERMINAL_STATUSES:
                raise SystemExit(
                    f"Campaign {found_campaign_id} is terminal ({status_before}) "
                    "and cannot be paused."
                )
            if status_before != _PAUSABLE_STATUS:
                if status_before == "paused":
                    return PauseCampaignResult(
                        campaign_id=found_campaign_id,
                        campaign_status_before=status_before,
                        campaign_status_after=status_before,
                        campaign_runs_paused=0,
                        reason=reason,
                    )
                raise SystemExit(
                    f"Campaign {found_campaign_id} must be `{_PAUSABLE_STATUS}` "
                    f"to pause; current status is `{status_before}`."
                )

            cursor.execute(
                """
                UPDATE campaigns
                SET status = 'paused',
                    updated_at = %s
                WHERE id = %s
                """,
                (now, found_campaign_id),
            )

            cursor.execute(
                """
                UPDATE campaign_runs
                SET status = 'paused'
                WHERE campaign_id = %s
                  AND status = 'running'
                """,
                (found_campaign_id,),
            )
            runs_paused = int(cursor.rowcount or 0)

            after_state = {
                "status": "paused",
                "reason": reason,
                "paused_at": now.isoformat(),
                "campaign_runs_paused": runs_paused,
            }
            before_state = {"status": status_before}
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
                    "campaign.pause",
                    "campaign",
                    found_campaign_id,
                    Json(before_state),
                    Json(after_state),
                    ip_address,
                    user_agent,
                ),
            )

    return PauseCampaignResult(
        campaign_id=found_campaign_id,
        campaign_status_before=status_before,
        campaign_status_after="paused",
        campaign_runs_paused=runs_paused,
        reason=reason,
    )


if __name__ == "__main__":
    raise SystemExit(main())
