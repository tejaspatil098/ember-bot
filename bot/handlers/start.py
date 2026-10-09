from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from bot.keyboards.user import come_link_keyboard, user_menu
from config import get_settings
from database.database import async_session_factory
from services.competition_service import refresh_competition_state
from services.referral_service import register_user

router = Router(name="start")
logger = logging.getLogger("referral_bot.start")

WELCOME = (
    "Welcome to the Referral Competition!\n\n"
    "Prize: ₹{prize}\n\n"
    "Share your personal Telegram invitation link. Only referrals verified by the competition owner count.\n\n"
    "Choose an option below. For help, use Contact Admin."
)


@router.message(CommandStart())
async def start(message: Message) -> None:
    if not message.from_user:
        return
    parts = (message.text or "").split(maxsplit=1)
    payload = parts[1].strip() if len(parts) > 1 else None
    settings = get_settings()
    async with async_session_factory() as session:
        result = await register_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name or "",
            start_code=payload,
        )
        competition = await refresh_competition_state(session)
        await session.commit()

    if result.created:
        logger.info("USER_REGISTERED telegram_user_id=%s", message.from_user.id)
    await message.answer(
        WELCOME.format(prize=f"{competition.prize_amount:,.0f}"),
        reply_markup=user_menu(),
    )
    if result.referral_created:
        await message.answer(
            "Referral link detected. The participant who invited you will receive credit only "
            "after your required action is reviewed and approved.\n\n"
            "1. Open the competition owner's Come.apk link.\n"
            "2. Complete the required registration/action.\n"
            "3. Return here and submit a clear screenshot.\n\n"
            "Your referral is pending until verification.",
            reply_markup=come_link_keyboard(settings.come_referral_link),
        )
        return
    if result.referral_error == "SELF_REFERRAL":
        await message.answer("Self-referrals are not allowed.")
    elif result.referral_error == "ALREADY_ATTRIBUTED":
        await message.answer("Your original referrer is already recorded and cannot be changed.")
    elif result.referral_error == "INVALID_CODE":
        await message.answer("That invitation link is invalid. Ask the participant for a current link.")
    elif result.referral_error == "COMPETITION_CLOSED":
        await message.answer("The competition is not accepting new referrals right now.")


@router.message(F.text.in_({"How It Works", "ℹ️ How It Works"}))
async def how_it_works(message: Message) -> None:
    settings = get_settings()
    text = (
        f"HOW THE COMPETITION WORKS\n\n"
        "1. Get your personal Telegram invitation link.\n"
        "2. Share it with friends.\n"
        "3. Your friend starts the bot through your link.\n"
        "4. Your friend receives the same owner-provided Come.apk link as everyone else.\n"
        "5. Your friend completes the required action and submits a screenshot.\n"
        "6. The competition owner reviews the submission.\n"
        f"7. An approved referral adds 1 verified referral. The highest verified count wins ₹{settings.prize_amount:,}.\n\n"
        "Fake, duplicate, reused, or invalid referrals do not count. The prize is paid manually by the owner."
    )
    await message.answer(text, reply_markup=user_menu())
