from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Protocol
from urllib import parse, request

from libs.core.config import Settings
from libs.core.errors import ExternalServiceError, ValidationError
from libs.dns_provisioner.base import (
    AuthenticationError,
    AwsSecretsManagerSecretProvider,
    DNSProvisioner,
    DNSRecordInput,
    DNSZone,
    RateLimitedError,
    RecordExistsError,
    SecretProvider,
    ZoneNotFoundError,
    normalize_dns_value,
)


class CloudflareTransport(Protocol):
    async def request_json(
        self,
        *,
        method: str,
        path: str,
        token: str,
        params: dict[str, str] | None = None,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]: ...


@dataclass(slots=True)
class _UrllibCloudflareTransport:
    base_url: str

    async def request_json(
        self,
        *,
        method: str,
        path: str,
        token: str,
        params: dict[str, str] | None = None,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return await asyncio.to_thread(
            self._request_json_sync,
            method,
            path,
            token,
            params,
            payload,
        )

    def _request_json_sync(
        self,
        method: str,
        path: str,
        token: str,
        params: dict[str, str] | None,
        payload: dict[str, object] | None,
    ) -> dict[str, object]:
        query = f"?{parse.urlencode(params)}" if params else ""
        target = f"{self.base_url.rstrip('/')}{path}{query}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = request.Request(
            target,
            data=body,
            method=method.upper(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=20) as response:
                raw = response.read().decode("utf-8")
                if not raw:
                    return {}
                return json.loads(raw)
        except Exception as exc:
            raise ExternalServiceError("Cloudflare API request failed") from exc


class CloudflareDNSProvisioner(DNSProvisioner):
    def __init__(
        self,
        settings: Settings,
        *,
        secret_provider: SecretProvider | None = None,
        transport: CloudflareTransport | None = None,
    ) -> None:
        self._settings = settings
        self._secret_provider = secret_provider or AwsSecretsManagerSecretProvider(settings)
        self._transport = transport or _UrllibCloudflareTransport(settings.cloudflare_api_base_url)
        self._token: str | None = None

    async def create_record(self, *, zone_id: str, record: DNSRecordInput) -> str:
        existing = await self._find_record(zone_id=zone_id, record=record)
        if existing is not None:
            existing_id, existing_value = existing
            if normalize_dns_value(existing_value) == normalize_dns_value(record.value):
                return existing_id
            return await self.update_record(zone_id=zone_id, record_id=existing_id, record=record)

        payload: dict[str, object] = {
            "type": record.record_type,
            "name": record.name,
            "content": record.value,
            "ttl": max(record.ttl, 60),
        }
        if record.record_type.upper() == "MX" and record.priority is not None:
            payload["priority"] = record.priority

        body = await self._request(
            method="POST",
            path=f"/zones/{zone_id}/dns_records",
            payload=payload,
        )
        result = body.get("result")
        if not isinstance(result, dict):
            raise ExternalServiceError("Cloudflare did not return created record")
        record_id = str(result.get("id") or "").strip()
        if not record_id:
            raise ExternalServiceError("Cloudflare response missing record id")
        return record_id

    async def update_record(self, *, zone_id: str, record_id: str, record: DNSRecordInput) -> str:
        payload: dict[str, object] = {
            "type": record.record_type,
            "name": record.name,
            "content": record.value,
            "ttl": max(record.ttl, 60),
        }
        if record.record_type.upper() == "MX" and record.priority is not None:
            payload["priority"] = record.priority

        body = await self._request(
            method="PUT",
            path=f"/zones/{zone_id}/dns_records/{record_id}",
            payload=payload,
        )
        result = body.get("result")
        if not isinstance(result, dict):
            raise ExternalServiceError("Cloudflare did not return updated record")
        updated_id = str(result.get("id") or "").strip()
        if not updated_id:
            raise ExternalServiceError("Cloudflare response missing record id")
        return updated_id

    async def delete_record(self, *, zone_id: str, record_id: str) -> None:
        await self._request(method="DELETE", path=f"/zones/{zone_id}/dns_records/{record_id}")

    async def verify_record(self, *, zone_id: str, record: DNSRecordInput) -> bool:
        existing = await self._find_record(zone_id=zone_id, record=record)
        if existing is None:
            return False
        _, existing_value = existing
        return normalize_dns_value(existing_value) == normalize_dns_value(record.value)

    async def list_zones(self) -> list[DNSZone]:
        body = await self._request(method="GET", path="/zones", params={"per_page": "100"})
        result = body.get("result")
        if not isinstance(result, list):
            raise ExternalServiceError("Cloudflare zones response format is invalid")
        zones: list[DNSZone] = []
        for item in result:
            if not isinstance(item, dict):
                continue
            zone_id = str(item.get("id") or "").strip()
            zone_name = str(item.get("name") or "").strip().lower()
            if not zone_id or not zone_name:
                continue
            zones.append(DNSZone(id=zone_id, name=zone_name))
        return zones

    async def _find_record(self, *, zone_id: str, record: DNSRecordInput) -> tuple[str, str] | None:
        body = await self._request(
            method="GET",
            path=f"/zones/{zone_id}/dns_records",
            params={
                "type": record.record_type.upper(),
                "name": record.name,
                "per_page": "100",
            },
        )
        result = body.get("result")
        if not isinstance(result, list):
            return None
        normalized_name = normalize_dns_value(record.name)
        for item in result:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "").strip()
            item_name = normalize_dns_value(str(item.get("name") or ""))
            item_value = str(item.get("content") or "").strip()
            item_type = str(item.get("type") or "").strip().upper()
            if (
                item_id
                and item_type == record.record_type.upper()
                and item_name == normalized_name
            ):
                return item_id, item_value
        return None

    async def _request(
        self,
        *,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        token = await self._get_token()
        body = await self._transport.request_json(
            method=method,
            path=path,
            token=token,
            params=params,
            payload=payload,
        )
        if not isinstance(body, dict):
            raise ExternalServiceError("Cloudflare response is invalid")

        success = body.get("success")
        if success is True:
            return body

        errors = body.get("errors")
        code = ""
        message = "Cloudflare request failed"
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                code = str(first.get("code") or "").strip()
                message = str(first.get("message") or message).strip()

        lowered = message.lower()
        if code in {"10000", "9109"} or "authentication" in lowered or "unauthorized" in lowered:
            raise AuthenticationError(message)
        if code in {"10100", "7003", "7000"} or "zone" in lowered and "not found" in lowered:
            raise ZoneNotFoundError(message)
        if code in {"81057"}:
            raise RecordExistsError(message)
        if code in {"1015", "429"} or "rate limit" in lowered:
            raise RateLimitedError(message)
        raise ExternalServiceError(message)

    async def _get_token(self) -> str:
        if self._token is not None:
            return self._token

        secret_name = self._settings.cloudflare_api_token_secret_name
        if not secret_name:
            raise ValidationError("CLOUDFLARE_API_TOKEN_SECRET_NAME is required")

        secret = await self._secret_provider.get_secret(secret_name=secret_name)
        token = self._extract_token(secret)
        if not token:
            raise ValidationError("Cloudflare API token secret is empty")
        self._token = token
        return token

    @staticmethod
    def _extract_token(secret: str) -> str:
        text = secret.strip()
        if not text:
            return ""
        if text.startswith("{"):
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                return text
            if isinstance(payload, dict):
                for key in ("api_token", "token", "cloudflare_api_token"):
                    value = payload.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        return text
