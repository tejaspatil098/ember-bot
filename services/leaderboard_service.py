from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Referral, User
from services.competition_service import calculate_rankings


async def get_leaderboard(session: AsyncSession, limit: int = 10) -> list[tuple[User, int, object]]:
    return (await calculate_rankings(session))[:limit]


async def get_user_counts(session: AsyncSession, user_id: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for status in ("PENDING", "VERIFIED", "REJECTED", "CANCELLED"):
        result = await session.execute(
            select(func.count(Referral.id)).where(
                Referral.referrer_id == user_id,
                Referral.status == status,
            )
        )
        counts[status.lower()] = int(result.scalar_one())
    counts["total"] = sum(counts.values())
    return counts


async def get_user_rank(session: AsyncSession, user_id: int) -> tuple[int | None, int, tuple[User, int, object] | None]:
    leaderboard = await calculate_rankings(session)
    for index, entry in enumerate(leaderboard, start=1):
        if entry[0].id == user_id:
            return index, entry[1], leaderboard[0] if leaderboard else None
    return None, 0, leaderboard[0] if leaderboard else None
