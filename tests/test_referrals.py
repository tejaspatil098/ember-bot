from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from database.models import Referral, User
from bot.keyboards.user import user_menu
from services.referral_service import register_user


def test_main_menu_shows_come_link_and_personal_referral_link():
    labels = [
        button.text
        for row in user_menu().keyboard
        for button in row
    ]
    assert labels[0] == "Come.apk Link"
    assert "Come.apk Link" in labels
    assert "My Referral Link" in labels


@pytest.mark.asyncio
async def test_registration_and_unique_referral_code(session_factory):
    async with session_factory() as session:
        result = await register_user(
            session,
            telegram_id=101,
            username="alice",
            first_name="Alice",
            start_code=None,
        )
        await session.commit()
        assert result.created is True
        assert re.fullmatch(r"[A-Z0-9]{8}", result.user.referral_code)

        duplicate = await register_user(
            session,
            telegram_id=101,
            username="alice_new",
            first_name="Alice",
            start_code=None,
        )
        await session.commit()
        assert duplicate.created is False
        assert duplicate.user.referral_code == result.user.referral_code
        assert duplicate.user.username == "alice_new"


@pytest.mark.asyncio
async def test_referral_attribution_is_immutable_and_unique(session_factory):
    async with session_factory() as session:
        owner = await register_user(
            session, telegram_id=201, username="owner", first_name="Owner", start_code=None
        )
        alternate = await register_user(
            session, telegram_id=202, username="other", first_name="Other", start_code=None
        )
        invited = await register_user(
            session,
            telegram_id=203,
            username="invited",
            first_name="Invited",
            start_code=owner.user.referral_code,
        )
        assert invited.referral_created is True
        relationship = (
            await session.execute(
                select(Referral).where(Referral.referred_user_id == invited.user.id)
            )
        ).scalar_one()
        assert relationship.referrer_id == owner.user.id
        assert relationship.status == "PENDING"

        duplicate = await register_user(
            session,
            telegram_id=203,
            username="invited",
            first_name="Invited",
            start_code=alternate.user.referral_code,
        )
        assert duplicate.referral_error == "ALREADY_ATTRIBUTED"
        assert (
            await session.execute(
                select(Referral).where(Referral.referred_user_id == invited.user.id)
            )
        ).scalar_one().referrer_id == owner.user.id
        await session.commit()


@pytest.mark.asyncio
async def test_self_referral_is_blocked(session_factory):
    async with session_factory() as session:
        user = await register_user(
            session, telegram_id=301, username="self", first_name="Self", start_code=None
        )
        self_attempt = await register_user(
            session,
            telegram_id=301,
            username="self",
            first_name="Self",
            start_code=user.user.referral_code,
        )
        assert self_attempt.referral_error == "SELF_REFERRAL"
        assert (
            await session.execute(select(Referral))
        ).scalars().all() == []
        await session.commit()


@pytest.mark.asyncio
async def test_fixed_link_is_configured_once(session_factory):
    from config import get_settings

    async with session_factory() as session:
        first = await register_user(
            session, telegram_id=401, username="first", first_name="First", start_code=None
        )
        second = await register_user(
            session, telegram_id=402, username="second", first_name="Second", start_code=None
        )
        await session.commit()
    settings = get_settings()
    assert settings.come_referral_link == "https://example.com/authorized-referral"
    assert first.user.referral_code != second.user.referral_code
