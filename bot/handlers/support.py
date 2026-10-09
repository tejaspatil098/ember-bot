from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from bot.keyboards.support import reply_to_admin_keyboard, reply_to_user_keyboard
from bot.states.support import SupportStates
from config import get_settings
from utils.security import is_admin

router = Router(name="support")
logger = logging.getLogger("referral_bot.support")


def _display_name(user: User) -> str:
    name = html.escape(user.full_name or "Telegram user")
    if user.username:
        return f"{name} (@{html.escape(user.username)})"
    return name


def _authorized_admin(telegram_id: int | None) -> bool:
    return is_admin(telegram_id, get_settings().admin_ids)


@router.message(Command("support"))
@router.message(F.text == "Contact Admin")
async def start_user_support(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    await state.clear()
    await state.set_state(SupportStates.waiting_for_user_message)
    await message.answer(
        "Contact Admin\n\n"
        "Send your message and it will be delivered to the competition admin team. "
        "You can send text, photos, or files. Use /cancel to stop."
    )


@router.message(Command("owner"))
@router.message(F.text == "Contact Bot Owner")
async def start_owner_contact(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    if not _authorized_admin(message.from_user.id):
        await message.answer("This command is restricted to competition admins.")
        return

    settings = get_settings()
    if settings.bot_owner_telegram_id is None:
        await message.answer(
            "Bot owner contact is not configured yet. Set BOT_OWNER_TELEGRAM_ID "
            "to the owner's numeric Telegram ID."
        )
        return

    await state.clear()
    await state.set_state(SupportStates.waiting_for_owner_message)
    await message.answer(
        "Contact Bot Owner\n\n"
        "Send a message for the bot owner. You can send text, photos, or files. "
        "Use /cancel to stop."
    )


@router.message(Command("cancel"))
async def cancel_support(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("The current message was cancelled.")


@router.message(SupportStates.waiting_for_user_message)
async def deliver_user_message_to_admins(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        await state.clear()
        return
    if message.text and message.text.startswith("/"):
        await message.answer("Send your support message, or use /cancel to stop.")
        return

    settings = get_settings()
    sender = message.from_user
    metadata = (
        "New support message\n"
        f"From: {_display_name(sender)}\n"
        f"Telegram ID: <code>{sender.id}</code>"
    )
    delivered = 0
    for admin_id in settings.admin_ids:
        try:
            await message.bot.send_message(
                admin_id,
                metadata,
                reply_markup=reply_to_user_keyboard(sender.id),
            )
            try:
                await message.bot.copy_message(
                    chat_id=admin_id,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                )
            except Exception:
                logger.exception(
                    "Unable to copy support message user_id=%s admin_id=%s",
                    sender.id,
                    admin_id,
                )
                await message.bot.send_message(
                    admin_id,
                    "The message content could not be copied. Ask the user to resend it.",
                )
                continue
            delivered += 1
        except Exception:
            logger.exception(
                "Unable to deliver support message user_id=%s admin_id=%s",
                sender.id,
                admin_id,
            )

    await state.clear()
    if delivered:
        await message.answer("Your message was sent to the competition admin team.")
    else:
        await message.answer(
            "The admin team could not be reached right now. Please try again later."
        )


@router.callback_query(F.data.startswith("support:reply:"))
async def start_admin_reply(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not _authorized_admin(callback.from_user.id):
        await callback.answer("This reply option is for admins only.", show_alert=True)
        return
    try:
        recipient_id = int((callback.data or "").rsplit(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("This reply button is invalid or expired.", show_alert=True)
        return

    await state.clear()
    await state.set_state(SupportStates.waiting_for_admin_reply)
    await state.update_data(recipient_telegram_id=recipient_id)
    await callback.bot.send_message(
        callback.from_user.id,
        f"Send your reply to Telegram user {recipient_id}. Use /cancel to stop.",
    )
    await callback.answer()


@router.message(SupportStates.waiting_for_admin_reply)
async def deliver_admin_reply(message: Message, state: FSMContext) -> None:
    if not message.from_user or not _authorized_admin(message.from_user.id):
        await state.clear()
        return
    if message.text and message.text.startswith("/"):
        await message.answer("Send your reply, or use /cancel to stop.")
        return

    data = await state.get_data()
    recipient_id = data.get("recipient_telegram_id")
    if not isinstance(recipient_id, int):
        await state.clear()
        await message.answer("That support reply has expired. Open the reply button again.")
        return
    try:
        await message.bot.send_message(recipient_id, "Reply from the competition admin team:")
        await message.bot.copy_message(
            chat_id=recipient_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
    except Exception:
        logger.exception(
            "Unable to deliver admin reply admin_id=%s user_id=%s",
            message.from_user.id,
            recipient_id,
        )
        await state.clear()
        await message.answer(
            "The reply could not be delivered. The user may need to start the bot first."
        )
        return

    await state.clear()
    await message.answer("Your reply was sent to the user.")


@router.message(SupportStates.waiting_for_owner_message)
async def deliver_admin_message_to_owner(message: Message, state: FSMContext) -> None:
    if not message.from_user or not _authorized_admin(message.from_user.id):
        await state.clear()
        return
    if message.text and message.text.startswith("/"):
        await message.answer("Send your message to the owner, or use /cancel to stop.")
        return

    settings = get_settings()
    owner_id = settings.bot_owner_telegram_id
    if owner_id is None:
        await state.clear()
        await message.answer("Bot owner contact is not configured yet.")
        return

    admin = message.from_user
    try:
        await message.bot.send_message(
            owner_id,
            "New message from a competition admin\n"
            f"From: {_display_name(admin)}\n"
            f"Telegram ID: <code>{admin.id}</code>",
            reply_markup=reply_to_admin_keyboard(admin.id),
        )
        await message.bot.copy_message(
            chat_id=owner_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
    except Exception:
        logger.exception("Unable to deliver admin message admin_id=%s", admin.id)
        await state.clear()
        await message.answer(
            "The message could not be delivered. Check that the owner has started the bot."
        )
        return

    await state.clear()
    await message.answer("Your message was sent to the bot owner.")


@router.callback_query(F.data.startswith("owner:reply:"))
async def start_owner_reply(callback: CallbackQuery, state: FSMContext) -> None:
    settings = get_settings()
    if (
        not callback.from_user
        or settings.bot_owner_telegram_id is None
        or callback.from_user.id != settings.bot_owner_telegram_id
    ):
        await callback.answer("Only the bot owner can use this reply option.", show_alert=True)
        return
    try:
        admin_id = int((callback.data or "").rsplit(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("This reply button is invalid or expired.", show_alert=True)
        return

    await state.clear()
    await state.set_state(SupportStates.waiting_for_owner_reply)
    await state.update_data(admin_telegram_id=admin_id)
    await callback.bot.send_message(
        callback.from_user.id,
        f"Send your reply to admin {admin_id}. Use /cancel to stop.",
    )
    await callback.answer()


@router.message(SupportStates.waiting_for_owner_reply)
async def deliver_owner_reply(message: Message, state: FSMContext) -> None:
    settings = get_settings()
    if (
        not message.from_user
        or settings.bot_owner_telegram_id is None
        or message.from_user.id != settings.bot_owner_telegram_id
    ):
        await state.clear()
        return
    if message.text and message.text.startswith("/"):
        await message.answer("Send your reply, or use /cancel to stop.")
        return

    data = await state.get_data()
    admin_id = data.get("admin_telegram_id")
    if not isinstance(admin_id, int) or not _authorized_admin(admin_id):
        await state.clear()
        await message.answer("That admin reply has expired or is no longer available.")
        return
    try:
        await message.bot.send_message(admin_id, "Reply from the bot owner:")
        await message.bot.copy_message(
            chat_id=admin_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
    except Exception:
        logger.exception(
            "Unable to deliver owner reply owner_id=%s admin_id=%s",
            message.from_user.id,
            admin_id,
        )
        await state.clear()
        await message.answer(
            "The reply could not be delivered. The admin may need to start the bot first."
        )
        return

    await state.clear()
    await message.answer("Your reply was sent to the admin.")
