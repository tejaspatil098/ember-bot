from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Competition, User


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def get_user_by_referral_code(session: AsyncSession, code: str) -> User | None:
    result = await session.execute(
        select(User).where(User.referral_code == code.strip().upper())
    )
    return result.scalar_one_or_none()


async def get_competition(session: AsyncSession) -> Competition | None:
    result = await session.execute(select(Competition).where(Competition.id == 1))
    return result.scalar_one_or_none()
