from __future__ import annotations

import io
import logging
from asyncio import to_thread

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards.admin import review_keyboard
from bot.keyboards.user import user_menu
from bot.states.verification import VerificationStates
from config import get_settings
from database.crud import get_user_by_telegram_id
from database.database import async_session_factory
from services.referral_service import get_referral_for_referred_user
from services.screenshot_service import ScreenshotValidationError, analyze_screenshot
from services.verification_service import (
    DuplicateScreenshotError,
    SubmissionRateLimitError,
    list_pending_verifications,
    submit_verification,
)

router = Router(name="verification")
logger = logging.getLogger("referral_bot.verification_handler")
MAX_TELEGRAM_PHOTO_BYTES = 20 * 1024 * 1024


@router.message(Command("verify"))
@router.message(F.text.in_({"Submit Verification", "📸 Submit Verification"}))
async def start_verification(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    async with async_session_factory() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        referral = await get_referral_for_referred_user(session, user.id) if user else None
        pending = []
        if referral:
            pending = [
                row
                for row in await list_pending_verifications(session)
                if row[0].referral_id == referral.id
            ]
        await session.commit()
    if not user:
        await message.answer("Send /start first to register.", reply_markup=user_menu())
        return
    if not referral:
        await message.answer(
            "There is no Telegram referral attached to your account, so this submission cannot count toward the competition.",
            reply_markup=user_menu(),
        )
        return
    if referral.status != "PENDING":
        await message.answer(
            f"This referral is {referral.status.lower()} and cannot accept another verification.",
            reply_markup=user_menu(),
        )
        return
    if pending:
        await message.answer(
            "Your screenshot is already waiting for admin review. It will not count until approved.",
            reply_markup=user_menu(),
        )
        return
    settings = get_settings()
    await state.set_state(VerificationStates.waiting_for_screenshot)
    await message.answer(
        "Submit Verification\n\n"
        "Upload a clear screenshot that shows the required information from Come.apk.\n"
        "Accepted formats: JPG, JPEG, PNG.\n"
        f"Maximum size: {settings.max_screenshot_size_mb} MB.\n\n"
        "The screenshot will be reviewed by a competition admin. OCR and image similarity checks are only screening signals.",
        reply_markup=user_menu(),
    )


@router.message(VerificationStates.waiting_for_screenshot, F.photo)
async def receive_photo(message: Message, state: FSMContext) -> None:
    photo = message.photo[-1]
    await _process_file(
        message=message,
        state=state,
        telegram_file_id=photo.file_id,
        file_size=photo.file_size,
        file_kind="PHOTO",
    )


@router.message(VerificationStates.waiting_for_screenshot, F.document)
async def receive_document(message: Message, state: FSMContext) -> None:
    document = message.document
    file_name = (document.file_name or "").lower()
    if not file_name.endswith((".jpg", ".jpeg", ".png")) or document.mime_type not in {
        "image/jpeg",
        "image/png",
    }:
        await message.answer("Upload a JPG, JPEG, or PNG image file.")
        return
    await _process_file(
        message=message,
        state=state,
        telegram_file_id=document.file_id,
        file_size=document.file_size,
        file_kind="DOCUMENT",
    )


@router.message(VerificationStates.waiting_for_screenshot)
async def unsupported_upload(message: Message) -> None:
    await message.answer("Please send a JPG, JPEG, or PNG screenshot.")


async def _process_file(
    *,
    message: Message,
    state: FSMContext,
    telegram_file_id: str,
    file_size: int | None,
    file_kind: str,
) -> None:
    if not message.from_user:
        return
    settings = get_settings()
    max_bytes = settings.max_screenshot_size_mb * 1024 * 1024
    if file_size and file_size > max_bytes:
        await message.answer(
            f"The screenshot exceeds the {settings.max_screenshot_size_mb} MB limit. Please upload a smaller image."
        )
        return
    if file_size and file_size > MAX_TELEGRAM_PHOTO_BYTES:
        await message.answer("The image is too large for safe processing.")
        return

    try:
        telegram_file = await message.bot.get_file(telegram_file_id)
        stream = io.BytesIO()
        await message.bot.download_file(telegram_file.file_path, destination=stream)
        image_bytes = stream.getvalue()
        analysis = await to_thread(
            analyze_screenshot,
            image_bytes,
            max_size_bytes=max_bytes,
        )
    except ScreenshotValidationError as exc:
        await message.answer(f"Screenshot not accepted: {exc}")
        return
    except Exception:
        logger.exception("SCREENSHOT_RECEIVED processing failed telegram_user_id=%s", message.from_user.id)
        await message.answer("The screenshot could not be processed right now. Please try again later.")
        return

    async with async_session_factory() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        referral = await get_referral_for_referred_user(session, user.id) if user else None
        if not user or not referral or referral.status != "PENDING":
            await session.commit()
            await message.answer("Your referral is no longer eligible for verification.")
            await state.clear()
            return
        try:
            verification = await submit_verification(
                session,
                user=user,
                referral=referral,
                telegram_file_id=telegram_file_id,
                file_kind=file_kind,
                analysis=analysis,
            )
            await session.commit()
        except DuplicateScreenshotError as exc:
            await session.commit()
            await message.answer(
                f"Screenshot Already Used\n\n{exc}\nYour referral has not been counted.",
                reply_markup=user_menu(),
            )
            await state.clear()
            return
        except SubmissionRateLimitError as exc:
            await session.rollback()
            await message.answer(str(exc))
            return
        referrer_result = await session.get(type(referral), referral.id)
        await session.refresh(referrer_result, attribute_names=["referrer"])
        referrer = referrer_result.referrer
        referred = user
        verification_id = verification.id
        referrer_name = f"@{referrer.username}" if referrer.username else str(referrer.telegram_id)
        flags = ", ".join(verification.suspicious_flags or []) or "none"
    await state.clear()
    await message.answer(
        "Screenshot received. It is awaiting admin review and your referral has not been counted yet.",
        reply_markup=user_menu(),
    )

    for admin_id in settings.admin_ids:
        try:
            caption = (
                "Verification Requires Review\n\n"
                f"User: @{referred.username}" if referred.username else "Verification Requires Review\n\nUser: (no username)"
            )
            caption += (
                f"\nTelegram ID: {referred.telegram_id}"
                f"\nReferrer: {referrer_name}"
                f"\nVerification ID: {verification_id}"
                f"\nFlags: {flags}"
            )
            keyboard = review_keyboard(verification_id)
            if file_kind == "PHOTO":
                await message.bot.send_photo(
                    admin_id,
                    photo=telegram_file_id,
                    caption=caption[:1024],
                    reply_markup=keyboard,
                )
            else:
                await message.bot.send_document(
                    admin_id,
                    document=telegram_file_id,
                    caption=caption[:1024],
                    reply_markup=keyboard,
                )
        except Exception:
            logger.exception(
                "Unable to notify admin for verification_id=%s admin_id=%s",
                verification_id,
                admin_id,
            )
