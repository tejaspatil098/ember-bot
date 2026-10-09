from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Message,
)
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from bot.keyboards.admin import admin_menu, review_keyboard
from bot.keyboards.user import user_menu
from config import get_settings
from database.models import Competition, Referral, User, Verification
from database.database import async_session_factory
from services.competition_service import (
    calculate_rankings,
    ensure_competition,
    record_audit,
    set_competition_status,
    update_competition_setting,
)
from services.leaderboard_service import get_leaderboard
from services.referral_service import count_all_referrals, count_referrals_by_status
from services.verification_service import (
    delete_user_verification_data,
    find_verification,
    list_pending_verifications,
    reject_referral,
    review_verification,
)
from utils.security import is_admin
from utils.validators import parse_admin_datetime, parse_admin_prize

router = Router(name="admin")
logger = logging.getLogger("referral_bot.admin")


def authorized(telegram_id: int | None) -> bool:
    return is_admin(telegram_id, get_settings().admin_ids)


async def admin_denied(message: Message) -> None:
    await message.answer("This command is restricted to competition admins.")


async def pending_as_messages(message: Message) -> None:
    if not message.from_user or not authorized(message.from_user.id):
        await admin_denied(message)
        return
    async with async_session_factory() as session:
        pending = await list_pending_verifications(session)
        await session.commit()
    if not pending:
        await message.answer("There are no screenshots waiting for review.")
        return
    for verification, referred_user, referrer, referral in pending:
        if not verification.telegram_file_id:
            continue
        username = f"@{referred_user.username}" if referred_user.username else "(no username)"
        referrer_name = f"@{referrer.username}" if referrer.username else str(referrer.telegram_id)
        flags = ", ".join(verification.suspicious_flags or []) or "none"
        caption = (
            "Verification Requires Review\n\n"
            f"User: {username}\n"
            f"Telegram ID: {referred_user.telegram_id}\n"
            f"Referrer: {referrer_name}\n"
            f"Verification ID: {verification.id}\n"
            f"Flags: {flags}"
        )
        try:
            keyboard = review_keyboard(verification.id)
            if verification.file_kind == "PHOTO":
                await message.bot.send_photo(
                    message.chat.id,
                    photo=verification.telegram_file_id,
                    caption=caption,
                    reply_markup=keyboard,
                )
            else:
                await message.bot.send_document(
                    message.chat.id,
                    document=verification.telegram_file_id,
                    caption=caption,
                    reply_markup=keyboard,
                )
        except Exception:
            logger.exception("Unable to send verification_id=%s to admin", verification.id)
            await message.answer(
                f"Could not retrieve screenshot #{verification.id}; inspect the submission in Telegram."
            )


async def send_admin_stats(message: Message) -> None:
    if not message.from_user or not authorized(message.from_user.id):
        await admin_denied(message)
        return
    async with async_session_factory() as session:
        total_users = int((await session.execute(select(func.count(User.id)))).scalar_one())
        total_referrals = await count_all_referrals(session)
        pending = await count_referrals_by_status(session, "PENDING")
        verified = await count_referrals_by_status(session, "VERIFIED")
        rejected = await count_referrals_by_status(session, "REJECTED")
        cancelled = await count_referrals_by_status(session, "CANCELLED")
        competition = await ensure_competition(session)
        leaders = await get_leaderboard(session, 1)
        await session.commit()
    leader_name = (
        f"@{leaders[0][0].username}"
        if leaders and leaders[0][0].username
        else "No public username"
    )
    leader_count = leaders[0][1] if leaders else 0
    await message.answer(
        "COMPETITION STATISTICS\n\n"
        f"Total Telegram users: {total_users}\n"
        f"Total referral relationships: {total_referrals}\n"
        f"Pending referrals: {pending}\n"
        f"Verified referrals: {verified}\n"
        f"Rejected referrals: {rejected}\n"
        f"Cancelled referrals: {cancelled}\n\n"
        f"Current leader: {leader_name}\n"
        f"Verified referrals: {leader_count}\n"
        f"Prize: ₹{competition.prize_amount:,.0f}\n"
        f"Status: {competition.status.title()}",
        reply_markup=admin_menu(),
    )


async def send_admin_leaderboard(message: Message) -> None:
    if not message.from_user or not authorized(message.from_user.id):
        await admin_denied(message)
        return
    async with async_session_factory() as session:
        entries = await get_leaderboard(session, 20)
        await session.commit()
    if not entries:
        await message.answer("No verified referrals yet.")
        return
    lines = ["LEADERBOARD"]
    for index, (user, count, _) in enumerate(entries, 1):
        name = f"@{user.username}" if user.username else f"Telegram user {user.telegram_id}"
        lines.append(f"{index}. {name} — {count}")
    await message.answer("\n".join(lines))


@router.message(Command("admin"))
async def admin_command(message: Message) -> None:
    if not message.from_user or not authorized(message.from_user.id):
        await admin_denied(message)
        return
    await message.answer(
        "Admin controls\n\n"
        "/stats — competition statistics\n"
        "/leaderboard — leaderboard\n"
        "/pending — review screenshots\n"
        "/users — latest users\n"
        "/search &lt;id|username|referral code|Come user ID&gt;\n"
        "/export — download CSV\n"
        "/approve &lt;verification_id&gt; [Come user ID]\n"
        "/reject &lt;verification_id&gt; [reason]\n"
        "/reject_referral &lt;Telegram user ID&gt; &lt;reason&gt;\n"
        "/delete_verification &lt;Telegram user ID&gt;\n"
        "/owner — contact the bot owner (admins only)\n"
        "/set_name &lt;name&gt;\n/set_prize &lt;amount&gt;\n"
        "/set_start &lt;ISO datetime&gt;\n/set_end &lt;ISO datetime&gt;\n"
        "/lock_competition\n/end_competition",
        reply_markup=admin_menu(),
    )


@router.message(Command("stats"))
@router.message(F.text == "Admin Statistics")
async def stats_command(message: Message) -> None:
    await send_admin_stats(message)


@router.message(Command("pending"))
@router.message(F.text == "Pending Verification")
async def pending_command(message: Message) -> None:
    await pending_as_messages(message)


@router.message(Command("adminleaderboard"))
@router.message(F.text == "Admin Leaderboard")
async def admin_leaderboard(message: Message) -> None:
    await send_admin_leaderboard(message)


@router.message(Command("users"))
async def users_command(message: Message) -> None:
    if not message.from_user or not authorized(message.from_user.id):
        await admin_denied(message)
        return
    async with async_session_factory() as session:
        users = (
            await session.execute(
                select(User).order_by(User.created_at.desc()).limit(25)
            )
        ).scalars().all()
        await session.commit()
    if not users:
        await message.answer("No users have registered yet.")
        return
    lines = ["LATEST USERS"]
    for user in users:
        name = f"@{user.username}" if user.username else "(no username)"
        lines.append(f"{name} — ID {user.telegram_id} — code {user.referral_code}")
    await message.answer("\n".join(lines))


@router.message(Command("search"))
async def search_user(message: Message) -> None:
    if not message.from_user or not authorized(message.from_user.id):
        await admin_denied(message)
        return
    query = (message.text or "").partition(" ")[2].strip()
    if not query:
        await message.answer("Usage: /search <Telegram ID, username, referral code, or Come.apk user ID>")
        return
    cleaned = query.lstrip("@").strip()
    async with async_session_factory() as session:
        user = None
        if cleaned.isdecimal():
            user = (
                await session.execute(
                    select(User).where(User.telegram_id == int(cleaned))
                )
            ).scalar_one_or_none()
        if not user:
            user = (
                await session.execute(
                    select(User).where(
                        (func.lower(User.username) == cleaned.lower())
                        | (func.upper(User.referral_code) == cleaned.upper())
                    )
                )
            ).scalar_one_or_none()
        if not user:
            user = (
                await session.execute(
                    select(User)
                    .join(Verification, Verification.telegram_user_id == User.telegram_id)
                    .where(Verification.external_user_id == cleaned)
                )
            ).scalar_one_or_none()
        if not user:
            await session.commit()
            await message.answer("No matching user was found.")
            return
        counts = {}
        for status in ("PENDING", "VERIFIED", "REJECTED", "CANCELLED"):
            counts[status] = int(
                (
                    await session.execute(
                        select(func.count(Referral.id)).where(
                            Referral.referrer_id == user.id,
                            Referral.status == status,
                        )
                    )
                ).scalar_one()
            )
        incoming = (
            await session.execute(
                select(User)
                .join(Referral, Referral.referrer_id == User.id)
                .where(Referral.referred_user_id == user.id)
            )
        ).scalar_one_or_none()
        external_ids = (
            await session.execute(
                select(Verification.external_user_id).where(
                    Verification.telegram_user_id == user.telegram_id,
                    Verification.external_user_id.is_not(None),
                )
            )
        ).scalars().all()
        await session.commit()
    referrer_text = (
        f"@{incoming.username}" if incoming and incoming.username
        else str(incoming.telegram_id) if incoming
        else "None"
    )
    await message.answer(
        "USER DETAILS\n\n"
        f"Username: @{user.username}" if user.username else "USER DETAILS\n\nUsername: (none)"
    )
    await message.answer(
        f"Telegram ID: {user.telegram_id}\n"
        f"Referral code: {user.referral_code}\n"
        f"Referred by: {referrer_text}\n"
        f"Total referrals sent: {sum(counts.values())}\n"
        f"Verified: {counts['VERIFIED']}\n"
        f"Pending: {counts['PENDING']}\n"
        f"Rejected: {counts['REJECTED']}\n"
        f"Come.apk IDs on file: {', '.join(external_ids) if external_ids else 'None'}"
    )


@router.message(Command("export"))
@router.message(F.text == "Export CSV")
async def export_csv(message: Message) -> None:
    if not message.from_user or not authorized(message.from_user.id):
        await admin_denied(message)
        return
    async with async_session_factory() as session:
        users = (await session.execute(select(User).order_by(User.created_at))).scalars().all()
        sent_rows = (
            await session.execute(
                select(Referral.referrer_id, Referral.status, func.count(Referral.id))
                .group_by(Referral.referrer_id, Referral.status)
            )
        ).all()
        incoming_rows = (
            await session.execute(
                select(Referral.referred_user_id, User.telegram_id, User.username)
                .join(User, User.id == Referral.referrer_id)
            )
        ).all()
        await session.commit()
    counts: dict[int, dict[str, int]] = {}
    for user_id, status, count in sent_rows:
        counts.setdefault(user_id, {})[status] = int(count)
    referrer_map: dict[int, str] = {}
    for referred_user_id, telegram_id, username in incoming_rows:
        referrer_map[referred_user_id] = f"@{username}" if username else str(telegram_id)

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "telegram_id",
            "username",
            "referral_code",
            "referrer",
            "total_referrals",
            "verified_referrals",
            "pending_referrals",
            "rejected_referrals",
            "created_at",
        ]
    )
    for user in users:
        by_status = counts.get(user.id, {})
        writer.writerow(
            [
                user.telegram_id,
                user.username or "",
                user.referral_code,
                referrer_map.get(user.id, ""),
                sum(by_status.values()),
                by_status.get("VERIFIED", 0),
                by_status.get("PENDING", 0),
                by_status.get("REJECTED", 0),
                user.created_at.isoformat() if user.created_at else "",
            ]
        )
    csv_bytes = output.getvalue().encode("utf-8-sig")
    await message.answer_document(
        BufferedInputFile(csv_bytes, filename="referral-competition-users.csv"),
        caption="Competition user export. Verification images and secrets are not included.",
    )


@router.message(Command("approve"))
async def approve_command(message: Message) -> None:
    if not message.from_user or not authorized(message.from_user.id):
        await admin_denied(message)
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Usage: /approve <verification_id> [Come.apk user ID]")
        return
    await _perform_review(
        message=message,
        verification_id=int(parts[1]),
        admin_id=message.from_user.id,
        approve=True,
        external_user_id=parts[2].strip() if len(parts) > 2 else None,
    )


@router.message(Command("reject"))
async def reject_command(message: Message) -> None:
    if not message.from_user or not authorized(message.from_user.id):
        await admin_denied(message)
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Usage: /reject <verification_id> [reason]")
        return
    reason = parts[2] if len(parts) > 2 else "The screenshot did not meet the competition requirements."
    await _perform_review(
        message=message,
        verification_id=int(parts[1]),
        admin_id=message.from_user.id,
        approve=False,
        reason=reason,
    )


async def _perform_review(
    *,
    message: Message,
    verification_id: int,
    admin_id: int,
    approve: bool,
    reason: str | None = None,
    external_user_id: str | None = None,
) -> None:
    async with async_session_factory() as session:
        result, telegram_user_id = await review_verification(
            session,
            verification_id=verification_id,
            admin_id=admin_id,
            approve=approve,
            reason=reason,
            external_user_id=external_user_id,
        )
        await session.commit()
    messages = {
        "APPROVED": "Approved. The referral was counted exactly once.",
        "REJECTED": "Rejected. The referral remains pending so the participant can submit corrected evidence.",
        "NOT_FOUND": "Verification not found.",
        "ALREADY_REVIEWED": "This verification has already been reviewed.",
        "REFERRAL_NOT_FOUND": "The referral relationship could not be found.",
        "COMPETITION_ENDED": "The competition has ended; this verification cannot be approved.",
        "ALREADY_COUNTED": "This referred participant has already been counted.",
        "REFERRAL_NOT_ELIGIBLE": "This referral is no longer eligible.",
        "DUPLICATE_EXTERNAL_ACCOUNT": "That Come.apk account ID is already attached to another approved submission; this one remains for review.",
    }
    await message.answer(messages.get(result, f"Review result: {result}"))
    if telegram_user_id and result in {"APPROVED", "REJECTED"}:
        try:
            if result == "APPROVED":
                await message.bot.send_message(
                    telegram_user_id,
                    "Verification Successful!\n\nYour submission was approved. The participant who invited you has received +1 verified referral. Thank you for participating.",
                    reply_markup=user_menu(),
                )
            else:
                await message.bot.send_message(
                    telegram_user_id,
                    f"Verification Failed\n\nReason: {reason or 'The screenshot did not meet the competition requirements.'}\n\nYour referral has not been counted. You can submit a corrected screenshot.",
                    reply_markup=user_menu(),
                )
        except Exception:
            logger.info("Could not deliver review notification telegram_user_id=%s", telegram_user_id)


@router.callback_query(F.data.startswith("review:"))
async def review_callback(callback: CallbackQuery) -> None:
    if not callback.from_user or not authorized(callback.from_user.id):
        await callback.answer("Admin access required.", show_alert=True)
        return
    try:
        _, decision, raw_id = (callback.data or "").split(":")
        verification_id = int(raw_id)
    except (ValueError, TypeError):
        await callback.answer("Invalid review action.", show_alert=True)
        return
    if decision not in {"approve", "reject"}:
        await callback.answer("Invalid review action.", show_alert=True)
        return
    result, telegram_user_id = "UNKNOWN", None
    async with async_session_factory() as session:
        result, telegram_user_id = await review_verification(
            session,
            verification_id=verification_id,
            admin_id=callback.from_user.id,
            approve=decision == "approve",
            reason="Rejected by competition admin.",
        )
        await session.commit()
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    await callback.answer(
        "Approved." if result == "APPROVED" else "Rejected." if result == "REJECTED" else result.replace("_", " ").title(),
        show_alert=True,
    )
    if telegram_user_id and result in {"APPROVED", "REJECTED"}:
        try:
            if result == "APPROVED":
                await callback.bot.send_message(
                    telegram_user_id,
                    "Verification Successful! Your referral was approved and counted.",
                    reply_markup=user_menu(),
                )
            else:
                await callback.bot.send_message(
                    telegram_user_id,
                    "Verification Failed. Your screenshot was rejected and the referral was not counted. You may submit a corrected screenshot.",
                    reply_markup=user_menu(),
                )
        except Exception:
            logger.info("Could not deliver review notification telegram_user_id=%s", telegram_user_id)


@router.message(Command("reject_referral"))
async def reject_referral_command(message: Message) -> None:
    if not message.from_user or not authorized(message.from_user.id):
        await admin_denied(message)
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        await message.answer("Usage: /reject_referral <referred Telegram ID> <reason>")
        return
    async with async_session_factory() as session:
        found = await reject_referral(
            session,
            referred_telegram_id=int(parts[1]),
            admin_id=message.from_user.id,
            reason=parts[2],
        )
        await session.commit()
    await message.answer("Referral rejected." if found else "No referral was found for that Telegram user.")


@router.message(Command("delete_verification"))
async def delete_verification_command(message: Message) -> None:
    if not message.from_user or not authorized(message.from_user.id):
        await admin_denied(message)
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /delete_verification <Telegram user ID>")
        return
    async with async_session_factory() as session:
        deleted = await delete_user_verification_data(
            session,
            telegram_user_id=int(parts[1]),
            admin_id=message.from_user.id,
        )
        await session.commit()
    await message.answer(f"Deleted {deleted} stored verification record(s). Referral counts were not changed.")


@router.message(Command("set_name"))
async def set_name(message: Message) -> None:
    await _set_competition_value(message, "name")


@router.message(Command("set_prize"))
async def set_prize(message: Message) -> None:
    await _set_competition_value(message, "prize_amount")


@router.message(Command("set_start"))
async def set_start(message: Message) -> None:
    await _set_competition_value(message, "start_time")


@router.message(Command("set_end"))
async def set_end(message: Message) -> None:
    await _set_competition_value(message, "end_time")


async def _set_competition_value(message: Message, field: str) -> None:
    if not message.from_user or not authorized(message.from_user.id):
        await admin_denied(message)
        return
    raw = (message.text or "").partition(" ")[2].strip()
    if not raw:
        usage = {
            "name": "/set_name <competition name>",
            "prize_amount": "/set_prize <amount in INR>",
            "start_time": "/set_start <ISO datetime, e.g. 2026-11-01T18:30:00+05:30>",
            "end_time": "/set_end <ISO datetime, e.g. 2026-11-30T23:59:00+05:30>",
        }
        await message.answer(f"Usage: {usage[field]}")
        return
    try:
        if field == "name":
            value = raw[:160]
        elif field == "prize_amount":
            value = parse_admin_prize(raw)
        else:
            value = parse_admin_datetime(raw)
        async with async_session_factory() as session:
            await update_competition_setting(
                session,
                admin_id=message.from_user.id,
                field=field,
                value=value,
            )
            await session.commit()
        await message.answer(f"Competition {field.replace('_', ' ')} updated.")
    except (ValueError, OverflowError) as exc:
        await message.answer(f"Setting was not changed: {exc}")


@router.message(Command("competition"))
@router.message(F.text == "Competition Settings")
async def competition_settings(message: Message) -> None:
    if not message.from_user or not authorized(message.from_user.id):
        await admin_denied(message)
        return
    async with async_session_factory() as session:
        competition = await ensure_competition(session)
        await session.commit()
    await message.answer(
        "COMPETITION SETTINGS\n\n"
        f"Name: {competition.name}\n"
        f"Prize: ₹{competition.prize_amount:,.0f}\n"
        f"Start: {competition.start_time.isoformat() if competition.start_time else 'Not set'}\n"
        f"End: {competition.end_time.isoformat() if competition.end_time else 'Not set'}\n"
        f"Status: {competition.status}\n"
        f"Winner Telegram user ID: {competition.winner_user_id or 'Not selected'}\n\n"
        "Use /set_name, /set_prize, /set_start, /set_end, /lock_competition, /end_competition."
    )


@router.message(Command("lock_competition"))
async def lock_competition(message: Message) -> None:
    await _change_competition_status(message, "LOCKED")


@router.message(Command("end_competition"))
async def end_competition(message: Message) -> None:
    await _change_competition_status(message, "ENDED")


async def _change_competition_status(message: Message, status: str) -> None:
    if not message.from_user or not authorized(message.from_user.id):
        await admin_denied(message)
        return
    async with async_session_factory() as session:
        competition = await set_competition_status(session, status)
        await record_audit(
            session,
            admin_id=message.from_user.id,
            action=f"COMPETITION_{status}",
            target_user_id=competition.winner_user_id,
        )
        await session.commit()
        winner_result = await session.execute(
            select(User).where(User.id == competition.winner_user_id)
        ) if competition.winner_user_id else None
        winner = winner_result.scalar_one_or_none() if winner_result else None
    if status == "ENDED":
        winner_name = (
            f"@{winner.username}" if winner and winner.username else "Participant"
        )
        winner_count = 0
        if winner:
            async with async_session_factory() as session:
                winner_count = int(
                    (
                        await session.execute(
                            select(func.count(Referral.id)).where(
                                Referral.referrer_id == winner.id,
                                Referral.status == "VERIFIED",
                            )
                        )
                    ).scalar_one()
                )
        await message.answer(
            "Competition ended.\n\n"
            f"Winner: {winner_name}\n"
            f"Verified referrals: {winner_count}\n"
            f"Prize: ₹{competition.prize_amount:,.0f}\n\n"
            "Payment is handled manually by the competition owner. Unresolved referrals at closing were cancelled and excluded."
        )
        if winner:
            try:
                await message.bot.send_message(
                    winner.telegram_id,
                    f"Competition Winner\n\nCongratulations! You finished with {winner_count} verified referrals.\n\nPrize: ₹{competition.prize_amount:,.0f}\nPayment will be handled manually by the competition owner.",
                )
            except Exception:
                logger.info("Could not deliver winner message telegram_user_id=%s", winner.telegram_id)
    else:
        await message.answer("Competition locked. New referral relationships will not be accepted.")


@router.message(F.text == "Admin Help")
async def admin_help(message: Message) -> None:
    await admin_command(message)


@router.message(F.text == "Admin Leaderboard")
async def admin_leaderboard_button(message: Message) -> None:
    await send_admin_leaderboard(message)


@router.message(F.text == "Admin Statistics")
async def admin_stats_button(message: Message) -> None:
    await send_admin_stats(message)


@router.message(F.text == "Pending Verification")
async def pending_button(message: Message) -> None:
    await pending_as_messages(message)


@router.message(F.text == "Export CSV")
async def export_button(message: Message) -> None:
    await export_csv(message)


@router.message(F.text == "Competition Settings")
async def settings_button(message: Message) -> None:
    await competition_settings(message)

