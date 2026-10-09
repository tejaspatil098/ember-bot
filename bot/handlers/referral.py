from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards.user import come_link_keyboard, user_menu
from config import get_settings
from database.crud import get_user_by_telegram_id
from database.database import async_session_factory
from services.competition_service import refresh_competition_state
from services.leaderboard_service import get_user_counts, get_user_rank
from services.referral_service import get_referral_for_referred_user

router = Router(name="referral")


async def send_referral_link(message: Message) -> None:
    if not message.from_user:
        return
    async with async_session_factory() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        await session.commit()
    if not user:
        await message.answer("Send /start first to register.")
        return
    bot = await message.bot.get_me()
    if not bot.username:
        await message.answer("The bot username is not available yet. Please try again shortly.")
        return
    link = f"https://t.me/{bot.username}?start={user.referral_code}"
    await message.answer(
        "YOUR PERSONAL INVITATION LINK\n\n"
        f"Share this Telegram link:\n{link}\n\n"
        "When someone joins through it and their action is approved, you receive +1 verified referral. "
        "The highest verified count wins the prize.",
        reply_markup=user_menu(),
    )


@router.message(Command("link"))
@router.message(F.text.in_({"My Referral Link", "🔗 My Referral Link"}))
async def referral_link(message: Message) -> None:
    await send_referral_link(message)


@router.message(Command("myreferrals"))
@router.message(F.text.in_({"My Referrals", "📊 My Referrals"}))
async def my_referrals(message: Message) -> None:
    if not message.from_user:
        return
    async with async_session_factory() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not user:
            await session.commit()
            await message.answer("Send /start first to register.")
            return
        counts = await get_user_counts(session, user.id)
        competition = await refresh_competition_state(session)
        rank = await get_user_rank(session, user.id)
        await session.commit()
    await message.answer(
        "YOUR REFERRALS\n\n"
        f"Total invited: {counts['total']}\n"
        f"Verified: {counts['verified']}\n"
        f"Pending: {counts['pending']}\n"
        f"Rejected: {counts['rejected']}\n"
        f"Cancelled: {counts['cancelled']}\n"
        f"Current rank: {f'#{rank[0]}' if rank[0] else 'Not ranked'}\n"
        f"Competition: {competition.status.title()}",
        reply_markup=user_menu(),
    )


@router.message(Command("come"))
@router.message(F.text.in_({"Come.apk Link", "🔗 Get Come.apk Link"}))
async def come_link(message: Message) -> None:
    settings = get_settings()
    await message.answer(
        "Come.apk Referral Link\n\n"
        "Complete the required action using this owner-provided link. Every participant receives the same link.\n\n"
        "After completing the action, return here and submit the requested screenshot. "
        "Opening the link alone does not count as a referral.",
        reply_markup=come_link_keyboard(settings.come_referral_link),
    )


@router.message(Command("how"))
async def how_command(message: Message) -> None:
    await message.answer(
        "Get your personal Telegram link, invite someone, and ask them to complete the action through "
        "the owner's shared Come.apk link. Their screenshot is reviewed by an admin. Only approved "
        "referrals count. The prize is paid manually by the owner.",
        reply_markup=user_menu(),
    )
