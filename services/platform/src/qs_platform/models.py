"""Tables of ``platform_db``. The migrations in ``migrations/`` create exactly these."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from qs_template.auth import Role

metadata = MetaData()

ROLE_VALUES = tuple(role.value for role in Role)

users = Table(
    "users",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("username", Text, nullable=False),
    Column("email", Text, nullable=False),
    Column("display_name", Text, nullable=False),
    # NULL for an invited user until they set a password through their link
    Column("password_hash", Text),
    Column("role", Text, nullable=False),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column("failed_logins", Integer, nullable=False, server_default=text("0")),
    Column("locked_until", DateTime(timezone=True)),
    Column("last_login_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("deactivated_at", DateTime(timezone=True)),
    Column("created_by", Uuid),
    # A self sign-up can sign in only once its email is verified and, for Quant and
    # Analyst, once an admin has approved it
    Column("email_verified_at", DateTime(timezone=True)),
    Column("approved_at", DateTime(timezone=True)),
    Column("approved_by", Uuid),
    # The role set is fixed in the database itself, not only in code (NFR-INT-002)
    CheckConstraint(
        "role IN (" + ", ".join(f"'{r}'" for r in ROLE_VALUES) + ")", name="users_role_valid"
    ),
    CheckConstraint("username ~ '^[a-z0-9._-]{3,40}$'", name="users_username_format"),
    CheckConstraint("failed_logins >= 0", name="users_failed_logins_non_negative"),
    CheckConstraint(
        "(is_active AND deactivated_at IS NULL) OR (NOT is_active AND deactivated_at IS NOT NULL)",
        name="users_deactivation_consistent",
    ),
    # Usernames and emails are unique regardless of letter case
    Index("users_username_unique", func.lower(text("username")), unique=True),
    Index("users_email_unique", func.lower(text("email")), unique=True),
)

# Server-side refresh tokens (FR-15). Only a SHA-256 hash of each token is stored. Every
# refresh replaces the token with a new one in the same family (one family per sign-in);
# presenting a token that was already used revokes the whole family. Not audited: rows
# change on every refresh and hold nothing a reviewer needs beyond the user events.
refresh_tokens = Table(
    "refresh_tokens",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("user_id", Uuid, ForeignKey("users.id"), nullable=False),
    Column("family_id", Uuid, nullable=False),
    Column("token_hash", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
    CheckConstraint("expires_at > created_at", name="refresh_tokens_expiry_after_creation"),
    Index("refresh_tokens_token_hash_unique", "token_hash", unique=True),
    Index("refresh_tokens_family", "family_id"),
    Index("refresh_tokens_active_by_user", "user_id", postgresql_where=text("revoked_at IS NULL")),
)

ACCOUNT_TOKEN_PURPOSES = ("verify_email", "set_password", "reset_password")

# Single-use emailed links (verify email, set password after an invitation, reset
# password). Only a SHA-256 hash of each token is stored; issuing a new token voids the
# unused ones of the same user and purpose. Not audited, like refresh tokens: the user
# changes a token causes are audited on ``users``.
account_tokens = Table(
    "account_tokens",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("purpose", Text, nullable=False),
    Column("token_hash", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True)),
    CheckConstraint(
        "purpose IN (" + ", ".join(f"'{p}'" for p in ACCOUNT_TOKEN_PURPOSES) + ")",
        name="account_tokens_purpose_valid",
    ),
    CheckConstraint("expires_at > created_at", name="account_tokens_expiry_after_creation"),
    Index("account_tokens_token_hash_unique", "token_hash", unique=True),
    Index(
        "account_tokens_unused_by_user",
        "user_id",
        "purpose",
        postgresql_where=text("used_at IS NULL"),
    ),
)

# Account emails waiting to be sent, written in the same transaction as the change that
# causes them (NFR-REL-007) and sent by the relay worker
mail_outbox = Table(
    "mail_outbox",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("to_address", Text, nullable=False),
    Column("template", Text, nullable=False),
    Column("params", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("attempts", Integer, nullable=False, server_default=text("0")),
    Column("next_attempt_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("sent_at", DateTime(timezone=True)),
    Column("failed_at", DateTime(timezone=True)),
    Column("last_error", Text),
    Index(
        "mail_outbox_due",
        "next_attempt_at",
        postgresql_where=text("sent_at IS NULL AND failed_at IS NULL"),
    ),
)
