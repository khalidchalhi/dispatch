from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Single source of truth for backend configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "local"
    service_name: str = "dispatch-api"
    log_level: str = "INFO"
    secret_key: str = "dispatch-local-secret"

    database_url: str = "postgresql+asyncpg://postgres:khalid123@localhost:5432/dispatch"
    database_pool_size: int = 20
    database_max_overflow: int = 10
    database_pool_timeout: int = 30

    redis_url: str = "redis://localhost:6379/0"

    aws_region: str = "us-east-1"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None
    localstack_endpoint_url: str = "http://localhost:4566"
    cloudflare_api_base_url: str = "https://api.cloudflare.com/client/v4"
    cloudflare_api_token_secret_name: str | None = None
    route53_default_hosted_zone_id: str | None = None

    ses_region: str = "us-east-1"
    ses_sns_topic_arn: str = "arn:aws:sns:us-east-1:000000000000:dispatch-local-events"
    domain_provisioning_poll_interval_seconds: int = Field(default=30, ge=1, le=120)
    domain_provisioning_timeout_seconds: int = Field(default=300, ge=30, le=3600)

    default_domain_hourly_rate_limit: int = 150
    default_campaign_hourly_rate_limit: int = 100
    bounce_rate_alarm: float = Field(default=0.015, ge=0.0, le=1.0)
    complaint_rate_alarm: float = Field(default=0.0005, ge=0.0, le=1.0)
    throttle_bucket_ttl_seconds: int = Field(default=60 * 60 * 2, ge=60, le=60 * 60 * 24)
    throttle_fail_closed_retry_seconds: int = Field(default=60, ge=1, le=600)
    circuit_breaker_cache_ttl_seconds: int = Field(default=10, ge=1, le=300)
    circuit_breaker_auto_reset_hours: int = Field(default=24, ge=1, le=168)
    circuit_breaker_recheck_delay_seconds: int = Field(default=60, ge=1, le=600)
    circuit_breaker_trip_consecutive_evaluations: int = Field(default=1, ge=1, le=10)

    ml_scorer_enabled: bool = False
    reply_intent_enabled: bool = False
    anomaly_detection_enabled: bool = False

    session_cookie_name: str = "dispatch_session"
    session_ttl_seconds: int = 60 * 60 * 24 * 14
    unsubscribe_token_ttl_seconds: int = 60 * 60 * 24 * 30
    mfa_challenge_ttl_seconds: int = 300
    mfa_enrollment_ttl_seconds: int = 600
    mfa_kms_data_key: str | None = None

    auth_lockout_max_attempts: int = 5
    auth_lockout_seconds: int = 900
    auth_login_attempt_window_seconds: int = 900

    argon2_time_cost: int = 3
    argon2_memory_cost: int = 65536
    argon2_parallelism: int = 2

    import_max_upload_bytes: int = 25 * 1024 * 1024
    import_batch_size: int = 1000
    import_storage_root: str = ".import_storage"
    import_max_concurrent_jobs_per_user: int = 3
    import_smtp_probe_enabled: bool = False
    import_mx_cache_ttl_seconds: int = 3600
    import_role_account_prefixes: str = (
        "info,admin,sales,support,contact,noreply,no-reply,postmaster,help"
    )
    import_disposable_domains: str = (
        "mailinator.com,10minutemail.com,tempmail.com,guerrillamail.com"
    )
    suppression_cache_ttl_seconds: int = Field(default=30, ge=1, le=60)
    suppression_max_removals_per_day: int = Field(default=25, ge=1, le=10000)
    suppression_ses_sync_enabled: bool = False
    suppression_ses_sync_batch_size: int = Field(default=100, ge=1, le=1000)
    suppression_ses_sync_pause_ms: int = Field(default=25, ge=0, le=5000)
    suppression_ses_sync_max_records_per_run: int = Field(default=1000, ge=1, le=100000)
    public_unsubscribe_base_url: str = "http://localhost:8000"
    sns_signature_cert_cache_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    event_dedup_ttl_seconds: int = Field(default=60 * 60 * 24 * 7, ge=60, le=60 * 60 * 24 * 30)

    @property
    def session_cookie_secure(self) -> bool:
        return self.app_env not in {"local", "test"}

    @property
    def role_account_prefix_set(self) -> set[str]:
        return {
            item.strip().lower()
            for item in self.import_role_account_prefixes.split(",")
            if item.strip()
        }

    @property
    def disposable_domain_set(self) -> set[str]:
        return {
            item.strip().lower()
            for item in self.import_disposable_domains.split(",")
            if item.strip()
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor for routes, workers, and scripts."""

    return Settings()


def reset_settings_cache() -> None:
    """Test helper to clear cached settings."""

    get_settings.cache_clear()
