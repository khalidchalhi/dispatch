from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol, cast

from libs.core.config import Settings
from libs.core.errors import ExternalServiceError, ValidationError
from libs.dns_provisioner.base import (
    AuthenticationError,
    DNSProvisioner,
    DNSRecordInput,
    DNSZone,
    RateLimitedError,
    ZoneNotFoundError,
    normalize_dns_value,
)


class _Route53ClientProtocol(Protocol):
    def list_hosted_zones(self, **kwargs: object) -> dict[str, object]: ...

    def change_resource_record_sets(self, **kwargs: object) -> dict[str, object]: ...

    def list_resource_record_sets(self, **kwargs: object) -> dict[str, object]: ...


@dataclass(slots=True)
class Route53DNSProvisioner(DNSProvisioner):
    settings: Settings
    client: _Route53ClientProtocol | None = None

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = self._build_client()

    async def create_record(self, *, zone_id: str, record: DNSRecordInput) -> str:
        await asyncio.to_thread(
            self._upsert_records_sync,
            zone_id,
            [record],
        )
        return self._record_id(record)

    async def update_record(self, *, zone_id: str, record_id: str, record: DNSRecordInput) -> str:
        _ = record_id
        await asyncio.to_thread(
            self._upsert_records_sync,
            zone_id,
            [record],
        )
        return self._record_id(record)

    async def upsert_records(
        self,
        *,
        zone_id: str,
        records: list[DNSRecordInput],
    ) -> dict[str, str]:
        if not records:
            return {}
        await asyncio.to_thread(
            self._upsert_records_sync,
            zone_id,
            records,
        )
        return {
            self._record_id(record): self._record_id(record)
            for record in records
        }

    async def delete_record(self, *, zone_id: str, record_id: str) -> None:
        name, record_type = self._parse_record_id(record_id)
        existing = await asyncio.to_thread(self._fetch_record_set_sync, zone_id, name, record_type)
        if existing is None:
            return
        await asyncio.to_thread(self._delete_record_sync, zone_id, existing)

    async def verify_record(self, *, zone_id: str, record: DNSRecordInput) -> bool:
        existing = await asyncio.to_thread(
            self._fetch_record_set_sync,
            zone_id,
            record.name,
            record.record_type,
        )
        if existing is None:
            return False

        values = existing.get("ResourceRecords")
        if not isinstance(values, list):
            return False
        normalized_expected = normalize_dns_value(record.value)
        for value_item in values:
            if not isinstance(value_item, dict):
                continue
            value = value_item.get("Value")
            if isinstance(value, str) and normalize_dns_value(value) == normalized_expected:
                return True
        return False

    async def list_zones(self) -> list[DNSZone]:
        payload = await asyncio.to_thread(self._list_zones_sync)
        zones_raw = payload.get("HostedZones")
        if not isinstance(zones_raw, list):
            raise ExternalServiceError("Route53 hosted zones response is invalid")
        zones: list[DNSZone] = []
        for item in zones_raw:
            if not isinstance(item, dict):
                continue
            zone_id = str(item.get("Id") or "").strip().replace("/hostedzone/", "")
            zone_name = normalize_dns_value(str(item.get("Name") or ""))
            if zone_id and zone_name:
                zones.append(DNSZone(id=zone_id, name=zone_name))
        return zones

    def _list_zones_sync(self) -> dict[str, object]:
        assert self.client is not None
        try:
            return self.client.list_hosted_zones()
        except Exception as exc:
            self._raise_mapped_error(exc)
            raise

    def _upsert_records_sync(self, zone_id: str, records: list[DNSRecordInput]) -> None:
        assert self.client is not None
        changes = [
            {
                "Action": "UPSERT",
                "ResourceRecordSet": self._to_record_set(record),
            }
            for record in records
        ]
        request_payload = {
            "HostedZoneId": zone_id,
            "ChangeBatch": {
                "Changes": changes
            },
        }
        try:
            self.client.change_resource_record_sets(**request_payload)
        except Exception as exc:
            self._raise_mapped_error(exc)
            raise

    def _delete_record_sync(self, zone_id: str, existing_record_set: dict[str, object]) -> None:
        assert self.client is not None
        request_payload = {
            "HostedZoneId": zone_id,
            "ChangeBatch": {
                "Changes": [
                    {
                        "Action": "DELETE",
                        "ResourceRecordSet": existing_record_set,
                    }
                ]
            },
        }
        try:
            self.client.change_resource_record_sets(**request_payload)
        except Exception as exc:
            self._raise_mapped_error(exc)
            raise

    def _fetch_record_set_sync(
        self,
        zone_id: str,
        name: str,
        record_type: str,
    ) -> dict[str, object] | None:
        assert self.client is not None
        normalized_name = normalize_dns_value(name)
        try:
            payload = self.client.list_resource_record_sets(
                HostedZoneId=zone_id,
                StartRecordName=name,
                StartRecordType=record_type.upper(),
                MaxItems="5",
            )
        except Exception as exc:
            self._raise_mapped_error(exc)
            raise
        sets = payload.get("ResourceRecordSets")
        if not isinstance(sets, list):
            return None
        for item in sets:
            if not isinstance(item, dict):
                continue
            item_name = normalize_dns_value(str(item.get("Name") or ""))
            item_type = str(item.get("Type") or "").upper()
            if item_name == normalized_name and item_type == record_type.upper():
                return item
        return None

    @staticmethod
    def _to_record_set(record: DNSRecordInput) -> dict[str, object]:
        record_set: dict[str, object] = {
            "Name": record.name,
            "Type": record.record_type.upper(),
            "TTL": max(record.ttl, 1),
            "ResourceRecords": [{"Value": record.value}],
        }
        if record.record_type.upper() == "MX" and record.priority is not None:
            record_set["ResourceRecords"] = [{"Value": f"{record.priority} {record.value}"}]
        return record_set

    @staticmethod
    def _record_id(record: DNSRecordInput) -> str:
        normalized_name = normalize_dns_value(record.name)
        return f"{record.record_type.upper()}:{normalized_name}"

    @staticmethod
    def _parse_record_id(record_id: str) -> tuple[str, str]:
        normalized = record_id.strip()
        if ":" not in normalized:
            raise ValidationError("Invalid Route53 record id")
        record_type, name = normalized.split(":", 1)
        clean_type = record_type.strip().upper()
        clean_name = name.strip()
        if not clean_type or not clean_name:
            raise ValidationError("Invalid Route53 record id")
        return clean_name, clean_type

    def _build_client(self) -> _Route53ClientProtocol:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover
            raise ValidationError("boto3 is required for Route53 provisioning") from exc

        kwargs: dict[str, object] = {"region_name": self.settings.aws_region}
        if self.settings.aws_access_key_id and self.settings.aws_secret_access_key:
            kwargs["aws_access_key_id"] = self.settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = self.settings.aws_secret_access_key
            if self.settings.aws_session_token:
                kwargs["aws_session_token"] = self.settings.aws_session_token

        if self.settings.app_env in {"local", "test"}:
            kwargs["endpoint_url"] = self.settings.localstack_endpoint_url

        return cast(_Route53ClientProtocol, boto3.client("route53", **kwargs))

    @staticmethod
    def _raise_mapped_error(exc: Exception) -> None:
        error_code = ""
        error_message = "Route53 request failed"
        response = getattr(exc, "response", None)
        if isinstance(response, dict):
            payload = response.get("Error")
            if isinstance(payload, dict):
                error_code = str(payload.get("Code") or "")
                error_message = str(payload.get("Message") or error_message)

        lowered_code = error_code.lower()
        lowered_message = error_message.lower()
        if "auth" in lowered_code or "accessdenied" in lowered_code:
            raise AuthenticationError(error_message) from exc
        if "throttl" in lowered_code or "rate" in lowered_message:
            raise RateLimitedError(error_message) from exc
        if "nohostedzone" in lowered_code or "hosted zone" in lowered_message:
            raise ZoneNotFoundError(error_message) from exc
        raise ExternalServiceError(error_message) from exc
