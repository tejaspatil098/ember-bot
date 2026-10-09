from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards.user import user_menu
from config import get_settings
from database.database import async_session_factory
from services.competition_service import ensure_competition, refresh_competition_state
from services.leaderboard_service import get_leaderboard, get_user_rank
from database.crud import get_user_by_telegram_id

router = Router(name="leaderboard")


def display_name(username: str | None, position: int) -> str:
    return f"@{username}" if username else f"Participant {position}"


@router.message(Command("leaderboard"))
@router.message(F.text.in_({"Leaderboard", "🏆 Leaderboard"}))
async def leaderboard(message: Message) -> None:
    settings = get_settings()
    async with async_session_factory() as session:
        competition = await refresh_competition_state(session)
        entries = await get_leaderboard(session, limit=10)
        await session.commit()
    if not entries:
        await message.answer(
            f"LIVE LEADERBOARD\n\nNo verified referrals yet.\n\nPrize: ₹{competition.prize_amount:,.0f}",
            reply_markup=user_menu(),
        )
        return
    lines = ["LIVE LEADERBOARD"]
    medals = ["1.", "2.", "3."]
    for index, (user, count, _) in enumerate(entries, start=1):
        prefix = medals[index - 1] if index <= 3 else f"{index}."
        lines.append(f"{prefix} {display_name(user.username, index)} — {count} verified")
    lines.extend(
        [
            "",
            f"Prize: ₹{competition.prize_amount:,.0f}",
            f"Status: {competition.status.title()}",
            "Ties are ordered by who reached that verified count first.",
        ]
    )
    await message.answer("\n".join(lines), reply_markup=user_menu())


@router.message(Command("rank"))
async def rank_command(message: Message) -> None:
    if not message.from_user:
        return
    async with async_session_factory() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not user:
            await session.commit()
            await message.answer("Send /start first to register.")
            return
        current_rank, verified, leader = await get_user_rank(session, user.id)
        competition = await ensure_competition(session)
        await session.commit()
    if leader:
        leader_user, leader_count, _ = leader
        leader_name = display_name(leader_user.username, 1)
    else:
        leader_name, leader_count = "No leader yet", 0
    await message.answer(
        "YOUR RANK\n\n"
        f"Current position: {f'#{current_rank}' if current_rank else 'Not ranked yet'}\n"
        f"Verified referrals: {verified}\n"
        f"Leader: {leader_name}\n"
        f"Leader's verified referrals: {leader_count}\n"
        f"Prize: ₹{competition.prize_amount:,.0f}",
        reply_markup=user_menu(),
    )
