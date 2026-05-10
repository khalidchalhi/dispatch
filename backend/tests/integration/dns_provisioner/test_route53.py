from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from libs.core.config import Settings
from libs.dns_provisioner.base import DNSRecordInput
from libs.dns_provisioner.route53 import Route53DNSProvisioner


@dataclass(slots=True)
class _FakeRoute53Client:
    zones: list[dict[str, str]] = field(
        default_factory=lambda: [{"Id": "/hostedzone/ZONE123", "Name": "dispatch.test."}]
    )
    record_sets: dict[str, dict[tuple[str, str], dict[str, object]]] = field(default_factory=dict)
    change_calls: list[dict[str, object]] = field(default_factory=list)

    def list_hosted_zones(self, **kwargs: object) -> dict[str, object]:
        _ = kwargs
        return {"HostedZones": list(self.zones)}

    def change_resource_record_sets(self, **kwargs: object) -> dict[str, object]:
        self.change_calls.append(dict(kwargs))
        zone_id = str(kwargs["HostedZoneId"])
        change_batch = kwargs["ChangeBatch"]
        assert isinstance(change_batch, dict)
        changes = change_batch.get("Changes")
        assert isinstance(changes, list)
        zone_records = self.record_sets.setdefault(zone_id, {})
        for change in changes:
            assert isinstance(change, dict)
            action = str(change["Action"])
            record_set = change["ResourceRecordSet"]
            assert isinstance(record_set, dict)
            key = (
                str(record_set["Name"]).lower().rstrip("."),
                str(record_set["Type"]).upper(),
            )
            if action == "DELETE":
                zone_records.pop(key, None)
            else:
                zone_records[key] = dict(record_set)
        return {"ChangeInfo": {"Id": "change-1"}}

    def list_resource_record_sets(self, **kwargs: object) -> dict[str, object]:
        zone_id = str(kwargs["HostedZoneId"])
        start_name = str(kwargs["StartRecordName"]).lower().rstrip(".")
        start_type = str(kwargs["StartRecordType"]).upper()
        zone_records = self.record_sets.setdefault(zone_id, {})
        result: list[dict[str, object]] = []
        for (name, record_type), payload in zone_records.items():
            if name == start_name and record_type == start_type:
                result.append(dict(payload))
        return {"ResourceRecordSets": result}


@pytest.mark.asyncio
async def test_route53_provisioner_happy_path_upsert_verify_delete() -> None:
    fake_client = _FakeRoute53Client()
    settings = Settings(app_env="test")
    provisioner = Route53DNSProvisioner(settings=settings, client=fake_client)

    zones = await provisioner.list_zones()
    assert zones[0].id == "ZONE123"

    record = DNSRecordInput(
        record_type="TXT",
        name="mail.dispatch.test",
        value="v=spf1 include:amazonses.com -all",
    )
    record_id = await provisioner.create_record(zone_id="ZONE123", record=record)
    assert record_id == "TXT:mail.dispatch.test"

    assert await provisioner.verify_record(zone_id="ZONE123", record=record) is True

    updated = DNSRecordInput(
        record_type="TXT",
        name="mail.dispatch.test",
        value="v=spf1 include:amazonses.com ~all",
    )
    await provisioner.update_record(zone_id="ZONE123", record_id=record_id, record=updated)
    assert await provisioner.verify_record(zone_id="ZONE123", record=updated) is True
    assert await provisioner.verify_record(zone_id="ZONE123", record=record) is False

    await provisioner.delete_record(zone_id="ZONE123", record_id=record_id)
    assert await provisioner.verify_record(zone_id="ZONE123", record=updated) is False


@pytest.mark.asyncio
async def test_route53_provisioner_batches_upserts_in_single_change_call() -> None:
    fake_client = _FakeRoute53Client()
    settings = Settings(app_env="test")
    provisioner = Route53DNSProvisioner(settings=settings, client=fake_client)

    records = [
        DNSRecordInput(
            record_type="TXT",
            name="mail.dispatch.test",
            value="v=spf1 include:amazonses.com -all",
        ),
        DNSRecordInput(
            record_type="MX",
            name="mail.dispatch.test",
            value="feedback-smtp.us-east-1.amazonses.com",
            priority=10,
        ),
    ]

    provider_ids = await provisioner.upsert_records(zone_id="ZONE123", records=records)

    assert len(provider_ids) == 2
    assert len(fake_client.change_calls) == 1
    only_call = fake_client.change_calls[0]
    change_batch = only_call.get("ChangeBatch")
    assert isinstance(change_batch, dict)
    changes = change_batch.get("Changes")
    assert isinstance(changes, list)
    assert len(changes) == 2
