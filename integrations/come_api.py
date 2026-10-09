"""Come.apk verification boundary.

No official API contract or authorized export was supplied. The production
default therefore remains manual review; this module deliberately does not
guess endpoints or attempt scraping.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ComeAPI(Protocol):
    async def get_user(self, identifier: str) -> dict | None: ...

    async def verify_user(self, identifier: str) -> bool: ...

    async def verify_referral(self, referrer: str, referred_user: str) -> bool: ...


@dataclass
class ManualVerificationMode:
    async def get_user(self, identifier: str) -> dict | None:
        return None

    async def verify_user(self, identifier: str) -> bool:
        raise RuntimeError("No authorized Come.apk verification API is configured.")

    async def verify_referral(self, referrer: str, referred_user: str) -> bool:
        raise RuntimeError("Use admin review until an authorized Come.apk referral feed is available.")


@dataclass
class MockComeAPI:
    """Development-only fixture adapter; it never approves unknown accounts."""

    fixtures: dict[str, dict]

    async def get_user(self, identifier: str) -> dict | None:
        return self.fixtures.get(identifier)

    async def verify_user(self, identifier: str) -> bool:
        user = self.fixtures.get(identifier)
        return bool(user and user.get("verified") is True)

    async def verify_referral(self, referrer: str, referred_user: str) -> bool:
        user = self.fixtures.get(referred_user)
        return bool(
            user
            and user.get("verified") is True
            and user.get("referred_by") == referrer
        )


class AuthorizedComeAPI:
    """Extension point for an API contract supplied and authorized by the owner."""

    def __init__(self, base_url: str, api_key: str, api_secret: str | None = None):
        if not base_url.startswith("https://") or not api_key:
            raise ValueError("An HTTPS API base URL and API key are required.")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret

    async def get_user(self, identifier: str) -> dict | None:
        raise NotImplementedError(
            "The provider's official endpoint and response contract must be supplied before enabling live verification."
        )

    async def verify_user(self, identifier: str) -> bool:
        raise NotImplementedError(
            "The provider's official endpoint and response contract must be supplied before enabling live verification."
        )

    async def verify_referral(self, referrer: str, referred_user: str) -> bool:
        raise NotImplementedError(
            "The provider's official endpoint and response contract must be supplied before enabling live verification."
        )


def get_come_api() -> ComeAPI:
    return ManualVerificationMode()
