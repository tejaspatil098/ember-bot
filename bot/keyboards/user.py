from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def user_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Come.apk Link")],
            [KeyboardButton(text="My Referral Link")],
            [KeyboardButton(text="My Referrals"), KeyboardButton(text="Leaderboard")],
            [KeyboardButton(text="Submit Verification"), KeyboardButton(text="How It Works")],
            [KeyboardButton(text="Contact Admin")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Choose an option",
    )


def come_link_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Open Come.apk", url=url)]]
    )
