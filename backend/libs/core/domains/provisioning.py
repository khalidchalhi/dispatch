from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, cast

from libs.core.config import Settings
from libs.core.errors import ExternalServiceError, ValidationError
from libs.dns_provisioner.base import AuthenticationError, RateLimitedError


@dataclass(frozen=True, slots=True)
class ProvisioningStep:
    name: str
    status: str
    at: datetime
    message: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "at": self.at.astimezone(UTC).isoformat(),
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> ProvisioningStep | None:
        raw_name = payload.get("name")
        raw_status = payload.get("status")
        raw_at = payload.get("at")
        if not isinstance(raw_name, str) or not isinstance(raw_status, str):
            return None
        if not isinstance(raw_at, str):
            return None
        timestamp = _parse_datetime(raw_at)
        if timestamp is None:
            return None
        raw_message = payload.get("message")
        return cls(
            name=raw_name,
            status=raw_status,
            at=timestamp,
            message=raw_message if isinstance(raw_message, str) else None,
        )


@dataclass(frozen=True, slots=True)
class DomainProvisioningStatus:
    domain_id: str
    run_id: str | None
    status: str
    reason_code: str | None
    started_at: datetime | None
    completed_at: datetime | None
    steps: list[ProvisioningStep]

    def to_metadata(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "reason_code": self.reason_code,
            "started_at": self.started_at.astimezone(UTC).isoformat()
            if self.started_at
            else None,
            "completed_at": self.completed_at.astimezone(UTC).isoformat()
            if self.completed_at
            else None,
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_metadata(
        cls,
        *,
        domain_id: str,
        payload: dict[str, object] | None,
    ) -> DomainProvisioningStatus:
        if payload is None:
            return cls(
                domain_id=domain_id,
                run_id=None,
                status="not_started",
                reason_code=None,
                started_at=None,
                completed_at=None,
                steps=[],
            )

        run_id = payload.get("run_id")
        status = payload.get("status")
        reason_code = payload.get("reason_code")
        started_at = _parse_datetime(payload.get("started_at"))
        completed_at = _parse_datetime(payload.get("completed_at"))
        raw_steps = payload.get("steps")
        steps: list[ProvisioningStep] = []
        if isinstance(raw_steps, list):
            for item in raw_steps:
                if not isinstance(item, dict):
                    continue
                parsed = ProvisioningStep.from_dict(item)
                if parsed is not None:
                    steps.append(parsed)
        return cls(
            domain_id=domain_id,
            run_id=run_id if isinstance(run_id, str) else None,
            status=status if isinstance(status, str) else "not_started",
            reason_code=reason_code if isinstance(reason_code, str) else None,
            started_at=started_at,
            completed_at=completed_at,
            steps=steps,
        )


class DomainProvisioningFailureReason(StrEnum):
    DOMAIN_PROVISIONING_FAILED = "domain_provisioning_failed"
    EXTERNAL_SERVICE_ERROR = "external_service_error"
    DNS_AUTHENTICATION_ERROR = "dns_authentication_error"
    DNS_RATE_LIMITED = "dns_rate_limited"
    DNS_ZONE_NOT_FOUND = "dns_zone_not_found"
    SES_IDENTITY_SETUP_FAILED = "ses_identity_setup_failed"
    SES_CONFIGURATION_SET_FAILED = "ses_configuration_set_failed"
    SES_MAIL_FROM_FAILED = "ses_mail_from_failed"
    DNS_RECORD_SYNC_FAILED = "dns_record_sync_failed"
    DNS_RECORD_APPLY_FAILED = "dns_record_apply_failed"
    SES_VERIFICATION_FAILED = "ses_verification_failed"
    SES_VERIFICATION_TIMEOUT = "ses_verification_timeout"
    DNS_VERIFICATION_FAILED = "dns_verification_failed"


@dataclass(frozen=True, slots=True)
class SesIdentityState:
    identity_arn: str | None
    verified_for_sending: bool
    dkim_tokens: list[str]
    dkim_signing_enabled: bool


class SesDomainProvisioner(Protocol):
    async def ensure_identity(self, *, domain_name: str) -> SesIdentityState: ...

    async def get_identity_state(self, *, domain_name: str) -> SesIdentityState: ...

    async def ensure_configuration_set(
        self,
        *,
        name: str,
        sns_topic_arn: str | None,
    ) -> None: ...

    async def ensure_mail_from(self, *, domain_name: str, mail_from_domain: str) -> None: ...

    async def delete_identity(self, *, domain_name: str) -> None: ...


class _SesV2ClientProtocol(Protocol):
    def create_email_identity(self, **kwargs: object) -> dict[str, object]: ...

    def get_email_identity(self, **kwargs: object) -> dict[str, object]: ...

    def put_email_identity_mail_from_attributes(self, **kwargs: object) -> dict[str, object]: ...

    def create_configuration_set(self, **kwargs: object) -> dict[str, object]: ...

    def create_configuration_set_event_destination(
        self, **kwargs: object
    ) -> dict[str, object]: ...

    def update_configuration_set_event_destination(
        self, **kwargs: object
    ) -> dict[str, object]: ...

    def delete_email_identity(self, **kwargs: object) -> dict[str, object]: ...


class Boto3SesDomainProvisioner(SesDomainProvisioner):
    def __init__(
        self,
        settings: Settings,
        *,
        client: _SesV2ClientProtocol | None = None,
    ) -> None:
        self._settings = settings
        self._client = client

    async def ensure_identity(self, *, domain_name: str) -> SesIdentityState:
        await asyncio.to_thread(self._ensure_identity_sync, domain_name)
        return await self.get_identity_state(domain_name=domain_name)

    async def get_identity_state(self, *, domain_name: str) -> SesIdentityState:
        payload = await asyncio.to_thread(self._get_identity_sync, domain_name)
        return self._parse_identity(payload)

    async def ensure_configuration_set(
        self,
        *,
        name: str,
        sns_topic_arn: str | None,
    ) -> None:
        await asyncio.to_thread(
            self._ensure_configuration_set_sync,
            name,
            sns_topic_arn,
        )

    async def ensure_mail_from(self, *, domain_name: str, mail_from_domain: str) -> None:
        await asyncio.to_thread(
            self._put_mail_from_sync,
            domain_name,
            mail_from_domain,
        )

    async def delete_identity(self, *, domain_name: str) -> None:
        await asyncio.to_thread(self._delete_identity_sync, domain_name)

    def _ensure_identity_sync(self, domain_name: str) -> None:
        client = self._client or self._build_client()
        try:
            client.create_email_identity(
                EmailIdentity=domain_name,
            )
        except Exception as exc:
            code = self._error_code(exc)
            if code in {"AlreadyExistsException", "ConflictException"}:
                return
            self._raise_mapped_error(exc)

    def _get_identity_sync(self, domain_name: str) -> dict[str, object]:
        client = self._client or self._build_client()
        try:
            return client.get_email_identity(EmailIdentity=domain_name)
        except Exception as exc:
            self._raise_mapped_error(exc)
            raise

    def _put_mail_from_sync(self, domain_name: str, mail_from_domain: str) -> None:
        client = self._client or self._build_client()
        try:
            client.put_email_identity_mail_from_attributes(
                EmailIdentity=domain_name,
                MailFromDomain=mail_from_domain,
                BehaviorOnMxFailure="USE_DEFAULT_VALUE",
            )
        except Exception as exc:
            self._raise_mapped_error(exc)

    def _ensure_configuration_set_sync(self, name: str, sns_topic_arn: str | None) -> None:
        client = self._client or self._build_client()
        try:
            client.create_configuration_set(ConfigurationSetName=name)
        except Exception as exc:
            code = self._error_code(exc)
            if code != "AlreadyExistsException":
                self._raise_mapped_error(exc)

        if not sns_topic_arn:
            return

        payload = {
            "ConfigurationSetName": name,
            "EventDestinationName": "dispatch-sns-events",
            "EventDestination": {
                "Enabled": True,
                "MatchingEventTypes": [
                    "SEND",
                    "REJECT",
                    "BOUNCE",
                    "COMPLAINT",
                    "DELIVERY",
                    "OPEN",
                    "CLICK",
                    "RENDERING_FAILURE",
                ],
                "SNSDestination": {"TopicARN": sns_topic_arn},
            },
        }
        try:
            client.create_configuration_set_event_destination(**payload)
        except Exception as exc:
            code = self._error_code(exc)
            if code in {"AlreadyExistsException", "ConflictException"}:
                try:
                    client.update_configuration_set_event_destination(**payload)
                except Exception as update_exc:
                    self._raise_mapped_error(update_exc)
            else:
                self._raise_mapped_error(exc)

    def _delete_identity_sync(self, domain_name: str) -> None:
        client = self._client or self._build_client()
        try:
            client.delete_email_identity(EmailIdentity=domain_name)
        except Exception as exc:
            code = self._error_code(exc)
            if code in {"NotFoundException"}:
                return
            self._raise_mapped_error(exc)

    def _build_client(self) -> _SesV2ClientProtocol:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover
            raise ValidationError("boto3 is required for SES domain provisioning") from exc

        kwargs: dict[str, object] = {"region_name": self._settings.ses_region}
        if self._settings.aws_access_key_id and self._settings.aws_secret_access_key:
            kwargs["aws_access_key_id"] = self._settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = self._settings.aws_secret_access_key
            if self._settings.aws_session_token:
                kwargs["aws_session_token"] = self._settings.aws_session_token

        if self._settings.app_env in {"local", "test"}:
            kwargs["endpoint_url"] = self._settings.localstack_endpoint_url

        return cast(_SesV2ClientProtocol, boto3.client("sesv2", **kwargs))

    @staticmethod
    def _parse_identity(payload: dict[str, object]) -> SesIdentityState:
        identity_arn_raw = payload.get("IdentityArn")
        verified_raw = payload.get("VerifiedForSendingStatus")
        dkim_raw = payload.get("DkimAttributes")

        identity_arn = identity_arn_raw if isinstance(identity_arn_raw, str) else None
        verified = bool(verified_raw) if isinstance(verified_raw, bool) else False

        dkim_tokens: list[str] = []
        dkim_signing_enabled = False
        if isinstance(dkim_raw, dict):
            token_raw = dkim_raw.get("Tokens")
            if isinstance(token_raw, list):
                for item in token_raw:
                    if isinstance(item, str) and item.strip():
                        dkim_tokens.append(item.strip())
            signing_enabled_raw = dkim_raw.get("SigningEnabled")
            if isinstance(signing_enabled_raw, bool):
                dkim_signing_enabled = signing_enabled_raw
            else:
                status_raw = dkim_raw.get("Status")
                if isinstance(status_raw, str) and status_raw.upper() == "SUCCESS":
                    dkim_signing_enabled = True

        return SesIdentityState(
            identity_arn=identity_arn,
            verified_for_sending=verified,
            dkim_tokens=dkim_tokens,
            dkim_signing_enabled=dkim_signing_enabled,
        )

    @staticmethod
    def _error_code(exc: Exception) -> str:
        response = getattr(exc, "response", None)
        if isinstance(response, dict):
            payload = response.get("Error")
            if isinstance(payload, dict):
                code = payload.get("Code")
                if isinstance(code, str):
                    return code
        return ""

    @classmethod
    def _raise_mapped_error(cls, exc: Exception) -> None:
        code = cls._error_code(exc).lower()
        message = str(exc) or "SES provisioning request failed"
        if "accessdenied" in code or "auth" in code:
            raise AuthenticationError(message) from exc
        if "throttl" in code or "toomanyrequests" in code:
            raise RateLimitedError(message) from exc
        raise ExternalServiceError(message) from exc


def _parse_datetime(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
