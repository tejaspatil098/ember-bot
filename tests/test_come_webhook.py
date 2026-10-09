from __future__ import annotations

import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from database.models import AuditLog, Referral, User, Verification
from integrations.come_webhook import ComeWebhookEvent, verify_webhook_signature
from services.referral_service import register_user
from services.verification_service import approve_referral_from_webhook


def sign(body: bytes, timestamp: str, secret: str) -> str:
    return hmac.new(
        secret.encode(),
        timestamp.encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()


class RequestStub:
    def __init__(self, body: bytes):
        self.headers = {"content-type": "application/json"}
        self._body = body

    async def stream(self):
        yield self._body


def test_webhook_signature_checks_raw_body_and_timestamp():
    body = b'{"event_id":"evt-1"}'
    timestamp = "1760000000"
    signature = sign(body, timestamp, "test-webhook-secret")

    assert verify_webhook_signature(
        body=body,
        timestamp=timestamp,
        signature=signature,
        secret="test-webhook-secret",
        now=1760000000,
    )
    assert not verify_webhook_signature(
        body=body + b" ",
        timestamp=timestamp,
        signature=signature,
        secret="test-webhook-secret",
        now=1760000000,
    )
    assert not verify_webhook_signature(
        body=body,
        timestamp="1759999699",
        signature=signature,
        secret="test-webhook-secret",
        now=1760000000,
    )


def test_webhook_event_requires_supported_event_and_positive_numeric_ids():
    valid = {
        "event_id": "evt-1",
        "event_type": "registration.verified",
        "campaign_id": "campaign-1",
        "telegram_user_id": 123,
        "come_user_id": "come-123",
    }
    assert ComeWebhookEvent.model_validate(valid).telegram_user_id == 123

    with pytest.raises(ValidationError):
        ComeWebhookEvent.model_validate({**valid, "event_type": "registration.created"})
    with pytest.raises(ValidationError):
        ComeWebhookEvent.model_validate({**valid, "telegram_user_id": True})


@pytest.mark.asyncio
async def test_signed_provider_event_approves_once_without_screenshot(session_factory):
    async with session_factory() as session:
        referrer = await register_user(
            session, telegram_id=801, username="referrer", first_name="Referrer", start_code=None
        )
        referred = await register_user(
            session,
            telegram_id=802,
            username="referred",
            first_name="Referred",
            start_code=referrer.user.referral_code,
        )
        referral = (
            await session.execute(
                __import__("sqlalchemy").select(Referral).where(
                    Referral.referred_user_id == referred.user.id
                )
            )
        ).scalar_one()

        result = await approve_referral_from_webhook(
            session,
            event_id="evt-1",
            campaign_id="campaign-1",
            telegram_user_id=referred.user.telegram_id,
            come_user_id="come-account-802",
        )
        await session.commit()

        assert result == ("APPROVED", referred.user.telegram_id)
        assert referral.status == "VERIFIED"
        verification = (
            await session.execute(
                __import__("sqlalchemy").select(Verification).where(
                    Verification.telegram_user_id == referred.user.telegram_id
                )
            )
        ).scalar_one()
        assert verification.file_kind == "WEBHOOK"
        assert verification.telegram_file_id is None
        assert verification.external_user_id == "come-account-802"
        assert verification.reviewed_by is None
        audit = (
            await session.execute(
                __import__("sqlalchemy").select(AuditLog).where(
                    AuditLog.action == "COME_WEBHOOK_APPROVAL"
                )
            )
        ).scalar_one()
        assert audit.details["event_id"] == "evt-1"

        duplicate_delivery = await approve_referral_from_webhook(
            session,
            event_id="evt-1",
            campaign_id="campaign-1",
            telegram_user_id=referred.user.telegram_id,
            come_user_id="come-account-802",
        )
        await session.commit()
        assert duplicate_delivery == ("ALREADY_VERIFIED", referred.user.telegram_id)


@pytest.mark.asyncio
async def test_webhook_rejects_reuse_of_approved_come_account(session_factory):
    async with session_factory() as session:
        first_referrer = await register_user(
            session, telegram_id=901, username="ref1", first_name="Ref1", start_code=None
        )
        first_referred = await register_user(
            session,
            telegram_id=902,
            username="person1",
            first_name="Person1",
            start_code=first_referrer.user.referral_code,
        )
        second_referrer = await register_user(
            session, telegram_id=903, username="ref2", first_name="Ref2", start_code=None
        )
        second_referred = await register_user(
            session,
            telegram_id=904,
            username="person2",
            first_name="Person2",
            start_code=second_referrer.user.referral_code,
        )

        first = await approve_referral_from_webhook(
            session,
            event_id="evt-1",
            campaign_id="campaign-1",
            telegram_user_id=first_referred.user.telegram_id,
            come_user_id="reused-account",
        )
        await session.commit()
        assert first[0] == "APPROVED"

        second = await approve_referral_from_webhook(
            session,
            event_id="evt-2",
            campaign_id="campaign-1",
            telegram_user_id=second_referred.user.telegram_id,
            come_user_id="reused-account",
        )
        await session.commit()
        assert second == ("DUPLICATE_EXTERNAL_ACCOUNT", second_referred.user.telegram_id)


@pytest.mark.asyncio
async def test_signed_webhook_route_approves_and_is_idempotent(session_factory, monkeypatch):
    import main as bot_main

    secret = "route-test-secret"
    campaign_id = "campaign-route-test"
    monkeypatch.setattr(bot_main.settings, "come_webhook_secret", secret)
    monkeypatch.setattr(bot_main.settings, "come_webhook_campaign_id", campaign_id)
    monkeypatch.setattr(bot_main, "async_session_factory", session_factory)
    fake_bot = SimpleNamespace(send_message=AsyncMock())
    monkeypatch.setattr(bot_main, "bot", fake_bot)

    async with session_factory() as session:
        referrer = await register_user(
            session, telegram_id=1001, username="route-ref", first_name="RouteRef", start_code=None
        )
        referred = await register_user(
            session,
            telegram_id=1002,
            username="route-user",
            first_name="RouteUser",
            start_code=referrer.user.referral_code,
        )
        await session.commit()

    event = {
        "event_id": "route-event-1",
        "event_type": "registration.verified",
        "campaign_id": campaign_id,
        "telegram_user_id": referred.user.telegram_id,
        "come_user_id": "route-come-account",
    }
    body = json.dumps(event, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = sign(body, timestamp, secret)

    first = await bot_main.receive_come_webhook(
        RequestStub(body),
        x_come_timestamp=timestamp,
        x_come_signature=signature,
    )
    second = await bot_main.receive_come_webhook(
        RequestStub(body),
        x_come_timestamp=timestamp,
        x_come_signature=signature,
    )

    assert first == {"status": "approved", "event_id": "route-event-1"}
    assert second == {"status": "already_processed", "event_id": "route-event-1"}
    fake_bot.send_message.assert_awaited_once()
