"""The market service's audit feed, ``GET /api/market/audit`` (admins, ``view_audit_log``).

Three sources become rows of the shared feed shape (:mod:`qs_template.audit_feed`):

- the audit trail of ``instrument`` (added, updated, retired);
- the audit trail of ``market_environment`` (created, status changes);
- ingestion runs (requested, and how they ended, with the cleaning gate's totals).

A run that rejected bars, or only partly succeeded, is a warning; a failed run is
critical, so the Audit Log page's severity filter finds the runs that need a look.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from qs_market.models import ingestion_run, ingestion_run_item
from qs_template import Database
from qs_template.audit import AuditRecord, recent_changes
from qs_template.audit_feed import (
    FEED_DEFAULT_LIMIT,
    FEED_MAX_LIMIT,
    AuditEventOut,
    Severity,
)
from qs_template.auth import Authenticator, Capability, Principal

SERVICE = "Market Data"
AUDITED_TABLES = ("instrument", "market_environment")
_TYPE_NAMES = {"historical_replay": "Historical Replay", "synthetic": "Synthetic Market"}
# Columns whose change is bookkeeping, not something a person did
_NOISE = {"updated_at"}


def _actor(value: str | None) -> str | None:
    """A user id as text, or None for changes the system made without a user."""
    if not value or value == "scheduler":
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def _event(
    source: str,
    key: object,
    at: datetime,
    actor: str | None,
    action: str,
    severity: Severity,
    detail: str,
) -> AuditEventOut:
    return AuditEventOut(
        id=f"market:{source}:{key}",
        occurred_at=at,
        actor_id=actor,
        actor=None,
        service=SERVICE,
        action=action,
        severity=severity,
        detail=detail,
    )


def _changed(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return sorted(k for k in after if k not in _NOISE and before.get(k) != after.get(k))


def _instrument_event(record: AuditRecord) -> AuditEventOut | None:
    before, after = record.old_data or {}, record.new_data or {}
    row = after or before
    symbol = row.get("symbol", "?")
    actor = _actor(record.changed_by)

    def make(action: str, severity: Severity, detail: str) -> AuditEventOut:
        return _event("audit", record.id, record.changed_at, actor, action, severity, detail)

    if record.operation == "INSERT":
        return make(
            f"Instrument {symbol} added",
            "info",
            f"{row.get('name', '')} · {row.get('exchange', '')} · {row.get('asset_class', '')}",
        )
    if record.operation == "DELETE":
        return make(f"Instrument {symbol} deleted", "critical", "The row was removed.")
    changed = _changed(before, after)
    if not changed:
        return None
    if before.get("status") == "active" and after.get("status") == "retired":
        return make(
            f"Instrument {symbol} retired", "warning", "No longer ingested; history is kept."
        )
    if before.get("status") == "retired" and after.get("status") == "active":
        return make(f"Instrument {symbol} reinstated", "info", "Ingested again from now on.")
    detail = "; ".join(
        f"{k}: {before.get(k)} → {after.get(k)}" if k != "notes" else "notes changed"
        for k in changed
        if k not in {"status", "retired_at"}
    )
    return make(f"Instrument {symbol} updated", "info", detail or "Details changed.")


def _environment_event(record: AuditRecord) -> AuditEventOut | None:
    before, after = record.old_data or {}, record.new_data or {}
    row = after or before
    name = row.get("name", "?")
    actor = _actor(record.changed_by)

    def make(action: str, severity: Severity, detail: str) -> AuditEventOut:
        return _event("audit", record.id, record.changed_at, actor, action, severity, detail)

    if record.operation == "INSERT":
        count = len(row.get("instrument_ids") or [])
        return make(
            f"Market environment {name} created",
            "info",
            f"{_TYPE_NAMES.get(row.get('type', ''), row.get('type'))}, {count} instruments,"
            f" {row.get('start_date')} → {row.get('end_date')}, {row.get('frequency')}",
        )
    if record.operation == "DELETE":
        return make(f"Market environment {name} deleted", "warning", "The row was removed.")
    changed = _changed(before, after)
    if not changed:
        return None
    if changed == ["status"]:
        return make(
            f"Market environment {name} is {after.get('status')}",
            "info",
            f"Status {before.get('status')} → {after.get('status')}",
        )
    return make(f"Market environment {name} updated", "info", ", ".join(changed) + " changed")


def _audit_event(record: AuditRecord) -> AuditEventOut | None:
    if record.table_name == "instrument":
        return _instrument_event(record)
    return _environment_event(record)


def _run_events(row: Any) -> list[AuditEventOut]:
    actor = _actor(row.requested_by)
    who = "the scheduler" if row.requested_by == "scheduler" else "a user"
    window = (
        f"{row.window_start or 'watermark'} → {row.window_end or 'latest'}"
        if row.window_start or row.window_end
        else "from each instrument's watermark"
    )
    events = [
        _event(
            "run",
            f"{row.id}:requested",
            row.created_at,
            actor,
            f"Ingestion run requested ({row.mode})",
            "info",
            f"Requested by {who}; vendor {row.vendor}; window {window}.",
        )
    ]
    if row.finished_at is None:
        return events
    totals = (
        f"{row.instruments} instruments: {row.received} bars received, {row.passed} passed,"
        f" {row.corrected} corrected, {row.rejected} rejected, {row.new_bars} new,"
        f" {row.revised} revised"
    )
    severity: Severity = "info"
    if row.status == "failed":
        severity = "critical"
    elif row.status == "partially_succeeded" or row.rejected > 0:
        severity = "warning"
    detail = totals + (f". Error: {row.error}" if row.error else ".")
    events.append(
        _event(
            "run",
            f"{row.id}:finished",
            row.finished_at,
            None,
            f"Ingestion run {row.status.replace('_', ' ')}",
            severity,
            detail,
        )
    )
    return events


async def market_audit_feed(session: AsyncSession, limit: int) -> list[AuditEventOut]:
    events = [
        event
        for record in await recent_changes(session, AUDITED_TABLES, limit=limit)
        if (event := _audit_event(record)) is not None
    ]
    item = ingestion_run_item.c
    runs = await session.execute(
        select(
            ingestion_run.c.id,
            ingestion_run.c.mode,
            ingestion_run.c.status,
            ingestion_run.c.vendor,
            ingestion_run.c.requested_by,
            ingestion_run.c.window_start,
            ingestion_run.c.window_end,
            ingestion_run.c.error,
            ingestion_run.c.created_at,
            ingestion_run.c.finished_at,
            func.count(item.instrument_id).label("instruments"),
            func.coalesce(func.sum(item.received), 0).label("received"),
            func.coalesce(func.sum(item.passed_untouched), 0).label("passed"),
            func.coalesce(func.sum(item.corrected), 0).label("corrected"),
            func.coalesce(func.sum(item.rejected), 0).label("rejected"),
            func.coalesce(func.sum(item.new_bars), 0).label("new_bars"),
            func.coalesce(func.sum(item.revised), 0).label("revised"),
        )
        .select_from(ingestion_run.outerjoin(ingestion_run_item))
        .group_by(ingestion_run.c.id)
        .order_by(ingestion_run.c.created_at.desc())
        .limit(limit)
    )
    for row in runs.all():
        events.extend(_run_events(row))
    events.sort(key=lambda e: (e.occurred_at, e.id), reverse=True)
    return events[:limit]


def build_audit_routers(*, auth: Authenticator, database: Database) -> list[APIRouter]:
    router = APIRouter(tags=["audit"])
    Auditor = Annotated[Principal, Depends(auth.require_capability(Capability.VIEW_AUDIT_LOG))]
    Session = Annotated[AsyncSession, Depends(database.session, scope="function")]

    @router.get("/audit", responses={401: {}, 403: {}})
    async def audit_feed(
        _: Auditor,
        session: Session,
        limit: Annotated[int, Query(ge=1, le=FEED_MAX_LIMIT)] = FEED_DEFAULT_LIMIT,
    ) -> list[AuditEventOut]:
        """Latest events first: instrument and environment changes and ingestion runs."""
        return await market_audit_feed(session, limit)

    return [router]
