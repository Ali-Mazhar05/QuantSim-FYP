"""The platform service's audit feed, ``GET /api/platform/audit`` (admins, ``view_audit_log``).

Every change to ``users`` is already recorded by the database trigger with its before and
after state (the password hash is never logged). This turns each recorded change into rows
of the shared feed shape (:mod:`qs_template.audit_feed`): sign-ups and invitations, email
verification, approvals, role changes, deactivation, sign-ins and failed sign-ins.
"""

import uuid
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qs_platform.models import users
from qs_template.audit import AuditRecord, recent_changes
from qs_template.audit_feed import AuditEventOut, Severity

SERVICE = "Platform"
_ROLE_NAMES = {"viewer": "Viewer", "analyst": "Analyst", "quant": "Quant", "admin": "Admin"}
# Columns whose change says nothing on its own
_NOISE = {"updated_at"}


def _role(value: object) -> str:
    return _ROLE_NAMES.get(str(value), str(value))


def _actor_id(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


class _Event(NamedTuple):
    action: str
    severity: Severity
    detail: str
    # Something only the account holder can do (sign up, verify their email, sign in, fail
    # to sign in). With no acting admin on record it is credited to that account; any other
    # change with no actor on record is shown as the system (a CLI command, a job).
    self_service: bool = False


def _actor_for(record: AuditRecord, event: _Event) -> str | None:
    row = record.new_data or record.old_data or {}
    if acting := _actor_id(record.changed_by):
        return acting
    return _actor_id(str(row.get("id") or "")) if event.self_service else None


def _describe(record: AuditRecord) -> list[_Event]:
    """Each thing one recorded change did."""
    before, after = record.old_data or {}, record.new_data or {}
    name = (after or before).get("username", "?")
    if record.operation == "INSERT":
        role = _role(after.get("role"))
        actor = _actor_id(record.changed_by)
        own_id = _actor_id(str(after.get("id") or ""))
        if actor and actor != own_id:
            return [
                _Event(f"User {name} invited", "info", f"Invited as {role} ({after.get('email')}).")
            ]
        if actor is None and after.get("email_verified_at"):
            # A sign-up always starts unverified; an account born verified with no acting
            # user was made by a command (bootstrap-admin, seed-test-users)
            return [_Event(f"Account {name} created", "info", f"{role} account, created verified.")]
        # The sign-up route records the new account itself as the actor
        return [_Event(f"User {name} signed up", "info", f"Requested a {role} account.", True)]
    if record.operation == "DELETE":
        return [_Event(f"User {name} deleted", "critical", "The account row was removed.")]

    def went(column: str) -> bool:
        return before.get(column) != after.get(column)

    found: list[_Event] = []
    if went("role"):
        found.append(
            _Event(
                f"Role of {name} changed",
                "warning",
                f"{_role(before.get('role'))} → {_role(after.get('role'))}; existing sessions"
                " were revoked.",
            )
        )
    if went("is_active"):
        if after.get("is_active"):
            found.append(_Event(f"User {name} reactivated", "info", "May sign in again."))
        else:
            found.append(
                _Event(
                    f"User {name} deactivated", "warning", "Signed out everywhere; cannot sign in."
                )
            )
    if went("email_verified_at") and after.get("email_verified_at"):
        found.append(
            _Event(f"User {name} verified their email", "info", str(after.get("email")), True)
        )
    if went("approved_at") and after.get("approved_at"):
        found.append(
            _Event(f"User {name} approved", "info", f"{_role(after.get('role'))} access granted.")
        )
    if went("locked_until") and after.get("locked_until"):
        found.append(
            _Event(
                f"Sign-in locked for {name}",
                "warning",
                f"Too many failed sign-ins; locked until {after.get('locked_until')}.",
                True,
            )
        )
    elif went("failed_logins") and (after.get("failed_logins") or 0) > (
        before.get("failed_logins") or 0
    ):
        found.append(
            _Event(
                f"Failed sign-in for {name}",
                "warning",
                f"{after.get('failed_logins')} failed attempts in a row.",
                True,
            )
        )
    if went("last_login_at") and after.get("last_login_at"):
        found.append(_Event(f"User {name} signed in", "info", "Session started.", True))
    if went("email") or went("display_name") or went("username"):
        changed = [c for c in ("username", "email", "display_name") if went(c)]
        found.append(_Event(f"Profile of {name} updated", "info", ", ".join(changed) + " changed"))
    if not found:
        visible = [c for c in after if c not in _NOISE and went(c)]
        if not visible:
            found.append(
                # Not self-service: an emailed reset link and a command-line reset both
                # leave no actor, so with none on record it is shown as the system
                _Event(
                    f"Account {name} updated", "info", "Password or another private field changed."
                )
            )
    return found


async def platform_audit_feed(session: AsyncSession, limit: int) -> list[AuditEventOut]:
    records = await recent_changes(session, ["users"], limit=limit)
    described = [(record, _describe(record)) for record in records]
    ids = {a for record, found in described for e in found if (a := _actor_for(record, e))}
    names: dict[str, str] = {}
    if ids:
        rows = await session.execute(
            select(users.c.id, users.c.username).where(users.c.id.in_([uuid.UUID(i) for i in ids]))
        )
        names = {str(i): n for i, n in rows.all()}
    events: list[AuditEventOut] = []
    for record, found in described:
        for n, event in enumerate(found):
            actor_id = _actor_for(record, event)
            events.append(
                AuditEventOut(
                    id=f"platform:audit:{record.id}:{n}",
                    occurred_at=record.changed_at,
                    actor_id=actor_id,
                    actor=names.get(actor_id) if actor_id else None,
                    service=SERVICE,
                    action=event.action,
                    severity=event.severity,
                    detail=event.detail,
                )
            )
    return events[:limit]
