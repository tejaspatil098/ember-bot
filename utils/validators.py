from __future__ import annotations

from datetime import datetime, timezone

from config import parse_utc


def parse_admin_datetime(value: str) -> datetime:
    parsed = parse_utc(value)
    if parsed is None:
        raise ValueError("Provide an ISO date/time, for example 2026-11-01T18:30:00+05:30.")
    return parsed.astimezone(timezone.utc)


def parse_admin_prize(value: str) -> int:
    amount = int(value)
    if not 1 <= amount <= 10_000_000:
        raise ValueError("Prize must be a positive amount no greater than 10,000,000.")
    return amount
