"""HTTP API of the Platform service, all under ``/api/platform``.

Public:  POST /auth/login, GET /.well-known/jwks.json
Signed-in users:  GET /auth/me
Admins:  user management and per-user change history
"""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from qs_platform.keys import SigningKeys
from qs_platform.schemas import (
    AuditEntryOut,
    ChangeRoleRequest,
    CreateUserRequest,
    LoginRequest,
    TokenResponse,
    UserList,
    UserOut,
)
from qs_platform.service import INVALID_CREDENTIALS, UserService
from qs_template import Database, ServiceError
from qs_template.audit import set_audit_context
from qs_template.auth import Authenticator, Principal, Role


def build_routers(
    *, service: UserService, auth: Authenticator, database: Database, keys: SigningKeys
) -> list[APIRouter]:
    public = APIRouter(tags=["auth"])
    users = APIRouter(prefix="/users", tags=["users"])

    Admin = Annotated[Principal, Depends(auth.require(Role.ADMIN))]
    Session = Annotated[AsyncSession, Depends(database.session)]

    async def admin_session(
        request: Request, admin: Admin
    ) -> AsyncIterator[tuple[AsyncSession, Principal]]:
        """A transaction whose changes the audit trail attributes to the admin."""
        async with database.transaction() as session:
            await set_audit_context(
                session,
                user_id=admin.user_id,
                request_id=getattr(request.state, "request_id", None),
            )
            yield session, admin

    AdminSession = Annotated[tuple[AsyncSession, Principal], Depends(admin_session)]

    @public.post("/auth/login", responses={401: {}, 429: {}})
    async def login(body: LoginRequest, response: Response) -> TokenResponse:
        # Failed attempts are counted in their own transaction, committed before the
        # error is returned, so lockout cannot be bypassed by the rollback
        async with database.transaction() as session:
            outcome = await service.login(session, body.username, body.password)
        if outcome.token is not None:
            response.headers["Cache-Control"] = "no-store"
            return outcome.token
        if outcome.locked_seconds is not None:
            raise ServiceError(
                429,
                "Too many failed sign-in attempts",
                "Sign-in is temporarily blocked for this account. Try again later.",
                type_="urn:quantsim:problem:locked",
                extra={"retry_after_seconds": outcome.locked_seconds},
            )
        raise INVALID_CREDENTIALS

    @public.get("/.well-known/jwks.json")
    async def jwks(response: Response) -> dict[str, object]:
        response.headers["Cache-Control"] = "public, max-age=300"
        return keys.jwks()

    @public.get("/auth/me")
    async def me(
        session: Session, principal: Annotated[Principal, Depends(auth.principal)]
    ) -> UserOut:
        return await service.get_user(session, principal.user_id)

    @users.get("")
    async def list_users(
        session: Session,
        _: Admin,
        include_inactive: bool = False,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> UserList:
        return await service.list_users(
            session, include_inactive=include_inactive, limit=limit, offset=offset
        )

    @users.post("", status_code=status.HTTP_201_CREATED, responses={409: {}})
    async def create_user(body: CreateUserRequest, context: AdminSession) -> UserOut:
        session, admin = context
        return await service.create_user(session, admin, body)

    @users.get("/{user_id}", responses={404: {}})
    async def get_user(user_id: uuid.UUID, session: Session, _: Admin) -> UserOut:
        return await service.get_user(session, user_id)

    @users.post("/{user_id}/deactivate", responses={404: {}, 409: {}})
    async def deactivate(user_id: uuid.UUID, context: AdminSession) -> UserOut:
        session, admin = context
        return await service.deactivate(session, admin, user_id)

    @users.post("/{user_id}/reactivate", responses={404: {}})
    async def reactivate(user_id: uuid.UUID, context: AdminSession) -> UserOut:
        session, admin = context
        return await service.reactivate(session, admin, user_id)

    @users.put("/{user_id}/role", responses={404: {}, 409: {}})
    async def change_role(
        user_id: uuid.UUID, body: ChangeRoleRequest, context: AdminSession
    ) -> UserOut:
        session, admin = context
        return await service.change_role(session, admin, user_id, body.role)

    @users.get("/{user_id}/history", responses={404: {}})
    async def history(user_id: uuid.UUID, session: Session, _: Admin) -> list[AuditEntryOut]:
        return await service.history(session, user_id)

    return [public, users]
