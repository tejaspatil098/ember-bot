from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def admin_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Admin Statistics"), KeyboardButton(text="Pending Verification")],
            [KeyboardButton(text="Admin Leaderboard"), KeyboardButton(text="Competition Settings")],
            [KeyboardButton(text="Export CSV"), KeyboardButton(text="Admin Help")],
            [KeyboardButton(text="Contact Bot Owner")],
        ],
        resize_keyboard=True,
    )


def review_keyboard(verification_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Approve",
                    callback_data=f"review:approve:{verification_id}",
                ),
                InlineKeyboardButton(
                    text="Reject",
                    callback_data=f"review:reject:{verification_id}",
                ),
            ]
        ]
    )
