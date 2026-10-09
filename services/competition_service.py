from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database.crud import get_competition
from database.models import Competition, Referral, User, Verification


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def ensure_competition(session: AsyncSession) -> Competition:
    competition = await get_competition(session)
    if competition:
        return competition

    settings = get_settings()
    now = utcnow()
    if settings.competition_end and settings.competition_end <= now:
        status = "ENDED"
    elif settings.competition_start and settings.competition_start > now:
        status = "SCHEDULED"
    else:
        status = "ACTIVE"
    competition = Competition(
        id=1,
        name=settings.competition_name,
        start_time=settings.competition_start,
        end_time=settings.competition_end,
        prize_amount=Decimal(settings.prize_amount),
        status=status,
    )
    session.add(competition)
    await session.flush()
    return competition


async def record_audit(
    session: AsyncSession,
    *,
    admin_id: int | None,
    action: str,
    target_user_id: int | None = None,
    details: dict | None = None,
) -> None:
    from database.models import AuditLog

    session.add(
        AuditLog(
            admin_id=admin_id,
            action=action,
            target_user_id=target_user_id,
            details=details,
        )
    )


async def calculate_rankings(session: AsyncSession) -> list[tuple[User, int, datetime | None]]:
    result = await session.execute(
        select(User, Referral.verified_at)
        .join(Referral, Referral.referrer_id == User.id)
        .where(Referral.status == "VERIFIED")
        .order_by(Referral.verified_at.asc())
    )
    last_reached: dict[int, datetime | None] = {}
    for user, verified_at in result.all():
        last_reached[user.id] = verified_at

    count_result = await session.execute(
        select(Referral.referrer_id, Referral.id)
        .where(Referral.status == "VERIFIED")
        .order_by(Referral.verified_at.asc())
    )
    counts: dict[int, int] = {}
    for referrer_id, _ in count_result.all():
        counts[referrer_id] = counts.get(referrer_id, 0) + 1

    users_result = await session.execute(select(User).where(User.id.in_(counts.keys())))
    users = {user.id: user for user in users_result.scalars().all()}
    ranked = [
        (
            users[user_id],
            count,
            (
                last_reached[user_id].replace(tzinfo=timezone.utc)
                if last_reached.get(user_id) and last_reached[user_id].tzinfo is None
                else last_reached.get(user_id)
            ),
        )
        for user_id, count in counts.items()
        if user_id in users
    ]
    return sorted(
        ranked,
        key=lambda row: (-row[1], row[2] or datetime.max.replace(tzinfo=timezone.utc), row[0].id),
    )


async def set_competition_status(session: AsyncSession, status: str) -> Competition:
    competition = await ensure_competition(session)
    if competition.status == "ENDED":
        return competition

    if status == "LOCKED":
        competition.status = "LOCKED"
    elif status == "ENDED":
        # Unresolved evidence does not count at close. This is the published
        # competition rule when no external verification feed is available.
        await session.execute(
            update(Verification)
            .where(Verification.status.in_(["PENDING", "MANUAL_REVIEW"]))
            .values(status="CANCELLED", rejection_reason="Competition ended before review.")
        )
        await session.execute(
            update(Referral)
            .where(Referral.status == "PENDING")
            .values(status="CANCELLED")
        )
        rankings = await calculate_rankings(session)
        competition.winner_user_id = rankings[0][0].id if rankings else None
        competition.status = "ENDED"
        competition.end_time = competition.end_time or utcnow()
    else:
        raise ValueError("Competition status must be LOCKED or ENDED.")

    await session.flush()
    return competition


async def refresh_competition_state(session: AsyncSession) -> Competition:
    competition = await ensure_competition(session)
    now = utcnow()
    if competition.status == "SCHEDULED" and (
        competition.start_time is None or competition.start_time <= now
    ):
        competition.status = "ACTIVE"
    if competition.end_time and competition.end_time <= now and competition.status != "ENDED":
        await set_competition_status(session, "ENDED")
        competition = await ensure_competition(session)
    await session.flush()
    return competition


async def update_competition_setting(
    session: AsyncSession,
    *,
    admin_id: int,
    field: str,
    value: str | int | datetime,
) -> Competition:
    allowed = {"name", "prize_amount", "start_time", "end_time"}
    if field not in allowed:
        raise ValueError("Unsupported competition setting.")
    competition = await ensure_competition(session)
    if competition.status == "ENDED":
        raise ValueError("The competition has ended; its settings are locked.")
    setattr(competition, field, Decimal(value) if field == "prize_amount" else value)
    if competition.start_time and competition.end_time and competition.end_time <= competition.start_time:
        raise ValueError("End time must be later than start time.")
    if competition.status in {"ACTIVE", "SCHEDULED"}:
        competition.status = (
            "SCHEDULED"
            if competition.start_time and competition.start_time > utcnow()
            else "ACTIVE"
        )
    await record_audit(
        session,
        admin_id=admin_id,
        action="COMPETITION_SETTING_CHANGED",
        details={"field": field, "value": str(value)},
    )
    await session.flush()
    return competition
