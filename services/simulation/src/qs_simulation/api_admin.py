"""Queue depth for the operator (B-NFR-13, DL-024): ``GET /api/simulation/admin/queue``.

Administrators (``configure_system``) read how many jobs of each kind wait, run, finished and
failed, how long the oldest waiting job has waited and how many leases have expired (a worker that
died holding a job). It reads the job table and writes nothing, so it can be polled by a person or
by a metrics scraper that wants a number.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import ColumnElement

from qs_simulation.models import job
from qs_template import Database
from qs_template.auth import Authenticator, Capability, Principal


class KindDepth(BaseModel):
    kind: str
    queued: int
    running: int
    succeeded: int
    failed: int
    oldest_queued_seconds: float | None = Field(
        description="How long the longest waiting job has waited; null when none waits"
    )
    expired_leases: int = Field(description="Running jobs whose worker's lease has run out")


class QueueDepth(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "queued": 2,
                    "running": 1,
                    "kinds": [
                        {
                            "kind": "monte_carlo",
                            "queued": 2,
                            "running": 1,
                            "succeeded": 14,
                            "failed": 0,
                            "oldest_queued_seconds": 12.4,
                            "expired_leases": 0,
                        }
                    ],
                }
            ]
        }
    )

    queued: int
    running: int
    kinds: list[KindDepth]


def build_admin_routers(*, auth: Authenticator, database: Database) -> list[APIRouter]:
    router = APIRouter(prefix="/admin", tags=["admin"])
    Admin = Annotated[Principal, Depends(auth.require_capability(Capability.CONFIGURE_SYSTEM))]
    Session = Annotated[AsyncSession, Depends(database.session, scope="function")]

    @router.get("/queue", response_model=QueueDepth, responses={401: {}, 403: {}})
    async def queue_depth(_: Admin, session: Session) -> QueueDepth:
        now = func.now()

        rows = (
            await session.execute(
                select(
                    job.c.kind,
                    _in("queued").label("queued"),
                    _in("running").label("running"),
                    _in("succeeded").label("succeeded"),
                    _in("failed").label("failed"),
                    func.extract(
                        "epoch", now - func.min(case((job.c.status == "queued", job.c.created_at)))
                    ).label("oldest"),
                    func.count()
                    .filter(and_(job.c.status == "running", job.c.lease_expires_at < now))
                    .label("expired"),
                )
                .group_by(job.c.kind)
                .order_by(job.c.kind)
            )
        ).all()
        kinds = [
            KindDepth(
                kind=r.kind,
                queued=r.queued,
                running=r.running,
                succeeded=r.succeeded,
                failed=r.failed,
                oldest_queued_seconds=None if r.oldest is None else round(float(r.oldest), 3),
                expired_leases=r.expired,
            )
            for r in rows
        ]
        return QueueDepth(
            queued=sum(k.queued for k in kinds), running=sum(k.running for k in kinds), kinds=kinds
        )

    return [router]


def _in(status: str) -> ColumnElement[int]:
    """How many jobs are in ``status`` (a FILTER over the group)."""
    return func.count().filter(job.c.status == status)
