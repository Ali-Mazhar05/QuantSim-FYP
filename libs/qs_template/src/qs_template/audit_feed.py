"""The audit feed every service serves at ``GET /api/<service>/audit`` (FR-PLT-006..008).

Each service turns its own audit trail (and, where it has them, other durable records such
as ingestion runs) into the same row shape, which is exactly what the frontend Audit Log
page shows: when, who, which service, what happened, how serious, and the detail. The
frontend merges the feeds of every service by time; no service reads another's database.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "warning", "critical"]

FEED_DEFAULT_LIMIT = 200
FEED_MAX_LIMIT = 500


class AuditEventOut(BaseModel):
    id: str = Field(description="Unique across services: '<service>:<source>:<id>'")
    occurred_at: datetime
    actor_id: str | None = Field(description="The acting user's id; null for the system")
    actor: str | None = Field(description="The acting user's username when this service knows it")
    service: str = Field(description="Display name of the service that recorded the event")
    action: str
    severity: Severity
    detail: str
