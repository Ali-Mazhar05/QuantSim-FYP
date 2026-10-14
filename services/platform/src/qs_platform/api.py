"""HTTP API of the Platform service, all under ``/api/platform``.

Public:  POST /auth/login, /auth/refresh, /auth/logout, /auth/signup, /auth/verify-email,
         /auth/resend-verification, /auth/forgot-password, /auth/reset-password,
         GET /.well-known/jwks.json
Signed-in users:  GET /auth/me (with the role's capabilities), POST /auth/change-password
manage_users:  list, invite, read, deactivate and reactivate users; approve or reject
               sign-ups waiting for approval; resend an invitation
manage_roles:  change a user's role
view_audit_log:  a user's change history
"""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from qs_platform.accounts import CHECK_EMAIL, LINK_SENT, AccountService
from qs_platform.keys import SigningKeys
from qs_platform.schemas import (
    AuditEntryOut,
    ChangePasswordRequest,
    ChangeRoleRequest,
    CreateUserRequest,
    EmailRequest,
    LinkTokenRequest,
    LoginRequest,
    MeOut,
    MessageOut,
    PasswordSetOut,
    RefreshRequest,
    ResetPasswordRequest,
    SignUpRequest,
    TokenResponse,
    UserList,
    UserOut,
    VerifyEmailOut,
)
from qs_platform.service import INVALID_CREDENTIALS, INVALID_REFRESH, UserService
from qs_template import Database, ServiceError
from qs_template.audit import set_audit_context
from qs_template.auth import Authenticator, Capability, Principal


def client_address(request: Request) -> str:
    """The caller's address. Through the public tunnel, Cloudflare's edge sets
    CF-Connecting-IP (a caller cannot choose it); on the host, Traefik appends the caller
    as the last X-Forwarded-For entry."""
    cloudflare = request.headers.get("cf-connecting-ip", "").strip()
    if cloudflare:
        return cloudflare
    forwarded = request.headers.get("x-forwarded-for", "")
    last = forwarded.split(",")[-1].strip()
    if last:
        return last
    return request.client.host if request.client else "unknown"


EMAIL_UNVERIFIED = ServiceError(
    403,
    "Email not verified",
    "Verify your email first. We can send the link again.",
    type_="urn:quantsim:problem:email-unverified",
)

SIGNUP_CLOSED = ServiceError(
    404,
    "Not found",
    "Sign-up is closed on this environment.",
    type_="urn:quantsim:problem:not-found",
)


def build_routers(
    *,
    service: UserService,
    accounts: AccountService,
    auth: Authenticator,
    database: Database,
    keys: SigningKeys,
    signup_enabled: bool,
) -> list[APIRouter]:
    public = APIRouter(tags=["auth"])
    users = APIRouter(prefix="/users", tags=["users"])

    ManageUsers = Annotated[Principal, Depends(auth.require_capability(Capability.MANAGE_USERS))]
    ManageRoles = Annotated[Principal, Depends(auth.require_capability(Capability.MANAGE_ROLES))]
    ViewAudit = Annotated[Principal, Depends(auth.require_capability(Capability.VIEW_AUDIT_LOG))]
    Session = Annotated[AsyncSession, Depends(database.session)]

    async def audited(
        request: Request, actor: Principal
    ) -> AsyncIterator[tuple[AsyncSession, Principal]]:
        """A transaction whose changes the audit trail attributes to ``actor``."""
        async with database.transaction() as session:
            await set_audit_context(
                session,
                user_id=actor.user_id,
                request_id=getattr(request.state, "request_id", None),
            )
            yield session, actor

    async def users_session(
        request: Request, actor: ManageUsers
    ) -> AsyncIterator[tuple[AsyncSession, Principal]]:
        async for pair in audited(request, actor):
            yield pair

    async def roles_session(
        request: Request, actor: ManageRoles
    ) -> AsyncIterator[tuple[AsyncSession, Principal]]:
        async for pair in audited(request, actor):
            yield pair

    UsersSession = Annotated[tuple[AsyncSession, Principal], Depends(users_session)]
    RolesSession = Annotated[tuple[AsyncSession, Principal], Depends(roles_session)]

    @public.post("/auth/login", responses={401: {}, 429: {}})
    async def login(body: LoginRequest, response: Response) -> TokenResponse:
        # Failed attempts are counted in their own transaction, committed before the
        # error is returned, so lockout cannot be bypassed by the rollback
        async with database.transaction() as session:
            outcome = await service.login(session, body.username, body.password)
        if outcome.token is not None:
            response.headers["Cache-Control"] = "no-store"
            return outcome.token
        if outcome.email_unverified:
            raise EMAIL_UNVERIFIED
        if outcome.pending_role is not None:
            raise ServiceError(
                403,
                "Waiting for approval",
                "An administrator must approve your account before you can sign in.",
                type_="urn:quantsim:problem:approval-pending",
                extra={"requested_role": outcome.pending_role.value},
            )
        if outcome.locked_seconds is not None:
            raise ServiceError(
                429,
                "Too many failed sign-in attempts",
                "Sign-in is temporarily blocked for this account. Try again later.",
                type_="urn:quantsim:problem:locked",
                extra={"retry_after_seconds": outcome.locked_seconds},
            )
        raise INVALID_CREDENTIALS

    @public.post("/auth/refresh", responses={401: {}})
    async def refresh(body: RefreshRequest, response: Response) -> TokenResponse:
        # Committed before an error is returned, so a detected reuse stays revoked
        async with database.transaction() as session:
            token = await service.refresh(session, body.refresh_token)
        if token is None:
            raise INVALID_REFRESH
        response.headers["Cache-Control"] = "no-store"
        return token

    @public.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(body: RefreshRequest) -> Response:
        async with database.transaction() as session:
            await service.logout(session, body.refresh_token)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @public.post(
        "/auth/signup",
        status_code=status.HTTP_202_ACCEPTED,
        responses={404: {}, 409: {}, 429: {}, 503: {}},
    )
    async def signup(body: SignUpRequest, request: Request) -> MessageOut:
        if not signup_enabled:
            raise SIGNUP_CLOSED
        await accounts.check_client(client_address(request))
        async with database.transaction() as session:
            await accounts.sign_up(session, body)
        return MessageOut(message=CHECK_EMAIL)

    @public.post("/auth/verify-email", responses={400: {}})
    async def verify_email(body: LinkTokenRequest) -> VerifyEmailOut:
        async with database.transaction() as session:
            approval_required = await accounts.verify_email(session, body.token)
        return VerifyEmailOut(approval_required=approval_required)

    @public.post(
        "/auth/resend-verification",
        status_code=status.HTTP_202_ACCEPTED,
        responses={429: {}, 503: {}},
    )
    async def resend_verification(body: EmailRequest, request: Request) -> MessageOut:
        await accounts.check_client(client_address(request))
        async with database.transaction() as session:
            await accounts.resend_verification(session, str(body.email))
        return MessageOut(message=LINK_SENT)

    @public.post(
        "/auth/forgot-password",
        status_code=status.HTTP_202_ACCEPTED,
        responses={429: {}, 503: {}},
    )
    async def forgot_password(body: EmailRequest, request: Request) -> MessageOut:
        await accounts.check_client(client_address(request))
        async with database.transaction() as session:
            await accounts.forgot_password(session, str(body.email))
        return MessageOut(message=LINK_SENT)

    @public.post("/auth/reset-password", responses={400: {}})
    async def reset_password(body: ResetPasswordRequest) -> PasswordSetOut:
        async with database.transaction() as session:
            await accounts.set_password(session, body.token, body.password)
        return PasswordSetOut()

    @public.post("/auth/change-password", responses={400: {}, 401: {}})
    async def change_password(
        body: ChangePasswordRequest,
        request: Request,
        response: Response,
        principal: Annotated[Principal, Depends(auth.principal)],
    ) -> TokenResponse:
        """Change your own password; every other session ends and a new one is returned."""
        async with database.transaction() as session:
            await set_audit_context(
                session,
                user_id=principal.user_id,
                request_id=getattr(request.state, "request_id", None),
            )
            token = await accounts.change_password(
                session, principal.user_id, body.current_password, body.new_password
            )
        if token is None:
            raise ServiceError(
                400,
                "Wrong password",
                "The current password is incorrect.",
                type_="urn:quantsim:problem:wrong-password",
            )
        response.headers["Cache-Control"] = "no-store"
        return token

    @public.get("/.well-known/jwks.json")
    async def jwks(response: Response) -> dict[str, object]:
        response.headers["Cache-Control"] = "public, max-age=300"
        return keys.jwks()

    @public.get("/auth/me")
    async def me(
        session: Session, principal: Annotated[Principal, Depends(auth.principal)]
    ) -> MeOut:
        user = await service.get_user(session, principal.user_id)
        return MeOut.model_validate(user.model_dump(exclude={"status"}))

    @users.get("")
    async def list_users(
        session: Session,
        _: ManageUsers,
        include_inactive: bool = False,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> UserList:
        return await service.list_users(
            session, include_inactive=include_inactive, limit=limit, offset=offset
        )

    @users.post("", status_code=status.HTTP_201_CREATED, responses={409: {}})
    async def create_user(body: CreateUserRequest, context: UsersSession) -> UserOut:
        """Invite a user: they get an email to set their own password."""
        session, admin = context
        return await accounts.invite(session, admin, body)

    @users.post("/{user_id}/approve", responses={404: {}, 409: {}})
    async def approve(user_id: uuid.UUID, context: UsersSession) -> UserOut:
        session, admin = context
        return await accounts.approve(session, admin, user_id)

    @users.post("/{user_id}/reject", responses={404: {}, 409: {}})
    async def reject(user_id: uuid.UUID, context: UsersSession) -> UserOut:
        session, admin = context
        return await accounts.reject(session, admin, user_id)

    @users.post(
        "/{user_id}/resend-invite",
        status_code=status.HTTP_202_ACCEPTED,
        responses={404: {}, 409: {}},
    )
    async def resend_invite(user_id: uuid.UUID, context: UsersSession) -> MessageOut:
        session, admin = context
        await accounts.resend_invite(session, admin, user_id)
        return MessageOut(message="Invitation sent again.")

    @users.get("/{user_id}", responses={404: {}})
    async def get_user(user_id: uuid.UUID, session: Session, _: ManageUsers) -> UserOut:
        return await service.get_user(session, user_id)

    @users.post("/{user_id}/deactivate", responses={404: {}, 409: {}})
    async def deactivate(user_id: uuid.UUID, context: UsersSession) -> UserOut:
        session, admin = context
        return await service.deactivate(session, admin, user_id)

    @users.post("/{user_id}/reactivate", responses={404: {}})
    async def reactivate(user_id: uuid.UUID, context: UsersSession) -> UserOut:
        session, admin = context
        return await service.reactivate(session, admin, user_id)

    @users.put("/{user_id}/role", responses={404: {}, 409: {}})
    async def change_role(
        user_id: uuid.UUID, body: ChangeRoleRequest, context: RolesSession
    ) -> UserOut:
        session, admin = context
        return await service.change_role(session, admin, user_id, body.role)

    @users.get("/{user_id}/history", responses={404: {}})
    async def history(user_id: uuid.UUID, session: Session, _: ViewAudit) -> list[AuditEntryOut]:
        return await service.history(session, user_id)

    return [public, users]
