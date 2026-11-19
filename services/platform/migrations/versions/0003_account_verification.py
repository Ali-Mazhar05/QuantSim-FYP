"""Email verification, admin approval, emailed account links and the mail outbox.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

PURPOSES = "'verify_email', 'set_password', 'reset_password'"


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("approved_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("approved_by", sa.Uuid()))
    # Accounts that exist already were made by trusted operators: verified and approved
    op.execute("UPDATE users SET email_verified_at = created_at, approved_at = created_at")
    # An invited user has no password until they use their link
    op.alter_column("users", "password_hash", nullable=True)

    op.create_table(
        "account_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(f"purpose IN ({PURPOSES})", name="account_tokens_purpose_valid"),
        sa.CheckConstraint("expires_at > created_at", name="account_tokens_expiry_after_creation"),
    )
    op.create_index(
        "account_tokens_token_hash_unique", "account_tokens", ["token_hash"], unique=True
    )
    op.create_index(
        "account_tokens_unused_by_user",
        "account_tokens",
        ["user_id", "purpose"],
        postgresql_where=sa.text("used_at IS NULL"),
    )

    op.create_table(
        "mail_outbox",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("to_address", sa.Text(), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
    )
    op.create_index(
        "mail_outbox_due",
        "mail_outbox",
        ["next_attempt_at"],
        postgresql_where=sa.text("sent_at IS NULL AND failed_at IS NULL"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    without = bind.execute(sa.text("SELECT count(*) FROM users WHERE password_hash IS NULL"))
    if without.scalar_one():
        raise RuntimeError(
            "Some users have no password yet (invitations not accepted); deactivate or "
            "delete them before downgrading below 0003"
        )
    op.drop_table("mail_outbox")
    op.drop_table("account_tokens")
    op.alter_column("users", "password_hash", nullable=False)
    op.drop_column("users", "approved_by")
    op.drop_column("users", "approved_at")
    op.drop_column("users", "email_verified_at")
