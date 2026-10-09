from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def reply_to_user_keyboard(telegram_user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Reply to user",
                    callback_data=f"support:reply:{telegram_user_id}",
                )
            ]
        ]
    )


def reply_to_admin_keyboard(admin_telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Reply to admin",
                    callback_data=f"owner:reply:{admin_telegram_id}",
                )
            ]
        ]
    )
