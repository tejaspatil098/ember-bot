from __future__ import annotations

import os

# Unit tests use a private in-memory SQLite database and never call Telegram.
os.environ["BOT_TOKEN"] = "123456:test-token"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["COME_REFERRAL_LINK"] = "https://example.com/authorized-referral"
os.environ["ADMIN_TELEGRAM_IDS"] = "1001"
os.environ["PRIZE_AMOUNT"] = "2500"
os.environ["COMPETITION_START"] = ""
os.environ["COMPETITION_END"] = ""

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.database import Base
from database import models  # noqa: F401


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()
