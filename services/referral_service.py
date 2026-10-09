from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.crud import get_user_by_referral_code, get_user_by_telegram_id
from database.models import Referral, User
from services.competition_service import record_audit, refresh_competition_state, utcnow
from utils.security import generate_referral_code, normalize_referral_code

logger = logging.getLogger("referral_bot.referrals")


@dataclass
class RegistrationResult:
    user: User
    created: bool
    referral_created: bool = False
    referral_error: str | None = None
    referrer: User | None = None


async def register_user(
    session: AsyncSession,
    *,
    telegram_id: int,
    username: str | None,
    first_name: str,
    start_code: str | None,
) -> RegistrationResult:
    user = await get_user_by_telegram_id(session, telegram_id)
    created = user is None
    if user is None:
        for _ in range(5):
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name[:128],
                referral_code=generate_referral_code(),
            )
            session.add(user)
            try:
                await session.flush()
                break
            except IntegrityError:
                await session.rollback()
                existing = await get_user_by_telegram_id(session, telegram_id)
                if existing:
                    user = existing
                    created = False
                    break
                user = None
        if user is None:
            raise RuntimeError("Unable to create a unique referral code.")
    else:
        user.username = username
        user.first_name = first_name[:128]

    outcome = RegistrationResult(user=user, created=created)
    code = normalize_referral_code(start_code or "")
    if not code:
        await session.flush()
        return outcome

    referrer = await get_user_by_referral_code(session, code)
    if not referrer:
        outcome.referral_error = "INVALID_CODE"
        await session.flush()
        return outcome
    if referrer.id == user.id:
        outcome.referral_error = "SELF_REFERRAL"
        await record_audit(
            session,
            admin_id=None,
            action="SELF_REFERRAL_BLOCKED",
            target_user_id=telegram_id,
        )
        await session.flush()
        return outcome

    previous = await session.execute(
        select(Referral).where(Referral.referred_user_id == user.id)
    )
    existing_referral = previous.scalar_one_or_none()
    if existing_referral:
        if existing_referral.referrer_id != referrer.id:
            outcome.referral_error = "ALREADY_ATTRIBUTED"
        else:
            outcome.referral_error = "DUPLICATE"
        await record_audit(
            session,
            admin_id=None,
            action="REFERRAL_DUPLICATE",
            target_user_id=telegram_id,
            details={"referrer_telegram_id": referrer.telegram_id},
        )
        await session.flush()
        return outcome

    competition = await refresh_competition_state(session)
    if competition.status != "ACTIVE":
        outcome.referral_error = "COMPETITION_CLOSED"
        await session.flush()
        return outcome

    now = utcnow()
    recent_count = await session.execute(
        select(func.count(Referral.id)).where(
            Referral.referrer_id == referrer.id,
            Referral.created_at >= now - timedelta(hours=1),
        )
    )
    count = int(recent_count.scalar_one())
    session.add(
        Referral(
            referrer_id=referrer.id,
            referred_user_id=user.id,
            status="PENDING",
            created_at=now,
        )
    )
    if count >= 25:
        logger.warning(
            "suspicious referral velocity: referrer_telegram_id=%s count_last_hour=%s",
            referrer.telegram_id,
            count + 1,
        )
        await record_audit(
            session,
            admin_id=None,
            action="SUSPICIOUS_REFERRAL_VELOCITY",
            target_user_id=referrer.telegram_id,
            details={"count_last_hour": count + 1},
        )
    await session.flush()
    outcome.referral_created = True
    outcome.referrer = referrer
    logger.info(
        "REFERRAL_CREATED referrer_telegram_id=%s referred_telegram_id=%s",
        referrer.telegram_id,
        telegram_id,
    )
    return outcome


async def get_referral_for_referred_user(session: AsyncSession, user_id: int) -> Referral | None:
    result = await session.execute(
        select(Referral).where(Referral.referred_user_id == user_id)
    )
    return result.scalar_one_or_none()


async def count_all_referrals(session: AsyncSession) -> int:
    result = await session.execute(select(func.count(Referral.id)))
    return int(result.scalar_one())


async def count_referrals_by_status(session: AsyncSession, status: str) -> int:
    result = await session.execute(
        select(func.count(Referral.id)).where(Referral.status == status)
    )
    return int(result.scalar_one())
