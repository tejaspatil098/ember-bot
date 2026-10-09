from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from database.models import Competition, Referral, User, Verification
from services.competition_service import (
    record_audit,
    refresh_competition_state,
    utcnow,
)
from services.screenshot_service import ScreenshotAnalysis, perceptual_hash_distance

logger = logging.getLogger("referral_bot.verification")

MAX_SUBMISSIONS_PER_HOUR = 10
SUSPICIOUS_SUBMISSIONS_PER_HOUR = 3
SIMILAR_IMAGE_DISTANCE = 5


class DuplicateScreenshotError(ValueError):
    pass


class SubmissionRateLimitError(ValueError):
    pass


async def submit_verification(
    session: AsyncSession,
    *,
    user: User,
    referral: Referral,
    telegram_file_id: str,
    file_kind: str,
    analysis: ScreenshotAnalysis,
) -> Verification:
    duplicate = await session.execute(
        select(Verification.id).where(Verification.file_hash == analysis.sha256)
    )
    if duplicate.scalar_one_or_none() is not None:
        logger.warning("SCREENSHOT_DUPLICATE telegram_user_id=%s", user.telegram_id)
        await record_audit(
            session,
            admin_id=None,
            action="SCREENSHOT_DUPLICATE",
            target_user_id=user.telegram_id,
        )
        raise DuplicateScreenshotError("This screenshot has already been submitted.")

    now = utcnow()
    recent_result = await session.execute(
        select(func.count(Verification.id)).where(
            Verification.telegram_user_id == user.telegram_id,
            Verification.created_at >= now - timedelta(hours=1),
        )
    )
    recent_count = int(recent_result.scalar_one())
    if recent_count >= MAX_SUBMISSIONS_PER_HOUR:
        raise SubmissionRateLimitError("Too many screenshots were submitted recently. Please try later.")

    prior_hashes = await session.execute(
        select(Verification.perceptual_hash).where(
            Verification.perceptual_hash.is_not(None)
        )
    )
    flags = list(analysis.flags)
    for previous_hash in prior_hashes.scalars().all():
        if perceptual_hash_distance(analysis.perceptual_hash, previous_hash) <= SIMILAR_IMAGE_DISTANCE:
            flags.append("VISUALLY_SIMILAR_TO_PRIOR_SUBMISSION")
            break
    if recent_count >= SUSPICIOUS_SUBMISSIONS_PER_HOUR:
        flags.append("HIGH_SUBMISSION_VELOCITY")

    verification = Verification(
        referral_id=referral.id,
        telegram_user_id=user.telegram_id,
        telegram_file_id=telegram_file_id,
        file_kind=file_kind,
        file_hash=analysis.sha256,
        perceptual_hash=analysis.perceptual_hash,
        ocr_result=analysis.ocr_text,
        status="MANUAL_REVIEW",
        suspicious_flags=flags,
        created_at=now,
    )
    session.add(verification)
    await record_audit(
        session,
        admin_id=None,
        action="SCREENSHOT_RECEIVED",
        target_user_id=user.telegram_id,
        details={"verification_id": "pending-insert", "flag_count": len(flags)},
    )
    await session.flush()
    logger.info(
        "SCREENSHOT_RECEIVED telegram_user_id=%s verification_id=%s flags=%s",
        user.telegram_id,
        verification.id,
        len(flags),
    )
    return verification


async def list_pending_verifications(
    session: AsyncSession,
) -> list[tuple[Verification, User, User, Referral]]:
    referred_user = aliased(User)
    referrer = aliased(User)
    result = await session.execute(
        select(Verification, referred_user, referrer, Referral)
        .join(referred_user, referred_user.telegram_id == Verification.telegram_user_id)
        .join(Referral, Referral.id == Verification.referral_id)
        .join(referrer, referrer.id == Referral.referrer_id)
        .where(Verification.status.in_(["PENDING", "MANUAL_REVIEW"]))
        .order_by(Verification.created_at.asc())
        .limit(50)
    )
    return list(result.all())


async def review_verification(
    session: AsyncSession,
    *,
    verification_id: int,
    admin_id: int,
    approve: bool,
    reason: str | None = None,
    external_user_id: str | None = None,
) -> tuple[str, int | None]:
    result = await session.execute(
        select(Verification).where(Verification.id == verification_id).with_for_update()
    )
    verification = result.scalar_one_or_none()
    if verification is None:
        return "NOT_FOUND", None
    if verification.status not in {"PENDING", "MANUAL_REVIEW"}:
        return "ALREADY_REVIEWED", verification.telegram_user_id

    referral_result = await session.execute(
        select(Referral).where(Referral.id == verification.referral_id).with_for_update()
    )
    referral = referral_result.scalar_one_or_none()
    if not referral:
        return "REFERRAL_NOT_FOUND", verification.telegram_user_id

    if not approve:
        verification.status = "REJECTED"
        verification.rejection_reason = (reason or "The submitted screenshot did not pass admin review.")[:1000]
        verification.reviewed_by = admin_id
        await record_audit(
            session,
            admin_id=admin_id,
            action="ADMIN_REJECTION",
            target_user_id=verification.telegram_user_id,
            details={"verification_id": verification.id, "reason": verification.rejection_reason},
        )
        logger.info(
            "VERIFICATION_REJECTED admin_id=%s verification_id=%s",
            admin_id,
            verification.id,
        )
        await session.flush()
        return "REJECTED", verification.telegram_user_id

    competition = await refresh_competition_state(session)
    if competition.status == "ENDED":
        verification.status = "CANCELLED"
        verification.rejection_reason = "The competition ended before this verification was approved."
        verification.reviewed_by = admin_id
        await session.flush()
        return "COMPETITION_ENDED", verification.telegram_user_id
    if referral.status == "VERIFIED":
        verification.status = "REJECTED"
        verification.rejection_reason = "This referral has already been counted."
        verification.reviewed_by = admin_id
        await session.flush()
        return "ALREADY_COUNTED", verification.telegram_user_id
    if referral.status != "PENDING":
        verification.status = "REJECTED"
        verification.rejection_reason = "The referral is no longer eligible."
        verification.reviewed_by = admin_id
        await session.flush()
        return "REFERRAL_NOT_ELIGIBLE", verification.telegram_user_id

    if external_user_id:
        existing_external = await session.execute(
            select(Verification.id).where(
                Verification.external_user_id == external_user_id,
                Verification.id != verification.id,
                Verification.status == "APPROVED",
            )
        )
        if existing_external.scalar_one_or_none() is not None:
            verification.suspicious_flags = [
                *(verification.suspicious_flags or []),
                "EXTERNAL_ACCOUNT_ALREADY_USED",
            ]
            await record_audit(
                session,
                admin_id=admin_id,
                action="DUPLICATE_EXTERNAL_ACCOUNT_FLAGGED",
                target_user_id=verification.telegram_user_id,
                details={"verification_id": verification.id},
            )
            await session.flush()
            return "DUPLICATE_EXTERNAL_ACCOUNT", verification.telegram_user_id
        verification.external_user_id = external_user_id[:128]

    now = utcnow()
    verification.status = "APPROVED"
    verification.reviewed_by = admin_id
    verification.verified_at = now
    referral.status = "VERIFIED"
    referral.verified_at = now
    await record_audit(
        session,
        admin_id=admin_id,
        action="ADMIN_APPROVAL",
        target_user_id=verification.telegram_user_id,
        details={"verification_id": verification.id},
    )
    logger.info(
        "VERIFICATION_APPROVED admin_id=%s verification_id=%s",
        admin_id,
        verification.id,
    )
    await session.flush()
    return "APPROVED", verification.telegram_user_id


async def approve_referral_from_webhook(
    session: AsyncSession,
    *,
    event_id: str,
    campaign_id: str,
    telegram_user_id: int,
    come_user_id: str,
) -> tuple[str, int | None]:
    """Count a referred participant only after a signed provider event."""
    user_result = await session.execute(
        select(User).where(User.telegram_id == telegram_user_id)
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        return "USER_NOT_FOUND", None

    referral_result = await session.execute(
        select(Referral)
        .where(Referral.referred_user_id == user.id)
        .with_for_update()
    )
    referral = referral_result.scalar_one_or_none()
    if referral is None:
        return "REFERRAL_NOT_FOUND", telegram_user_id
    if referral.status == "VERIFIED":
        return "ALREADY_VERIFIED", telegram_user_id
    if referral.status != "PENDING":
        return "REFERRAL_NOT_ELIGIBLE", telegram_user_id

    competition = await refresh_competition_state(session)
    if competition.status == "ENDED":
        return "COMPETITION_ENDED", telegram_user_id

    duplicate_result = await session.execute(
        select(Verification.id).where(
            Verification.external_user_id == come_user_id,
            Verification.status == "APPROVED",
        )
    )
    if duplicate_result.scalar_one_or_none() is not None:
        await record_audit(
            session,
            admin_id=None,
            action="COME_WEBHOOK_DUPLICATE_ACCOUNT",
            target_user_id=telegram_user_id,
            details={"event_id": event_id, "campaign_id": campaign_id},
        )
        await session.flush()
        return "DUPLICATE_EXTERNAL_ACCOUNT", telegram_user_id

    pending_result = await session.execute(
        select(Verification)
        .where(
            Verification.referral_id == referral.id,
            Verification.status.in_(["PENDING", "MANUAL_REVIEW"]),
        )
        .order_by(Verification.created_at.desc())
        .with_for_update()
    )
    verification = pending_result.scalars().first()
    now = utcnow()
    if verification is None:
        verification = Verification(
            referral_id=referral.id,
            telegram_user_id=telegram_user_id,
            file_kind="WEBHOOK",
            status="APPROVED",
            suspicious_flags=[],
            created_at=now,
        )
        session.add(verification)
    verification.external_user_id = come_user_id
    verification.status = "APPROVED"
    verification.reviewed_by = None
    verification.verified_at = now
    referral.status = "VERIFIED"
    referral.verified_at = now
    await session.flush()

    await record_audit(
        session,
        admin_id=None,
        action="COME_WEBHOOK_APPROVAL",
        target_user_id=telegram_user_id,
        details={
            "event_id": event_id,
            "campaign_id": campaign_id,
            "come_user_id": come_user_id,
            "verification_id": verification.id,
        },
    )
    await session.flush()
    logger.info(
        "COME_WEBHOOK_APPROVAL telegram_user_id=%s event_id=%s",
        telegram_user_id,
        event_id,
    )
    return "APPROVED", telegram_user_id


async def reject_referral(
    session: AsyncSession,
    *,
    referred_telegram_id: int,
    admin_id: int,
    reason: str,
) -> bool:
    user_result = await session.execute(
        select(User).where(User.telegram_id == referred_telegram_id)
    )
    user = user_result.scalar_one_or_none()
    if not user:
        return False
    referral_result = await session.execute(
        select(Referral).where(Referral.referred_user_id == user.id).with_for_update()
    )
    referral = referral_result.scalar_one_or_none()
    if not referral:
        return False
    referral.status = "REJECTED"
    related = await session.execute(
        select(Verification).where(
            Verification.referral_id == referral.id,
            Verification.status.in_(["PENDING", "MANUAL_REVIEW"]),
        )
    )
    for verification in related.scalars().all():
        verification.status = "REJECTED"
        verification.reviewed_by = admin_id
        verification.rejection_reason = reason[:1000]
    await record_audit(
        session,
        admin_id=admin_id,
        action="REFERRAL_REJECTED",
        target_user_id=referred_telegram_id,
        details={"reason": reason[:1000]},
    )
    await session.flush()
    return True


async def delete_user_verification_data(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    admin_id: int,
) -> int:
    result = await session.execute(
        delete(Verification).where(Verification.telegram_user_id == telegram_user_id)
    )
    deleted = int(result.rowcount or 0)
    await record_audit(
        session,
        admin_id=admin_id,
        action="VERIFICATION_DATA_DELETED",
        target_user_id=telegram_user_id,
        details={"deleted_verification_records": deleted},
    )
    await session.flush()
    return deleted


async def find_verification(session: AsyncSession, verification_id: int):
    result = await session.execute(
        select(Verification, User, Referral)
        .join(User, User.telegram_id == Verification.telegram_user_id)
        .join(Referral, Referral.id == Verification.referral_id)
        .where(Verification.id == verification_id)
    )
    return result.one_or_none()
