from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import ErrorEvent, Update

from bot.handlers import admin as admin_handlers
from bot.handlers import support as support_handlers
from bot.keyboards.admin import admin_menu
from bot.keyboards.support import reply_to_admin_keyboard, reply_to_user_keyboard
from bot.keyboards.user import user_menu
from config import Settings
from main import handle_update_error


def test_requested_admin_ids_are_always_admins():
    settings = Settings(
        bot_token="test-token",
        database_url="sqlite+aiosqlite:///:memory:",
        come_referral_link="https://example.com/referral",
        admin_telegram_ids="1001",
    )

    assert settings.admin_ids == {6944760306, 8308849911, 1831302205, 1001}


def test_owner_telegram_id_can_be_left_unconfigured_or_set():
    base_settings = {
        "bot_token": "test-token",
        "database_url": "sqlite+aiosqlite:///:memory:",
        "come_referral_link": "https://example.com/referral",
    }

    assert Settings(**base_settings, bot_owner_telegram_id="").bot_owner_telegram_id is None
    assert Settings(**base_settings, bot_owner_telegram_id="123456789").bot_owner_telegram_id == 123456789


def test_support_actions_are_available_only_in_their_intended_menus():
    user_labels = [
        button.text
        for row in user_menu().keyboard
        for button in row
    ]
    admin_labels = [
        button.text
        for row in admin_menu().keyboard
        for button in row
    ]

    assert "Contact Admin" in user_labels
    assert "My Referral Link" in user_labels
    assert "Contact Bot Owner" in admin_labels
    assert "Contact Bot Owner" not in user_labels


def test_support_reply_buttons_encode_their_target_user():
    user_reply = reply_to_user_keyboard(987654321)
    owner_reply = reply_to_admin_keyboard(123456789)

    assert user_reply.inline_keyboard[0][0].callback_data == "support:reply:987654321"
    assert owner_reply.inline_keyboard[0][0].callback_data == "owner:reply:123456789"


@pytest.mark.asyncio
async def test_admin_help_escapes_placeholder_brackets(monkeypatch):
    settings = Settings(
        bot_token="test-token",
        database_url="sqlite+aiosqlite:///:memory:",
        come_referral_link="https://example.com/referral",
    )
    monkeypatch.setattr(admin_handlers, "get_settings", lambda: settings)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=8308849911),
        answer=AsyncMock(),
    )

    await admin_handlers.admin_command(message)

    help_text = message.answer.await_args.args[0]
    assert "&lt;id|username|referral code|Come user ID&gt;" in help_text
    assert "<id|" not in help_text
    assert "<verification_id>" not in help_text


@pytest.mark.asyncio
async def test_dispatcher_error_handler_accepts_aiogram_error_event():
    event = ErrorEvent(update=Update(update_id=123), exception=ValueError("test error"))

    assert await handle_update_error(event) is True


@pytest.mark.asyncio
async def test_non_admin_cannot_start_owner_contact(monkeypatch):
    settings = Settings(
        bot_token="test-token",
        database_url="sqlite+aiosqlite:///:memory:",
        come_referral_link="https://example.com/referral",
        bot_owner_telegram_id=9001,
    )
    monkeypatch.setattr(support_handlers, "get_settings", lambda: settings)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=7001),
        answer=AsyncMock(),
    )
    state = AsyncMock()

    await support_handlers.start_owner_contact(message, state)

    message.answer.assert_awaited_once_with(
        "This command is restricted to competition admins."
    )
    state.clear.assert_not_awaited()
    state.set_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_can_start_owner_contact(monkeypatch):
    settings = Settings(
        bot_token="test-token",
        database_url="sqlite+aiosqlite:///:memory:",
        come_referral_link="https://example.com/referral",
        bot_owner_telegram_id=9001,
    )
    monkeypatch.setattr(support_handlers, "get_settings", lambda: settings)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=8308849911),
        answer=AsyncMock(),
    )
    state = AsyncMock()

    await support_handlers.start_owner_contact(message, state)

    state.clear.assert_awaited_once()
    state.set_state.assert_awaited_once_with(
        support_handlers.SupportStates.waiting_for_owner_message
    )
    message.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_user_support_message_is_sent_to_all_admins(monkeypatch):
    settings = Settings(
        bot_token="test-token",
        database_url="sqlite+aiosqlite:///:memory:",
        come_referral_link="https://example.com/referral",
        admin_telegram_ids="1001",
    )
    monkeypatch.setattr(support_handlers, "get_settings", lambda: settings)
    bot = SimpleNamespace(
        send_message=AsyncMock(),
        copy_message=AsyncMock(),
    )
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=7001, full_name="Test User", username="tester"),
        text="Support message",
        bot=bot,
        chat=SimpleNamespace(id=7001),
        message_id=22,
        answer=AsyncMock(),
    )
    state = AsyncMock()

    await support_handlers.deliver_user_message_to_admins(message, state)

    recipients = {call.args[0] for call in bot.send_message.await_args_list}
    copied_to = {call.kwargs["chat_id"] for call in bot.copy_message.await_args_list}
    assert recipients == settings.admin_ids
    assert copied_to == settings.admin_ids
    assert "Your message was sent" in message.answer.await_args.args[0]
    state.clear.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_admin_cannot_deliver_a_message_to_owner(monkeypatch):
    settings = Settings(
        bot_token="test-token",
        database_url="sqlite+aiosqlite:///:memory:",
        come_referral_link="https://example.com/referral",
        bot_owner_telegram_id=9001,
    )
    monkeypatch.setattr(support_handlers, "get_settings", lambda: settings)
    bot = SimpleNamespace(
        send_message=AsyncMock(),
        copy_message=AsyncMock(),
    )
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=7001),
        text="Not an admin",
        bot=bot,
        chat=SimpleNamespace(id=7001),
        message_id=22,
        answer=AsyncMock(),
    )
    state = AsyncMock()

    await support_handlers.deliver_admin_message_to_owner(message, state)

    state.clear.assert_awaited_once()
    bot.send_message.assert_not_awaited()
    bot.copy_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_only_configured_owner_can_use_owner_reply_button(monkeypatch):
    settings = Settings(
        bot_token="test-token",
        database_url="sqlite+aiosqlite:///:memory:",
        come_referral_link="https://example.com/referral",
        bot_owner_telegram_id=9001,
    )
    monkeypatch.setattr(support_handlers, "get_settings", lambda: settings)
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=7001),
        data="owner:reply:8308849911",
        answer=AsyncMock(),
        bot=SimpleNamespace(send_message=AsyncMock()),
    )
    state = AsyncMock()

    await support_handlers.start_owner_reply(callback, state)

    callback.answer.assert_awaited_once_with(
        "Only the bot owner can use this reply option.",
        show_alert=True,
    )
    state.clear.assert_not_awaited()
    state.set_state.assert_not_awaited()
