"""Create referral competition tables.

Revision ID: 0001_initial
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "competition_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("referral_code", sa.String(length=12), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_competition_users_telegram_id", "competition_users", ["telegram_id"])
    op.create_index("ix_competition_users_username", "competition_users", ["username"])
    op.create_index("ix_competition_users_referral_code", "competition_users", ["referral_code"])

    op.create_table(
        "competition_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prize_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "winner_user_id",
            sa.Integer(),
            sa.ForeignKey("competition_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_competition_settings_status", "competition_settings", ["status"])

    op.create_table(
        "competition_referrals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "referrer_id",
            sa.Integer(),
            sa.ForeignKey("competition_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "referred_user_id",
            sa.Integer(),
            sa.ForeignKey("competition_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("referred_user_id", name="uq_competition_referral_referred_user"),
    )
    op.create_index("ix_competition_referrals_referrer_id", "competition_referrals", ["referrer_id"])
    op.create_index("ix_competition_referrals_referred_user_id", "competition_referrals", ["referred_user_id"])
    op.create_index("ix_competition_referrals_status", "competition_referrals", ["status"])
    op.create_index(
        "ix_competition_referrals_referrer_status",
        "competition_referrals",
        ["referrer_id", "status"],
    )

    op.create_table(
        "competition_verifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "referral_id",
            sa.Integer(),
            sa.ForeignKey("competition_referrals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("external_user_id", sa.String(length=128), nullable=True),
        sa.Column("telegram_file_id", sa.Text(), nullable=True),
        sa.Column("file_kind", sa.String(length=16), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=True, unique=True),
        sa.Column("perceptual_hash", sa.String(length=64), nullable=True),
        sa.Column("ocr_result", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("suspicious_flags", sa.JSON(), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_competition_verifications_referral_id", "competition_verifications", ["referral_id"])
    op.create_index("ix_competition_verifications_telegram_user_id", "competition_verifications", ["telegram_user_id"])
    op.create_index("ix_competition_verifications_status", "competition_verifications", ["status"])
    op.create_index("ix_competition_verifications_external_user", "competition_verifications", ["external_user_id"])
    op.create_index("ix_competition_verifications_phash", "competition_verifications", ["perceptual_hash"])
    op.create_index(
        "ix_competition_verifications_user_created",
        "competition_verifications",
        ["telegram_user_id", "created_at"],
    )

    op.create_table(
        "competition_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_user_id", sa.BigInteger(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_competition_audit_logs_admin_id", "competition_audit_logs", ["admin_id"])
    op.create_index("ix_competition_audit_logs_action", "competition_audit_logs", ["action"])
    op.create_index("ix_competition_audit_logs_target_user_id", "competition_audit_logs", ["target_user_id"])


def downgrade() -> None:
    op.drop_table("competition_audit_logs")
    op.drop_table("competition_verifications")
    op.drop_table("competition_referrals")
    op.drop_table("competition_settings")
    op.drop_table("competition_users")
