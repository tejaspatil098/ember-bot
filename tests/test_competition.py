from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from database.models import Referral
from services.competition_service import (
    calculate_rankings,
    ensure_competition,
    set_competition_status,
)
from services.referral_service import register_user
from utils.security import is_admin, normalize_referral_code


@pytest.mark.asyncio
async def test_rank_tie_goes_to_first_to_reach_total(session_factory):
    async with session_factory() as session:
        alice = await register_user(
            session, telegram_id=701, username="alice", first_name="Alice", start_code=None
        )
        bob = await register_user(
            session, telegram_id=702, username="bob", first_name="Bob", start_code=None
        )
        alice_referred = [
            await register_user(
                session,
                telegram_id=710 + index,
                username=f"a{index}",
                first_name="A",
                start_code=alice.user.referral_code,
            )
            for index in range(2)
        ]
        bob_referred = [
            await register_user(
                session,
                telegram_id=720 + index,
                username=f"b{index}",
                first_name="B",
                start_code=bob.user.referral_code,
            )
            for index in range(2)
        ]
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        referrals = (
            await session.execute(
                __import__("sqlalchemy").select(Referral).order_by(Referral.id)
            )
        ).scalars().all()
        for index, referral in enumerate(referrals):
            referral.status = "VERIFIED"
            referral.verified_at = base + timedelta(minutes=index)
        await session.commit()
        ranking = await calculate_rankings(session)
        assert [row[0].telegram_id for row in ranking] == [701, 702]
        assert [row[1] for row in ranking] == [2, 2]


@pytest.mark.asyncio
async def test_ending_competition_picks_winner_and_cancels_pending(session_factory):
    async with session_factory() as session:
        winner = await register_user(
            session, telegram_id=801, username="winner", first_name="Winner", start_code=None
        )
        invitee = await register_user(
            session,
            telegram_id=802,
            username="invitee",
            first_name="Invitee",
            start_code=winner.user.referral_code,
        )
        pending_invitee = await register_user(
            session,
            telegram_id=803,
            username="pending",
            first_name="Pending",
            start_code=winner.user.referral_code,
        )
        counted_referral = (
            await session.execute(
                select(Referral).where(
                    Referral.referred_user_id == invitee.user.id
                )
            )
        ).scalar_one()
        counted_referral.status = "VERIFIED"
        counted_referral.verified_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        await ensure_competition(session)
        ended = await set_competition_status(session, "ENDED")
        await session.commit()
        assert ended.status == "ENDED"
        assert ended.winner_user_id == winner.user.id
        relationship = (
            await session.execute(
                select(Referral).where(
                    Referral.referred_user_id == pending_invitee.user.id
                )
            )
        ).scalar_one()
        assert relationship.status == "CANCELLED"
        assert pending_invitee.referral_created


def test_admin_authorization_and_referral_code_validation():
    assert is_admin(1001, {1001, 1002}) is True
    assert is_admin(1003, {1001, 1002}) is False
    assert normalize_referral_code("ab12cd34") == "AB12CD34"
    assert normalize_referral_code("not-a-code") is None
