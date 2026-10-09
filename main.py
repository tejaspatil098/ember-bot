from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent, Update
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import text

from bot.handlers import (
    admin_router,
    leaderboard_router,
    referral_router,
    start_router,
    support_router,
    verification_router,
)
from config import get_settings
from database.database import async_session_factory, engine
from integrations.come_webhook import (
    MAX_WEBHOOK_BODY_BYTES,
    ComeWebhookEvent,
    verify_webhook_signature,
)
from services.competition_service import ensure_competition
from services.verification_service import approve_referral_from_webhook
from utils.logger import configure_logging
from utils.rate_limit import UserRateLimitMiddleware

configure_logging()
logger = logging.getLogger("referral_bot")
settings = get_settings()
bot = Bot(
    token=settings.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dispatcher = Dispatcher(storage=MemoryStorage())
for handler_router in (
    start_router,
    support_router,
    referral_router,
    leaderboard_router,
    verification_router,
    admin_router,
):
    dispatcher.include_router(handler_router)

rate_limiter = UserRateLimitMiddleware()
dispatcher.message.middleware(rate_limiter)
dispatcher.callback_query.middleware(rate_limiter)


@dispatcher.errors()
async def handle_update_error(event: ErrorEvent) -> bool:
    exception = event.exception
    logger.error(
        "Unhandled Telegram update error update_id=%s",
        event.update.update_id,
        exc_info=(type(exception), exception, exception.__traceback__),
    )
    return True


async def set_bot_commands() -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Register or open the competition menu"),
            BotCommand(command="link", description="Get your personal Telegram invitation link"),
            BotCommand(command="myreferrals", description="View your referral counts"),
            BotCommand(command="leaderboard", description="View verified referral rankings"),
            BotCommand(command="rank", description="View your rank"),
            BotCommand(command="verify", description="Submit a verification screenshot"),
            BotCommand(command="come", description="Get the shared Come.apk link"),
            BotCommand(command="how", description="How the competition works"),
            BotCommand(command="support", description="Contact the competition admins"),
            BotCommand(command="admin", description="Admin controls"),
        ]
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with async_session_factory() as session:
        competition = await ensure_competition(session)
        await session.commit()
    logger.info(
        "COMPETITION_STARTED status=%s name=%s",
        competition.status,
        competition.name,
    )

    await set_bot_commands()
    polling_task = asyncio.create_task(
        dispatcher.start_polling(bot, handle_signals=False),
        name="telegram-polling",
    )
    app.state.polling_task = polling_task
    try:
        yield
    finally:
        await dispatcher.stop_polling()
        if not polling_task.done():
            polling_task.cancel()
        with suppress(asyncio.CancelledError):
            await polling_task
        await bot.session.close()
        await engine.dispose()


app = FastAPI(
    title="Telegram Referral Competition Bot",
    description="Health endpoint for the Telegram referral competition bot.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/healthz", tags=["health"])
async def healthz() -> dict[str, str]:
    polling_task = getattr(app.state, "polling_task", None)
    if polling_task and polling_task.done():
        if polling_task.cancelled() or polling_task.exception():
            raise HTTPException(status_code=503, detail="Telegram polling is not running.")
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:
        logger.exception("Database health check failed")
        raise HTTPException(status_code=503, detail="Database is unavailable.") from exc
    return {"status": "ok", "bot": "polling"}


@app.post("/webhooks/come", tags=["integrations"])
async def receive_come_webhook(
    request: Request,
    x_come_timestamp: str | None = Header(default=None),
    x_come_signature: str | None = Header(default=None),
) -> dict[str, str]:
    """Receive a signed registration event from Come.apk or an authorized relay."""
    if not settings.come_webhook_secret or not settings.come_webhook_campaign_id:
        raise HTTPException(status_code=503, detail="Come.apk webhook verification is not configured.")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="Content-Type must be application/json.")

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_WEBHOOK_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Webhook body is too large.")
        body.extend(chunk)
    raw_body = bytes(body)

    if not verify_webhook_signature(
        body=raw_body,
        timestamp=x_come_timestamp,
        signature=x_come_signature,
        secret=settings.come_webhook_secret,
    ):
        raise HTTPException(status_code=401, detail="Invalid or expired webhook signature.")

    try:
        event = ComeWebhookEvent.model_validate_json(raw_body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid Come.apk webhook event.") from exc
    if event.campaign_id != settings.come_webhook_campaign_id:
        raise HTTPException(status_code=403, detail="Webhook campaign does not match this bot.")

    async with async_session_factory() as session:
        result, telegram_user_id = await approve_referral_from_webhook(
            session,
            event_id=event.event_id,
            campaign_id=event.campaign_id,
            telegram_user_id=event.telegram_user_id,
            come_user_id=event.come_user_id,
        )
        if result in {"APPROVED", "DUPLICATE_EXTERNAL_ACCOUNT"}:
            await session.commit()
        else:
            await session.rollback()

    if result == "APPROVED" and telegram_user_id is not None:
        try:
            await bot.send_message(
                telegram_user_id,
                "Come.apk registration verified. Your referral has been approved and counted.",
            )
        except Exception:
            logger.exception(
                "Unable to notify Telegram user after Come.apk webhook approval telegram_user_id=%s",
                telegram_user_id,
            )
        return {"status": "approved", "event_id": event.event_id}
    if result == "ALREADY_VERIFIED":
        return {"status": "already_processed", "event_id": event.event_id}
    if result == "DUPLICATE_EXTERNAL_ACCOUNT":
        raise HTTPException(status_code=409, detail="Come.apk account was already used.")
    if result == "USER_NOT_FOUND":
        raise HTTPException(status_code=404, detail="Telegram participant was not found.")
    if result == "REFERRAL_NOT_FOUND":
        raise HTTPException(status_code=404, detail="Participant has no tracked referral.")
    if result == "COMPETITION_ENDED":
        raise HTTPException(status_code=409, detail="The competition has ended.")
    raise HTTPException(status_code=409, detail="Participant referral is not eligible.")


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"service": "Telegram Referral Competition Bot", "health": "/healthz"}


async def run() -> None:
    import uvicorn

    port = int(__import__("os").environ.get("PORT", "8000"))
    await uvicorn.Server(
        uvicorn.Config(app, host="0.0.0.0", port=port, log_level=settings.log_level.lower())
    ).serve()


if __name__ == "__main__":
    asyncio.run(run())
