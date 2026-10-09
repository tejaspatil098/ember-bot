from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base


class User(Base):
    __tablename__ = "competition_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), index=True)
    first_name: Mapped[str] = mapped_column(String(128), default="")
    referral_code: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    referrals_sent: Mapped[list["Referral"]] = relationship(
        back_populates="referrer", foreign_keys="Referral.referrer_id"
    )


class Referral(Base):
    __tablename__ = "competition_referrals"
    __table_args__ = (
        UniqueConstraint("referred_user_id", name="uq_competition_referral_referred_user"),
        Index("ix_competition_referrals_referrer_status", "referrer_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    referrer_id: Mapped[int] = mapped_column(ForeignKey("competition_users.id", ondelete="RESTRICT"))
    referred_user_id: Mapped[int] = mapped_column(
        ForeignKey("competition_users.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    referrer: Mapped[User] = relationship(foreign_keys=[referrer_id], back_populates="referrals_sent")
    referred_user: Mapped[User] = relationship(foreign_keys=[referred_user_id])
    verifications: Mapped[list["Verification"]] = relationship(
        back_populates="referral", cascade="all, delete-orphan"
    )


class Verification(Base):
    __tablename__ = "competition_verifications"
    __table_args__ = (
        Index("ix_competition_verifications_user_created", "telegram_user_id", "created_at"),
        Index("ix_competition_verifications_external_user", "external_user_id"),
        Index("ix_competition_verifications_phash", "perceptual_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    referral_id: Mapped[int] = mapped_column(
        ForeignKey("competition_referrals.id", ondelete="CASCADE"), index=True
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    external_user_id: Mapped[str | None] = mapped_column(String(128))
    telegram_file_id: Mapped[str | None] = mapped_column(Text)
    file_kind: Mapped[str] = mapped_column(String(16), default="DOCUMENT")
    file_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    perceptual_hash: Mapped[str | None] = mapped_column(String(64))
    ocr_result: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="MANUAL_REVIEW", index=True)
    suspicious_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger)

    referral: Mapped[Referral] = relationship(back_populates="verifications")


class Competition(Base):
    __tablename__ = "competition_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prize_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("2500.00"))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)
    winner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("competition_users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuditLog(Base):
    __tablename__ = "competition_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
