from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

from database.models import Referral, User, Verification
from services.referral_service import register_user
from services.screenshot_service import (
    ScreenshotValidationError,
    analyze_screenshot,
    calculate_sha256,
    perceptual_hash_distance,
)
from services.verification_service import (
    DuplicateScreenshotError,
    review_verification,
    submit_verification,
)


def make_test_image(color: str = "white") -> bytes:
    image = Image.new("RGB", (720, 480), color=color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((25, 25, 695, 455), outline="black", width=3)
    draw.text((50, 60), "Come registration completed", fill="black")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_sha256_duplicate_detection_and_manual_submission(session_factory):
    data = make_test_image()
    analysis = analyze_screenshot(data, max_size_bytes=2_000_000)
    assert calculate_sha256(data) == analysis.sha256
    assert len(analysis.sha256) == 64

    async with session_factory() as session:
        referrer = await register_user(
            session, telegram_id=501, username="ref", first_name="Ref", start_code=None
        )
        referred = await register_user(
            session,
            telegram_id=502,
            username="person",
            first_name="Person",
            start_code=referrer.user.referral_code,
        )
        relationship = (
            await session.execute(
                __import__("sqlalchemy").select(Referral).where(
                    Referral.referred_user_id == referred.user.id
                )
            )
        ).scalar_one()
        item = await submit_verification(
            session,
            user=referred.user,
            referral=relationship,
            telegram_file_id="telegram-file-one",
            file_kind="DOCUMENT",
            analysis=analysis,
        )
        assert item.status == "MANUAL_REVIEW"
        assert relationship.status == "PENDING"
        with pytest.raises(DuplicateScreenshotError):
            await submit_verification(
                session,
                user=referred.user,
                referral=relationship,
                telegram_file_id="telegram-file-two",
                file_kind="DOCUMENT",
                analysis=analysis,
            )
        await session.commit()


def test_image_validation_rejects_blank_or_small_files():
    image = Image.new("RGB", (800, 600), color="white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    with pytest.raises(ScreenshotValidationError, match="blank"):
        analyze_screenshot(output.getvalue(), max_size_bytes=2_000_000)
    with pytest.raises(ScreenshotValidationError, match="size limit"):
        analyze_screenshot(make_test_image(), max_size_bytes=10)


def test_perceptual_hash_distance():
    image_one = analyze_screenshot(make_test_image(), max_size_bytes=2_000_000)
    image_two = analyze_screenshot(make_test_image(), max_size_bytes=2_000_000)
    assert perceptual_hash_distance(image_one.perceptual_hash, image_two.perceptual_hash) == 0


@pytest.mark.asyncio
async def test_approval_counts_referral_only_once(session_factory):
    async with session_factory() as session:
        referrer = await register_user(
            session, telegram_id=601, username="sponsor", first_name="Sponsor", start_code=None
        )
        referred = await register_user(
            session,
            telegram_id=602,
            username="new",
            first_name="New",
            start_code=referrer.user.referral_code,
        )
        relationship = (
            await session.execute(
                __import__("sqlalchemy").select(Referral).where(
                    Referral.referred_user_id == referred.user.id
                )
            )
        ).scalar_one()
        verification = Verification(
            referral_id=relationship.id,
            telegram_user_id=referred.user.telegram_id,
            telegram_file_id="reviewable",
            file_kind="DOCUMENT",
            file_hash="a" * 64,
            perceptual_hash="1" * 16,
            status="MANUAL_REVIEW",
            suspicious_flags=[],
        )
        session.add(verification)
        await session.flush()

        first = await review_verification(
            session,
            verification_id=verification.id,
            admin_id=1001,
            approve=True,
            external_user_id="COME-123",
        )
        await session.commit()
        assert first == ("APPROVED", referred.user.telegram_id)
        assert relationship.status == "VERIFIED"
        assert verification.status == "APPROVED"

        second = await review_verification(
            session,
            verification_id=verification.id,
            admin_id=1001,
            approve=True,
        )
        await session.commit()
        assert second[0] == "ALREADY_REVIEWED"
