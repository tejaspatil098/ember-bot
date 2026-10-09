"""Signed webhook contract for an authorized Come.apk event source or relay.

This is the bot's own contract. It is not an assertion that Come.apk directly
supports these headers or payload fields.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_WEBHOOK_BODY_BYTES = 32 * 1024
WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS = 300


class ComeWebhookEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    event_id: str = Field(min_length=1, max_length=128)
    event_type: Literal["registration.verified"]
    campaign_id: str = Field(min_length=1, max_length=128)
    telegram_user_id: int = Field(strict=True, gt=0)
    come_user_id: str = Field(min_length=1, max_length=128)

    @field_validator("telegram_user_id", mode="before")
    @classmethod
    def reject_boolean_telegram_ids(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("telegram_user_id must be a numeric Telegram user ID.")
        return value


def verify_webhook_signature(
    *,
    body: bytes,
    timestamp: str | None,
    signature: str | None,
    secret: str,
    now: int | None = None,
) -> bool:
    """Validate a timestamped HMAC-SHA256 signature over the raw request body."""
    if not timestamp or not timestamp.isascii() or not timestamp.isdigit():
        return False
    if not signature or len(signature) != 64:
        return False
    try:
        timestamp_value = int(timestamp)
        int(signature, 16)
    except ValueError:
        return False

    current_time = int(time.time()) if now is None else now
    if abs(current_time - timestamp_value) > WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS:
        return False

    signed_payload = timestamp.encode("ascii") + b"." + body
    expected = hmac.new(
        secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature.lower())
