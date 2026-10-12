"""Getting an account: self sign-up, email verification, admin approval and invitations,
and setting a password through an emailed link (FR-PLT-001, FR-PLT-002, FR-PLT-006).

- Self sign-up never reveals whether an email already has an account: every well-formed
  request gets the same answer and the difference goes only to that inbox. A taken
  username is reported, because usernames are visible inside the app.
- Viewer sign-ups can sign in once the email is verified; Quant and Analyst sign-ups
  also wait for an admin's approval. Accounts an admin creates need no approval.
- Emailed links are single-use, expire, and are stored only as SHA-256 hashes; issuing a
  new link voids the unused ones of the same purpose.
- Mail is queued in the same transaction as the change (see ``mail``), and the number of
  emails to one address is capped without changing any answer.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from qs_platform.limits import RateLimiter, too_many
from qs_platform.mail import queue_mail
from qs_platform.models import account_tokens, users
from qs_platform.passwords import hash_password
from qs_platform.schemas import CreateUserRequest, SignUpRequest, UserOut
from qs_platform.service import UserService
from qs_platform.settings import PlatformSettings
from qs_template.audit import set_audit_context
from qs_template.auth import Principal, Role
from qs_template.errors import ServiceError
from qs_template.logging import get_logger

log = get_logger(__name__)

VERIFY_EMAIL = "verify_email"
SET_PASSWORD = "set_password"  # noqa: S105 - after an admin invitation; a purpose name
RESET_PASSWORD = "reset_password"  # noqa: S105 - a purpose name, not a secret

LINK_LIFETIME = {
    VERIFY_EMAIL: timedelta(hours=24),
    SET_PASSWORD: timedelta(hours=72),
    RESET_PASSWORD: timedelta(hours=1),
}

# Self sign-ups in these roles wait for an admin
APPROVAL_REQUIRED = frozenset({Role.QUANT, Role.ANALYST})

TEST_USERS = (
    ("test.admin", Role.ADMIN),
    ("test.quant", Role.QUANT),
    ("test.analyst", Role.ANALYST),
    ("test.viewer", Role.VIEWER),
)

CHECK_EMAIL = "Check your email to finish creating your account."
LINK_SENT = "If an account uses that email, we have sent a link."

INVALID_LINK = ServiceError(
    400,
    "Invalid link",
    "This link is invalid or has expired.",
    type_="urn:quantsim:problem:invalid-link",
)

USERNAME_TAKEN = ServiceError(
    409,
    "Username taken",
    "That username is already taken.",
    type_="urn:quantsim:problem:conflict",
)

ALREADY_IN_USE = ServiceError(
    409,
    "User already exists",
    "That username or email is already in use.",
    type_="urn:quantsim:problem:conflict",
)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _not_pending(detail: str) -> ServiceError:
    return ServiceError(409, "Not possible", detail, type_="urn:quantsim:problem:conflict")


class AccountService:
    def __init__(
        self, settings: PlatformSettings, users_service: UserService, limiter: RateLimiter
    ) -> None:
        self._settings = settings
        self._users = users_service
        self._limiter = limiter

    # Limits --------------------------------------------------------------------------

    async def check_client(self, client: str) -> None:
        """Count one public account request from ``client``; 429 when over the limit."""
        wait = await self._limiter.hit(
            f"client:{client}",
            self._settings.signup_rate_limit,
            self._settings.signup_rate_window_seconds,
        )
        if wait is not None:
            raise too_many(wait)

    async def _mail(
        self, session: AsyncSession, to: str, template: str, params: dict[str, str]
    ) -> None:
        """Queue an email unless this address already got its share; silent either way."""
        wait = await self._limiter.hit(
            f"mail:{to.lower()}",
            self._settings.mail_per_address_limit,
            self._settings.mail_per_address_window_seconds,
        )
        if wait is not None:
            log.info("account email skipped: address limit reached", template=template)
            return
        await queue_mail(session, to, template, params)

    # Links ---------------------------------------------------------------------------

    async def _issue_link(self, session: AsyncSession, user_id: uuid.UUID, purpose: str) -> str:
        now = datetime.now(UTC)
        await session.execute(
            update(account_tokens)
            .where(
                account_tokens.c.user_id == user_id,
                account_tokens.c.purpose == purpose,
                account_tokens.c.used_at.is_(None),
            )
            .values(used_at=now)
        )
        token = secrets.token_urlsafe(32)
        await session.execute(
            insert(account_tokens).values(
                user_id=user_id,
                purpose=purpose,
                token_hash=_hash(token),
                created_at=now,
                expires_at=now + LINK_LIFETIME[purpose],
            )
        )
        return token

    async def _use_link(
        self, session: AsyncSession, token: str, purposes: tuple[str, ...]
    ) -> uuid.UUID:
        """Mark the link used and return its user, or raise the same 400 for any fault."""
        row = (
            await session.execute(
                select(account_tokens)
                .where(account_tokens.c.token_hash == _hash(token))
                .with_for_update()
            )
        ).one_or_none()
        now = datetime.now(UTC)
        if (
            row is None
            or row.purpose not in purposes
            or row.used_at is not None
            or row.expires_at <= now
        ):
            raise INVALID_LINK
        await session.execute(
            update(account_tokens).where(account_tokens.c.id == row.id).values(used_at=now)
        )
        user_id: uuid.UUID = row.user_id
        return user_id

    def _link(self, page: str, token: str, purpose: str | None = None) -> str:
        fragment = f"token={token}" + (f"&purpose={purpose}" if purpose else "")
        return f"{self._settings.app_url}/{page}#{fragment}"

    def _sign_in_link(self) -> str:
        return f"{self._settings.app_url}/login"

    # Self sign-up --------------------------------------------------------------------

    async def sign_up(self, session: AsyncSession, request: SignUpRequest) -> None:
        # Hash on every path, so the time taken does not reveal which path ran
        password_hash = hash_password(request.password)
        email = str(request.email)

        taken = (
            await session.execute(
                select(users.c.id).where(func.lower(users.c.username) == request.username)
            )
        ).first()
        if taken:
            raise USERNAME_TAKEN

        existing = (
            await session.execute(
                select(users).where(func.lower(users.c.email) == email.lower()).with_for_update()
            )
        ).one_or_none()
        if existing is not None:
            if existing.email_verified_at is None and existing.is_active:
                token = await self._issue_link(session, existing.id, VERIFY_EMAIL)
                await self._mail(
                    session,
                    existing.email,
                    "verify_email",
                    {"username": existing.username, "link": self._link("verify-email", token)},
                )
            else:
                await self._mail(
                    session,
                    existing.email,
                    "account_exists",
                    {"username": existing.username, "link": self._sign_in_link()},
                )
            return

        role = Role(request.account_type)
        user_id = uuid.uuid4()
        # The new user is the actor of their own creation in the audit trail
        await set_audit_context(session, user_id=user_id, request_id=None)
        approved = role not in APPROVAL_REQUIRED
        try:
            async with session.begin_nested():
                await session.execute(
                    insert(users).values(
                        id=user_id,
                        username=request.username,
                        email=email,
                        display_name=request.username,
                        password_hash=password_hash,
                        role=role.value,
                        created_by=user_id,
                        approved_at=func.now() if approved else None,
                    )
                )
        except IntegrityError as exc:
            # A concurrent sign-up took the username or email between the checks above
            if "users_username_unique" in str(exc.orig):
                raise USERNAME_TAKEN from exc
            return
        user = await self._users.get_user(session, user_id)
        token = await self._issue_link(session, user_id, VERIFY_EMAIL)
        await self._mail(
            session,
            email,
            "verify_email",
            {"username": user.username, "link": self._link("verify-email", token)},
        )
        await self._users._publish(
            session,
            "user.created",
            user,
            user_id,
            {"role": role.value, "source": "signup", "approval_required": not approved},
        )

    async def verify_email(self, session: AsyncSession, token: str) -> bool:
        """Verify the email behind a link; returns True when an admin must still approve."""
        user_id = await self._use_link(session, token, (VERIFY_EMAIL,))
        await set_audit_context(session, user_id=user_id, request_id=None)
        user = await self._users._get(session, user_id, lock=True)
        if user.email_verified_at is None:
            await session.execute(
                update(users)
                .where(users.c.id == user_id)
                .values(email_verified_at=func.now(), updated_at=func.now())
            )
            user = await self._users._get(session, user_id)
            await self._users._publish(session, "user.email_verified", user, user_id, {})
        return user.approved_at is None

    async def resend_verification(self, session: AsyncSession, email: str) -> None:
        row = (
            await session.execute(select(users).where(func.lower(users.c.email) == email.lower()))
        ).one_or_none()
        # Only an unverified self sign-up gets a new link; invitations use resend-invite
        if (
            row is None
            or not row.is_active
            or row.email_verified_at is not None
            or row.created_by != row.id
        ):
            hash_password(email)  # same work as a real request
            return
        token = await self._issue_link(session, row.id, VERIFY_EMAIL)
        await self._mail(
            session,
            row.email,
            "verify_email",
            {"username": row.username, "link": self._link("verify-email", token)},
        )

    # Passwords -----------------------------------------------------------------------

    async def forgot_password(self, session: AsyncSession, email: str) -> None:
        row = (
            await session.execute(select(users).where(func.lower(users.c.email) == email.lower()))
        ).one_or_none()
        if row is None or not row.is_active:
            hash_password(email)  # same work as a real request
            return
        token = await self._issue_link(session, row.id, RESET_PASSWORD)
        await self._mail(
            session,
            row.email,
            "reset_password",
            {
                "username": row.username,
                "link": self._link("set-password", token, "reset"),
            },
        )

    async def set_password(self, session: AsyncSession, token: str, password: str) -> None:
        """Use an invitation or reset link: new password, email verified, lock cleared and
        every existing session ended."""
        password_hash = hash_password(password)
        user_id = await self._use_link(session, token, (SET_PASSWORD, RESET_PASSWORD))
        await set_audit_context(session, user_id=user_id, request_id=None)
        user = await self._users._get(session, user_id, lock=True)
        if not user.is_active:
            raise INVALID_LINK
        await self._users._revocations.revoke_user(user_id)
        await self._users._revoke_user_sessions(session, user_id)
        await session.execute(
            update(users)
            .where(users.c.id == user_id)
            .values(
                password_hash=password_hash,
                email_verified_at=func.coalesce(users.c.email_verified_at, func.now()),
                failed_logins=0,
                locked_until=None,
                updated_at=func.now(),
            )
        )
        user = await self._users._get(session, user_id)
        await self._users._publish(session, "user.password_set", user, user_id, {})

    # Admin: invitations and approval -------------------------------------------------

    async def invite(
        self, session: AsyncSession, actor: Principal, request: CreateUserRequest
    ) -> UserOut:
        try:
            async with session.begin_nested():
                user_id = (
                    await session.execute(
                        insert(users)
                        .values(
                            username=request.username,
                            email=str(request.email),
                            display_name=request.display_name,
                            password_hash=None,
                            role=request.role.value,
                            created_by=actor.user_id,
                            approved_at=func.now(),
                            approved_by=actor.user_id,
                        )
                        .returning(users.c.id)
                    )
                ).scalar_one()
        except IntegrityError as exc:
            # The admin holds manage_users, so telling them is fine
            raise ALREADY_IN_USE from exc
        user = await self._users.get_user(session, user_id)
        await self._send_invite(session, user)
        await self._users._publish(
            session, "user.created", user, actor, {"role": user.role.value, "source": "admin"}
        )
        return user

    async def _send_invite(self, session: AsyncSession, user: UserOut) -> None:
        token = await self._issue_link(session, user.id, SET_PASSWORD)
        await self._mail(
            session,
            user.email,
            "invite",
            {
                "username": user.username,
                "role": user.role.value.title(),
                "link": self._link("set-password", token, "invite"),
            },
        )

    async def resend_invite(
        self, session: AsyncSession, actor: Principal, user_id: uuid.UUID
    ) -> None:
        user = await self._users._get(session, user_id, lock=True)
        if not user.is_active or user.email_verified_at is not None:
            raise _not_pending("Only an invited user who has not set a password can be re-sent.")
        await self._send_invite(session, user)

    async def approve(self, session: AsyncSession, actor: Principal, user_id: uuid.UUID) -> UserOut:
        user = await self._users._get(session, user_id, lock=True)
        if not user.is_active or user.email_verified_at is None or user.approved_at is not None:
            raise _not_pending("Only a verified sign-up waiting for approval can be approved.")
        await session.execute(
            update(users)
            .where(users.c.id == user_id)
            .values(approved_at=func.now(), approved_by=actor.user_id, updated_at=func.now())
        )
        user = await self._users._get(session, user_id)
        await self._mail(
            session,
            user.email,
            "approved",
            {
                "username": user.username,
                "role": user.role.value.title(),
                "link": self._sign_in_link(),
            },
        )
        await self._users._publish(session, "user.approved", user, actor, {"role": user.role.value})
        return user

    async def reject(self, session: AsyncSession, actor: Principal, user_id: uuid.UUID) -> UserOut:
        user = await self._users._get(session, user_id, lock=True)
        if not user.is_active or user.approved_at is not None:
            raise _not_pending("Only a sign-up waiting for approval can be rejected.")
        user = await self._users.deactivate(session, actor, user_id)
        await self._users._publish(session, "user.rejected", user, actor, {"role": user.role.value})
        return user

    # Housekeeping --------------------------------------------------------------------

    async def remove_stale_sign_ups(self, session: AsyncSession) -> int:
        """Delete self sign-ups whose email stayed unverified past the retention period;
        the audit trail keeps what was deleted. Invitations are never removed."""
        cutoff = datetime.now(UTC) - timedelta(days=self._settings.unverified_retention_days)
        await set_audit_context(session, user_id=None, request_id="stale-sign-up-cleanup")
        rows = (
            await session.execute(
                select(users).where(
                    users.c.email_verified_at.is_(None),
                    users.c.created_by == users.c.id,
                    users.c.created_at < cutoff,
                    users.c.last_login_at.is_(None),
                )
            )
        ).all()
        for row in rows:
            user = UserOut.model_validate(row)
            await session.execute(delete(users).where(users.c.id == row.id))
            await self._users._publish(session, "user.expired", user, None, {})
        if rows:
            log.info("stale sign-ups removed", count=len(rows))
        return len(rows)

    async def seed_test_users(self, session: AsyncSession, password: str, email_base: str) -> None:
        """Create or reset the four test accounts (DEV and TEST only): verified, approved,
        active, with the given password. ``email_base`` is ``name@domain``; each account
        gets ``name+qs-<role>@domain``."""
        name, _, domain = email_base.partition("@")
        password_hash = hash_password(password)
        await set_audit_context(session, user_id=None, request_id="seed-test-users")
        for username, role in TEST_USERS:
            email = f"{name}+qs-{role.value}@{domain}"
            values = {
                "email": email,
                "display_name": f"Test {role.value.title()}",
                "password_hash": password_hash,
                "role": role.value,
                "is_active": True,
                "deactivated_at": None,
                "failed_logins": 0,
                "locked_until": None,
            }
            existing = (
                await session.execute(
                    select(users.c.id).where(users.c.username == username).with_for_update()
                )
            ).scalar_one_or_none()
            if existing is None:
                await session.execute(
                    insert(users).values(
                        username=username,
                        email_verified_at=func.now(),
                        approved_at=func.now(),
                        **values,
                    )
                )
            else:
                await session.execute(
                    update(users)
                    .where(users.c.id == existing)
                    .values(
                        email_verified_at=func.coalesce(users.c.email_verified_at, func.now()),
                        approved_at=func.coalesce(users.c.approved_at, func.now()),
                        updated_at=func.now(),
                        **values,
                    )
                )
