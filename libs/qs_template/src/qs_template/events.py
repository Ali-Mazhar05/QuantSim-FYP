"""The envelope every QuantSim event travels in.

Events are published to topics named ``quantsim.<producer>.<aggregate type>`` and keyed
by aggregate id, so all events about one aggregate (one instrument, one portfolio) are
delivered in order. The envelope is versioned; consumers ignore fields they do not know
and producers only add fields within a major version (NFR-MNT-005).
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _now() -> datetime:
    return datetime.now(UTC)


class EventEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
    event_version: int = Field(default=1, ge=1)
    occurred_at: datetime = Field(default_factory=_now)
    producer: str
    aggregate_type: str
    aggregate_id: str
    correlation_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    @property
    def topic(self) -> str:
        return f"quantsim.{self.producer}.{self.aggregate_type}"

    def to_bytes(self) -> bytes:
        return self.model_dump_json().encode()

    @classmethod
    def from_bytes(cls, raw: bytes) -> "EventEnvelope":
        return cls.model_validate_json(raw)
