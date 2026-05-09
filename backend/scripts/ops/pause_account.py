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

_ACCOUNT_SCOPE_ID = "00000000-0000-0000-0000-000000000000"


@dataclass(frozen=True, slots=True)
class PauseAccountResult:
    breaker_state_id: str
    breaker_status_before: str | None
    breaker_status_after: str
    running_campaigns_paused: int
    running_campaign_runs_paused: int
    reason: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manually pause account-wide sending by opening the account circuit breaker."
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="Reason for account pause (written to circuit breaker and audit log).",
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
        default="ops-script:pause_account",
        help="User agent string for audit logging.",
    )
    args = parser.parse_args()

    reason = args.reason.strip()
    if not reason:
        raise SystemExit("`--reason` must not be empty.")

    result = pause_account(
        reason=reason,
        actor_id=args.actor_id,
        ip_address=args.ip_address,
        user_agent=args.user_agent,
    )

    print(
        "Account pause applied: "
        f"breaker={result.breaker_state_id} "
        f"({result.breaker_status_before} -> {result.breaker_status_after}), "
        f"campaigns_paused={result.running_campaigns_paused}, "
        f"campaign_runs_paused={result.running_campaign_runs_paused}, "
        f"reason={result.reason}"
    )
    return 0


def pause_account(
    *,
    reason: str,
    actor_id: str | None,
    ip_address: str | None,
    user_agent: str | None,
) -> PauseAccountResult:
    settings = get_settings()
    dsn = settings.database_url.replace("+asyncpg", "")
    actor_type = "user" if actor_id else "system"
    now = datetime.now(UTC)
    tripped_reason = f"manual_pause:{reason}"

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id::text, state
                FROM circuit_breaker_state
                WHERE scope_type = 'account'
                  AND scope_id = %s
                FOR UPDATE
                """,
                (_ACCOUNT_SCOPE_ID,),
            )
            breaker_row = cursor.fetchone()

            if breaker_row is None:
                breaker_state_id = str(uuid4())
                breaker_state_before = None
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
                    VALUES (%s, 'account', %s, 'open', NULL, NULL, %s, %s, NULL, %s, %s)
                    """,
                    (breaker_state_id, _ACCOUNT_SCOPE_ID, now, tripped_reason, actor_id, now),
                )
            else:
                breaker_state_id = str(breaker_row[0])
                breaker_state_before = str(breaker_row[1])
                cursor.execute(
                    """
                    UPDATE circuit_breaker_state
                    SET state = 'open',
                        bounce_rate_24h = NULL,
                        complaint_rate_24h = NULL,
                        tripped_at = %s,
                        tripped_reason = %s,
                        auto_reset_at = NULL,
                        manually_reset_by = %s,
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (now, tripped_reason, actor_id, now, breaker_state_id),
                )

            cursor.execute(
                """
                WITH updated_campaigns AS (
                    UPDATE campaigns
                    SET status = 'paused',
                        updated_at = %s
                    WHERE status = 'running'
                    RETURNING id
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
                (now,),
            )
            counts_row = cursor.fetchone()
            campaigns_paused = int(counts_row[0] if counts_row is not None else 0)
            runs_paused = int(counts_row[1] if counts_row is not None else 0)

            cursor.execute(
                """
                INSERT INTO anomaly_alerts (
                    id,
                    scope_type,
                    scope_id,
                    metric,
                    severity,
                    message,
                    observed_value,
                    expected_value,
                    acknowledged_by,
                    acknowledged_at,
                    resolved_at,
                    created_at
                )
                VALUES (%s, 'account', %s, %s, %s, %s, NULL, NULL, NULL, NULL, NULL, %s)
                """,
                (
                    str(uuid4()),
                    _ACCOUNT_SCOPE_ID,
                    "manual_pause",
                    "critical",
                    f"Manual account pause triggered: {reason}",
                    now,
                ),
            )

            before_state = {
                "state": breaker_state_before,
                "scope_type": "account",
                "scope_id": _ACCOUNT_SCOPE_ID,
            }
            after_state = {
                "state": "open",
                "scope_type": "account",
                "scope_id": _ACCOUNT_SCOPE_ID,
                "tripped_reason": tripped_reason,
                "campaigns_paused": campaigns_paused,
                "campaign_runs_paused": runs_paused,
                "paused_at": now.isoformat(),
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
                    "account.pause",
                    "circuit_breaker_state",
                    breaker_state_id,
                    Json(before_state),
                    Json(after_state),
                    ip_address,
                    user_agent,
                ),
            )

    return PauseAccountResult(
        breaker_state_id=breaker_state_id,
        breaker_status_before=breaker_state_before,
        breaker_status_after="open",
        running_campaigns_paused=campaigns_paused,
        running_campaign_runs_paused=runs_paused,
        reason=reason,
    )


if __name__ == "__main__":
    raise SystemExit(main())
