from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

BUILT_IN_ADMIN_IDS = frozenset({6944760306, 8308849911, 1831302205})


def parse_utc(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    bot_token: str
    database_url: str
    admin_telegram_ids: str = ""
    bot_owner_telegram_id: int | None = None
    come_referral_link: str
    come_api_base_url: str | None = None
    come_api_key: str | None = None
    come_api_secret: str | None = None
    come_webhook_campaign_id: str | None = "4c7fad75-0d3b-4c22-92d4-5ec77aa6ecaa"
    come_webhook_secret: str | None = None
    redis_url: str | None = None
    prize_amount: int = 2500
    competition_name: str = "Come Referral Competition"
    competition_start: datetime | None = None
    competition_end: datetime | None = None
    max_screenshot_size_mb: int = 10
    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        value = value.strip()
        url = make_url(value)
        if url.drivername == "postgres":
            url = url.set(drivername="postgresql")
        if url.drivername == "postgresql":
            url = url.set(drivername="postgresql+asyncpg")
        if url.drivername == "postgresql+asyncpg":
            # Replit/libpq-style URLs may include parameters accepted by psycopg
            # but not by asyncpg. Translate the TLS mode and discard the
            # libpq-only channel-binding flag.
            query = dict(url.query)
            sslmode = query.pop("sslmode", None)
            query.pop("channel_binding", None)
            if sslmode:
                query.setdefault("ssl", sslmode)
            url = url.set(query=query)
        return url.render_as_string(hide_password=False)

    @field_validator("come_referral_link")
    @classmethod
    def validate_come_referral_link(cls, value: str) -> str:
        value = value.strip()
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("COME_REFERRAL_LINK must be a valid HTTPS URL.")
        return value

    @field_validator("admin_telegram_ids")
    @classmethod
    def validate_admin_ids(cls, value: str) -> str:
        if value.strip():
            try:
                [int(item.strip()) for item in value.split(",") if item.strip()]
            except ValueError as exc:
                raise ValueError("ADMIN_TELEGRAM_IDS must be comma-separated numeric Telegram IDs.") from exc
        return value

    @field_validator("bot_owner_telegram_id", mode="before")
    @classmethod
    def validate_bot_owner_telegram_id(cls, value: Any) -> int | None:
        if value is None or not str(value).strip():
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("BOT_OWNER_TELEGRAM_ID must be a numeric Telegram ID.") from exc
        if parsed <= 0:
            raise ValueError("BOT_OWNER_TELEGRAM_ID must be a positive Telegram ID.")
        return parsed

    @field_validator("competition_start", "competition_end", mode="before")
    @classmethod
    def parse_competition_dates(cls, value: Any) -> datetime | None:
        return parse_utc(value)

    @field_validator("prize_amount")
    @classmethod
    def validate_prize(cls, value: int) -> int:
        if value < 1:
            raise ValueError("PRIZE_AMOUNT must be greater than zero.")
        return value

    @field_validator("max_screenshot_size_mb")
    @classmethod
    def validate_max_screenshot_size(cls, value: int) -> int:
        if not 1 <= value <= 20:
            raise ValueError("MAX_SCREENSHOT_SIZE_MB must be between 1 and 20.")
        return value

    @model_validator(mode="after")
    def validate_competition_window(self) -> "Settings":
        if self.competition_start and self.competition_end and self.competition_end <= self.competition_start:
            raise ValueError("COMPETITION_END must be later than COMPETITION_START.")
        return self

    @property
    def admin_ids(self) -> set[int]:
        configured_ids = {
            int(value.strip())
            for value in self.admin_telegram_ids.split(",")
            if value.strip()
        }
        return configured_ids | set(BUILT_IN_ADMIN_IDS)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
