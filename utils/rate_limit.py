from __future__ import annotations

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from utils.security import allow_rate_limited_action


class UserRateLimitMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user
        else:
            user = None
        if user and not allow_rate_limited_action(user.id):
            if isinstance(event, CallbackQuery):
                await event.answer("Please slow down and try again shortly.", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("Please slow down and try again shortly.")
            return None
        return await handler(event, data)
