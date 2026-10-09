from __future__ import annotations

import re
import secrets
import string
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

REFERRAL_ALPHABET = string.ascii_uppercase + string.digits
_events: dict[int, deque[datetime]] = defaultdict(deque)


def generate_referral_code(length: int = 8) -> str:
    return "".join(secrets.choice(REFERRAL_ALPHABET) for _ in range(length))


def normalize_referral_code(value: str) -> str | None:
    normalized = value.strip().upper()
    return normalized if re.fullmatch(r"[A-Z0-9]{6,12}", normalized) else None


def is_admin(telegram_id: int | None, admin_ids: set[int]) -> bool:
    return telegram_id is not None and telegram_id in admin_ids


def allow_rate_limited_action(
    telegram_id: int,
    *,
    limit: int = 20,
    window_seconds: int = 60,
    now: datetime | None = None,
) -> bool:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=window_seconds)
    events = _events[telegram_id]
    while events and events[0] < cutoff:
        events.popleft()
    if len(events) >= limit:
        return False
    events.append(now)
    return True
