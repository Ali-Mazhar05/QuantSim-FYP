"""Tables of ``platform_db``. The migrations in ``migrations/`` create exactly these."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    Uuid,
    func,
    text,
)

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
    Column("password_hash", Text, nullable=False),
    Column("role", Text, nullable=False),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column("failed_logins", Integer, nullable=False, server_default=text("0")),
    Column("locked_until", DateTime(timezone=True)),
    Column("last_login_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("deactivated_at", DateTime(timezone=True)),
    Column("created_by", Uuid),
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
