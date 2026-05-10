from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from libs.core.config import Settings
from libs.dns_provisioner.base import DNSRecordInput
from libs.dns_provisioner.cloudflare import CloudflareDNSProvisioner


class _FakeSecretProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def get_secret(self, *, secret_name: str) -> str:
        self.calls += 1
        assert secret_name == "dispatch/cloudflare/token"
        return '{"api_token":"cf-token"}'


@dataclass(slots=True)
class _MockCloudflareTransport:
    records: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)
    post_calls: int = 0
    put_calls: int = 0
    get_calls: int = 0
    delete_calls: int = 0

    async def request_json(
        self,
        *,
        method: str,
        path: str,
        token: str,
        params: dict[str, str] | None = None,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        assert token == "cf-token"
        params = params or {}
        payload = payload or {}
        parts = [part for part in path.split("/") if part]

        if method == "GET":
            self.get_calls += 1
        elif method == "POST":
            self.post_calls += 1
        elif method == "PUT":
            self.put_calls += 1
        elif method == "DELETE":
            self.delete_calls += 1

        if (
            method == "GET"
            and len(parts) == 3
            and parts[0] == "zones"
            and parts[2] == "dns_records"
        ):
            zone_id = parts[1]
            requested_name = str(params.get("name", "")).lower().rstrip(".")
            requested_type = str(params.get("type", "")).upper()
            zone_records = self.records.setdefault(zone_id, {})
            found: list[dict[str, str]] = []
            for item in zone_records.values():
                if (
                    item["name"].lower().rstrip(".") == requested_name
                    and item["type"].upper() == requested_type
                ):
                    found.append(dict(item))
            return {"success": True, "result": found, "errors": []}

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "zones"
            and parts[2] == "dns_records"
        ):
            zone_id = parts[1]
            zone_records = self.records.setdefault(zone_id, {})
            record_id = f"rec-{len(zone_records) + 1}"
            zone_records[record_id] = {
                "id": record_id,
                "type": str(payload["type"]),
                "name": str(payload["name"]),
                "content": str(payload["content"]),
            }
            return {"success": True, "result": dict(zone_records[record_id]), "errors": []}

        if (
            method == "PUT"
            and len(parts) == 4
            and parts[0] == "zones"
            and parts[2] == "dns_records"
        ):
            zone_id = parts[1]
            record_id = parts[3]
            zone_records = self.records.setdefault(zone_id, {})
            existing = zone_records[record_id]
            existing.update(
                {
                    "type": str(payload["type"]),
                    "name": str(payload["name"]),
                    "content": str(payload["content"]),
                }
            )
            return {"success": True, "result": dict(existing), "errors": []}

        if (
            method == "DELETE"
            and len(parts) == 4
            and parts[0] == "zones"
            and parts[2] == "dns_records"
        ):
            zone_id = parts[1]
            record_id = parts[3]
            zone_records = self.records.setdefault(zone_id, {})
            zone_records.pop(record_id, None)
            return {"success": True, "result": {}, "errors": []}

        if method == "GET" and parts == ["zones"]:
            return {
                "success": True,
                "result": [{"id": "zone-1", "name": "dispatch.test"}],
                "errors": [],
            }

        raise AssertionError(f"Unhandled request: {method} {path}")


@pytest.mark.asyncio
async def test_create_record_is_idempotent_on_duplicate_calls() -> None:
    settings = Settings(
        app_env="test",
        cloudflare_api_token_secret_name="dispatch/cloudflare/token",
    )
    secret_provider = _FakeSecretProvider()
    transport = _MockCloudflareTransport()
    provisioner = CloudflareDNSProvisioner(
        settings,
        secret_provider=secret_provider,
        transport=transport,
    )

    record = DNSRecordInput(
        record_type="TXT",
        name="mail.dispatch.test",
        value="v=spf1 include:amazonses.com -all",
    )
    first = await provisioner.create_record(zone_id="zone-1", record=record)
    second = await provisioner.create_record(zone_id="zone-1", record=record)

    assert first == second
    assert transport.post_calls == 1
    assert transport.put_calls == 0
    assert secret_provider.calls == 1


@pytest.mark.asyncio
async def test_create_record_updates_existing_when_value_changes() -> None:
    settings = Settings(
        app_env="test",
        cloudflare_api_token_secret_name="dispatch/cloudflare/token",
    )
    transport = _MockCloudflareTransport()
    provisioner = CloudflareDNSProvisioner(
        settings,
        secret_provider=_FakeSecretProvider(),
        transport=transport,
    )

    original = DNSRecordInput(
        record_type="TXT",
        name="mail.dispatch.test",
        value="v=spf1 include:amazonses.com -all",
    )
    changed = DNSRecordInput(
        record_type="TXT",
        name="mail.dispatch.test",
        value="v=spf1 include:amazonses.com ~all",
    )

    first = await provisioner.create_record(zone_id="zone-1", record=original)
    second = await provisioner.create_record(zone_id="zone-1", record=changed)

    assert first == second
    assert transport.post_calls == 1
    assert transport.put_calls == 1
