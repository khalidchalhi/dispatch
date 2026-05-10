from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from libs.core.config import Settings
from libs.core.domains.provisioning import Boto3SesDomainProvisioner


class _FakeClientError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.response = {"Error": {"Code": code, "Message": message}}


@dataclass(slots=True)
class _FakeSesClient:
    create_identity_calls: list[dict[str, object]] = field(default_factory=list)
    get_identity_calls: list[dict[str, object]] = field(default_factory=list)
    create_configuration_set_calls: list[dict[str, object]] = field(default_factory=list)
    create_event_destination_calls: list[dict[str, object]] = field(default_factory=list)
    update_event_destination_calls: list[dict[str, object]] = field(default_factory=list)
    put_mail_from_calls: list[dict[str, object]] = field(default_factory=list)
    should_raise_event_destination_exists: bool = False

    def create_email_identity(self, **kwargs: object) -> dict[str, object]:
        self.create_identity_calls.append(dict(kwargs))
        return {"IdentityType": "DOMAIN"}

    def get_email_identity(self, **kwargs: object) -> dict[str, object]:
        self.get_identity_calls.append(dict(kwargs))
        return {
            "IdentityArn": "arn:aws:ses:us-east-1:000000000000:identity/example.com",
            "VerifiedForSendingStatus": True,
            "DkimAttributes": {
                "Tokens": ["dkim1", "dkim2", "dkim3"],
                "SigningEnabled": True,
            },
        }

    def create_configuration_set(self, **kwargs: object) -> dict[str, object]:
        self.create_configuration_set_calls.append(dict(kwargs))
        return {}

    def create_configuration_set_event_destination(self, **kwargs: object) -> dict[str, object]:
        self.create_event_destination_calls.append(dict(kwargs))
        if self.should_raise_event_destination_exists:
            raise _FakeClientError("AlreadyExistsException", "event destination already exists")
        return {}

    def update_configuration_set_event_destination(self, **kwargs: object) -> dict[str, object]:
        self.update_event_destination_calls.append(dict(kwargs))
        return {}

    def put_email_identity_mail_from_attributes(self, **kwargs: object) -> dict[str, object]:
        self.put_mail_from_calls.append(dict(kwargs))
        return {}

    def delete_email_identity(self, **kwargs: object) -> dict[str, object]:
        _ = kwargs
        return {}


@pytest.mark.asyncio
async def test_ses_provisioner_ensure_identity_returns_dkim_tokens() -> None:
    settings = Settings(app_env="test")
    fake_client = _FakeSesClient()
    provisioner = Boto3SesDomainProvisioner(settings, client=fake_client)

    state = await provisioner.ensure_identity(domain_name="example.com")

    assert state.identity_arn is not None
    assert state.verified_for_sending is True
    assert state.dkim_tokens == ["dkim1", "dkim2", "dkim3"]
    assert state.dkim_signing_enabled is True
    assert len(fake_client.create_identity_calls) == 1
    assert len(fake_client.get_identity_calls) == 1


@pytest.mark.asyncio
async def test_ses_provisioner_ensure_configuration_set_upserts_event_destination() -> None:
    settings = Settings(app_env="test")
    fake_client = _FakeSesClient(should_raise_event_destination_exists=True)
    provisioner = Boto3SesDomainProvisioner(settings, client=fake_client)

    await provisioner.ensure_configuration_set(
        name="example.com-default",
        sns_topic_arn="arn:aws:sns:us-east-1:000000000000:dispatch-events",
    )

    assert len(fake_client.create_configuration_set_calls) == 1
    assert len(fake_client.create_event_destination_calls) == 1
    assert len(fake_client.update_event_destination_calls) == 1


@pytest.mark.asyncio
async def test_ses_provisioner_configures_mail_from_subdomain() -> None:
    settings = Settings(app_env="test")
    fake_client = _FakeSesClient()
    provisioner = Boto3SesDomainProvisioner(settings, client=fake_client)

    await provisioner.ensure_mail_from(
        domain_name="example.com",
        mail_from_domain="mail.example.com",
    )

    assert len(fake_client.put_mail_from_calls) == 1
    call: dict[str, Any] = fake_client.put_mail_from_calls[0]
    assert call["EmailIdentity"] == "example.com"
    assert call["MailFromDomain"] == "mail.example.com"
    assert call["BehaviorOnMxFailure"] == "USE_DEFAULT_VALUE"
