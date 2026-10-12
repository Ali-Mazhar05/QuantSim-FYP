"""User and session rules of the Platform service (FR-PLT-001..005, FR-PLT-008).

- Sign-in checks the password with Argon2id, locks an account for a while after repeated
  failures, and gives the same answer for unknown users, wrong passwords and deactivated
  accounts, so it never reveals which usernames exist.
- Every change to a user is published as an event through the outbox in the same
  transaction, and recorded in the audit trail by the database.
- Deactivation and role changes revoke the user's existing tokens in every service.
- The last active admin can be neither deactivated nor demoted, so the system can never
  be left without an administrator.
"""

import hashlib
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Row, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from qs_platform.keys import SigningKeys
from qs_platform.models import refresh_tokens, users
from qs_platform.passwords import hash_password, needs_rehash, verify_password
from qs_platform.schemas import (
    AuditEntryOut,
    CreateUserRequest,
    TokenResponse,
    UserList,
    UserOut,
)
from qs_platform.settings import PlatformSettings
from qs_template.audit import record_history
from qs_template.auth import Principal, Role
from qs_template.errors import ServiceError
from qs_template.events import EventEnvelope
from qs_template.logging import get_logger
from qs_template.messaging import add_event
from qs_template.revocation import RevocationList

log = get_logger(__name__)

INVALID_REFRESH = ServiceError(
    401,
    "Session expired",
    "The session is no longer valid. Sign in again.",
    type_="urn:quantsim:problem:invalid-refresh-token",
)

INVALID_CREDENTIALS = ServiceError(
    401,
    "Sign-in failed",
    "The username or password is incorrect.",
    type_="urn:quantsim:problem:invalid-credentials",
)

# Columns safe to show in audit history; password hashes are never logged at all
_HISTORY_COLUMNS = (
    "username",
    "email",
    "display_name",
    "role",
    "is_active",
    "deactivated_at",
    "locked_until",
)


def _not_found(user_id: uuid.UUID) -> ServiceError:
    return ServiceError(
        404, "User not found", f"No user {user_id}.", type_="urn:quantsim:problem:not-found"
    )


@dataclass(frozen=True)
class LoginOutcome:
    """Result of a sign-in attempt; failures are reported only after their bookkeeping
    has been committed."""

    token: TokenResponse | None = None
    locked_seconds: int | None = None


class UserService:
    def __init__(
        self, settings: PlatformSettings, keys: SigningKeys, revocations: RevocationList
    ) -> None:
        self._settings = settings
        self._keys = keys
        self._revocations = revocations

    # Sign-in -------------------------------------------------------------------------

    async def login(self, session: AsyncSession, username: str, password: str) -> LoginOutcome:
        now = datetime.now(UTC)
        row = (
            await session.execute(
                select(users)
                .where(func.lower(users.c.username) == username.strip().lower())
                .with_for_update()
            )
        ).one_or_none()

        if row is not None and row.locked_until is not None and row.locked_until > now:
            # Still spend the hashing time so a locked account looks like any other
            verify_password(None, password)
            return LoginOutcome(locked_seconds=int((row.locked_until - now).total_seconds()) + 1)

        valid = verify_password(row.password_hash if row else None, password)
        if row is None:
            return LoginOutcome()
        if not valid:
            await self._record_failure(session, row, now)
            return LoginOutcome()
        if not row.is_active:
            return LoginOutcome()

        changes: dict[str, Any] = {"failed_logins": 0, "locked_until": None, "last_login_at": now}
        if needs_rehash(row.password_hash):
            changes["password_hash"] = hash_password(password)
        await session.execute(update(users).where(users.c.id == row.id).values(**changes))
        user = await self._get(session, row.id)
        return LoginOutcome(token=await self._issue_tokens(session, user, uuid.uuid4()))

    # Sessions ------------------------------------------------------------------------

    async def refresh(self, session: AsyncSession, token: str) -> TokenResponse | None:
        """A new access and refresh token for a valid refresh token, or None.

        The caller commits before reporting None, so a detected reuse stays revoked.
        """
        now = datetime.now(UTC)
        row = (
            await session.execute(
                select(refresh_tokens)
                .where(refresh_tokens.c.token_hash == _hash_token(token))
                .with_for_update()
            )
        ).one_or_none()
        if row is None or row.revoked_at is not None:
            return None
        if row.used_at is not None:
            # A rotated token came back: someone else holds a copy, end the whole session
            log.warning("refresh token reused; session revoked", user_id=str(row.user_id))
            await self._revoke_family(session, row.family_id)
            return None
        if row.expires_at <= now:
            return None
        user = await self._get(session, row.user_id)
        if not user.is_active:
            await self._revoke_family(session, row.family_id)
            return None
        await session.execute(
            update(refresh_tokens).where(refresh_tokens.c.id == row.id).values(used_at=now)
        )
        return await self._issue_tokens(session, user, row.family_id)

    async def logout(self, session: AsyncSession, token: str) -> None:
        """End the session the refresh token belongs to; unknown tokens are ignored."""
        family = (
            await session.execute(
                select(refresh_tokens.c.family_id).where(
                    refresh_tokens.c.token_hash == _hash_token(token)
                )
            )
        ).scalar_one_or_none()
        if family is not None:
            await self._revoke_family(session, family)

    async def _revoke_family(self, session: AsyncSession, family_id: uuid.UUID) -> None:
        await session.execute(
            update(refresh_tokens)
            .where(refresh_tokens.c.family_id == family_id, refresh_tokens.c.revoked_at.is_(None))
            .values(revoked_at=func.now())
        )

    async def _revoke_user_sessions(self, session: AsyncSession, user_id: uuid.UUID) -> None:
        await session.execute(
            update(refresh_tokens)
            .where(refresh_tokens.c.user_id == user_id, refresh_tokens.c.revoked_at.is_(None))
            .values(revoked_at=func.now())
        )

    async def _issue_tokens(
        self, session: AsyncSession, user: UserOut, family_id: uuid.UUID
    ) -> TokenResponse:
        refresh = secrets.token_urlsafe(32)
        ttl = self._settings.refresh_token_ttl_seconds
        await session.execute(
            insert(refresh_tokens).values(
                user_id=user.id,
                family_id=family_id,
                token_hash=_hash_token(refresh),
                expires_at=datetime.now(UTC) + timedelta(seconds=ttl),
            )
        )
        return self._issue_token(user, refresh)

    async def _record_failure(self, session: AsyncSession, row: Row[Any], now: datetime) -> None:
        failures = row.failed_logins + 1
        if failures >= self._settings.login_max_failures:
            lock_until = now + timedelta(seconds=self._settings.login_lockout_seconds)
            values: dict[str, Any] = {"failed_logins": 0, "locked_until": lock_until}
            log.warning("account locked after repeated failures", user_id=str(row.id))
        else:
            values = {"failed_logins": failures}
        await session.execute(update(users).where(users.c.id == row.id).values(**values))

    def _issue_token(self, user: UserOut, refresh: str) -> TokenResponse:
        now_ms = int(time.time() * 1000)
        now = now_ms // 1000
        ttl = self._settings.access_token_ttl_seconds
        claims = {
            "iss": self._settings.auth_issuer,
            "aud": self._settings.auth_audience,
            "sub": str(user.id),
            "username": user.username,
            "name": user.display_name,
            "role": user.role.value,
            "jti": uuid.uuid4().hex,
            "iat": now,
            "iat_ms": now_ms,
            "exp": now + ttl,
        }
        return TokenResponse(
            access_token=self._keys.sign(claims),
            expires_in=ttl,
            refresh_token=refresh,
            refresh_expires_in=self._settings.refresh_token_ttl_seconds,
            user=user,
        )

    # Users ---------------------------------------------------------------------------

    async def create_user(
        self, session: AsyncSession, actor: Principal, request: CreateUserRequest
    ) -> UserOut:
        try:
            user_id = (
                await session.execute(
                    insert(users)
                    .values(
                        username=request.username,
                        email=str(request.email),
                        display_name=request.display_name,
                        password_hash=hash_password(request.password),
                        role=request.role.value,
                        created_by=actor.user_id,
                        email_verified_at=func.now(),
                        approved_at=func.now(),
                        approved_by=actor.user_id,
                    )
                    .returning(users.c.id)
                )
            ).scalar_one()
        except IntegrityError as exc:
            raise ServiceError(
                409,
                "User already exists",
                "That username or email is already in use.",
                type_="urn:quantsim:problem:conflict",
            ) from exc
        user = await self._get(session, user_id)
        await self._publish(session, "user.created", user, actor, {"role": user.role.value})
        return user

    async def list_users(
        self, session: AsyncSession, *, include_inactive: bool, limit: int, offset: int
    ) -> UserList:
        query = select(users)
        if not include_inactive:
            query = query.where(users.c.is_active)
        total = (
            await session.execute(select(func.count()).select_from(query.subquery()))
        ).scalar_one()
        rows = await session.execute(
            query.order_by(func.lower(users.c.username)).limit(limit).offset(offset)
        )
        return UserList(items=[UserOut.model_validate(r) for r in rows.all()], total=total)

    async def get_user(self, session: AsyncSession, user_id: uuid.UUID) -> UserOut:
        return await self._get(session, user_id)

    async def deactivate(
        self, session: AsyncSession, actor: Principal, user_id: uuid.UUID
    ) -> UserOut:
        user = await self._get(session, user_id, lock=True)
        if not user.is_active:
            return user
        if user.role is Role.ADMIN:
            await self._ensure_other_admin(session, user_id)
        # Revoke first: if Redis is down this fails closed and nothing changes
        await self._revocations.revoke_user(user_id)
        await self._revoke_user_sessions(session, user_id)
        await session.execute(
            update(users)
            .where(users.c.id == user_id)
            .values(is_active=False, deactivated_at=func.now(), updated_at=func.now())
        )
        user = await self._get(session, user_id)
        await self._publish(session, "user.deactivated", user, actor, {})
        return user

    async def reactivate(
        self, session: AsyncSession, actor: Principal, user_id: uuid.UUID
    ) -> UserOut:
        user = await self._get(session, user_id, lock=True)
        if user.is_active:
            return user
        await session.execute(
            update(users)
            .where(users.c.id == user_id)
            .values(
                is_active=True,
                deactivated_at=None,
                failed_logins=0,
                locked_until=None,
                updated_at=func.now(),
            )
        )
        user = await self._get(session, user_id)
        await self._publish(session, "user.reactivated", user, actor, {})
        return user

    async def change_role(
        self, session: AsyncSession, actor: Principal, user_id: uuid.UUID, role: Role
    ) -> UserOut:
        user = await self._get(session, user_id, lock=True)
        if user.role is role:
            return user
        if user.role is Role.ADMIN and user.is_active:
            await self._ensure_other_admin(session, user_id)
        # Existing tokens carry the old role; cut them off so the change applies at once
        await self._revocations.revoke_user(user_id)
        await self._revoke_user_sessions(session, user_id)
        previous = user.role
        await session.execute(
            update(users)
            .where(users.c.id == user_id)
            .values(role=role.value, updated_at=func.now())
        )
        user = await self._get(session, user_id)
        await self._publish(
            session,
            "user.role_changed",
            user,
            actor,
            {"previous_role": previous.value, "role": role.value},
        )
        return user

    async def history(self, session: AsyncSession, user_id: uuid.UUID) -> list[AuditEntryOut]:
        entries = await record_history(session, "users", str(user_id))
        if not entries:
            raise _not_found(user_id)
        result = []
        for entry in entries:
            before, after = entry.old_data or {}, entry.new_data or {}
            changes = {
                column: {"from": before.get(column), "to": after.get(column)}
                for column in _HISTORY_COLUMNS
                if before.get(column) != after.get(column)
            }
            result.append(
                AuditEntryOut(
                    operation=entry.operation,
                    changed_by=entry.changed_by,
                    request_id=entry.request_id,
                    changed_at=entry.changed_at,
                    changes=changes,
                )
            )
        return result

    # Helpers -------------------------------------------------------------------------

    async def _get(
        self, session: AsyncSession, user_id: uuid.UUID, *, lock: bool = False
    ) -> UserOut:
        query = select(users).where(users.c.id == user_id)
        if lock:
            query = query.with_for_update()
        row = (await session.execute(query)).one_or_none()
        if row is None:
            raise _not_found(user_id)
        return UserOut.model_validate(row)

    async def _ensure_other_admin(self, session: AsyncSession, user_id: uuid.UUID) -> None:
        # Lock every active admin row, so two admins removing each other at the same
        # moment are serialised and cannot both succeed
        admins = (
            await session.execute(
                select(users.c.id)
                .where(users.c.role == Role.ADMIN.value, users.c.is_active)
                .with_for_update()
            )
        ).scalars()
        if not any(admin != user_id for admin in admins):
            raise ServiceError(
                409,
                "Last administrator",
                "The last active administrator cannot be deactivated or demoted.",
                type_="urn:quantsim:problem:conflict",
            )

    async def _publish(
        self,
        session: AsyncSession,
        event_type: str,
        user: UserOut,
        actor: Principal,
        data: dict[str, Any],
    ) -> None:
        await add_event(
            session,
            EventEnvelope(
                event_type=event_type,
                producer="platform",
                aggregate_type="user",
                aggregate_id=str(user.id),
                data={
                    "user_id": str(user.id),
                    "username": user.username,
                    "is_active": user.is_active,
                    "actor_id": str(actor.user_id),
                    **data,
                },
            ),
        )


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def has_active_admin(session: AsyncSession) -> bool:
    count = (
        await session.execute(
            select(func.count()).where(users.c.role == Role.ADMIN.value, users.c.is_active)
        )
    ).scalar_one()
    return bool(count)


async def create_first_admin(
    session: AsyncSession, *, username: str, email: str, password: str
) -> None:
    """Create the initial administrator of a fresh installation."""
    await session.execute(
        insert(users).values(
            username=username,
            email=email,
            display_name="Administrator",
            password_hash=hash_password(password),
            role=Role.ADMIN.value,
            # Set up by the operator: nothing to verify or approve
            email_verified_at=func.now(),
            approved_at=func.now(),
        )
    )
