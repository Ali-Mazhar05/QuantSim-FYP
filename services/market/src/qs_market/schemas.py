"""Request and response bodies of the Market Data API (the published contract)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AssetClass = Literal["equity", "etf", "index", "crypto", "fx"]


class InstrumentIn(BaseModel):
    symbol: str = Field(pattern=r"^[A-Z0-9.\-]{1,15}$")
    name: str = Field(min_length=1, max_length=200)
    exchange: str = Field(pattern=r"^[A-Z0-9]{4}$", description="ISO 10383 MIC, e.g. XNAS")
    calendar: str = Field(default="XNYS", pattern=r"^[A-Z0-9_]{3,10}$")
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    asset_class: AssetClass = "equity"
    vendor_symbol: str | None = Field(default=None, max_length=30)
    notes: str = Field(default="", max_length=2000)


class InstrumentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


class InstrumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    symbol: str
    name: str
    exchange: str
    calendar: str
    currency: str
    asset_class: str
    vendor_symbol: str
    notes: str
    status: str
    created_at: datetime
    retired_at: datetime | None


class BarOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_date: date
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    adj_close: Decimal | None
    split_factor: Decimal
    dividend: Decimal
    revision: int
    quality_flags: list[str]


class ReturnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_date: date
    log_return: float | None
    adj_log_return: float | None
    vol_20d: float | None
    vol_60d: float | None


class RunRequest(BaseModel):
    mode: Literal["manual", "backfill"] = "manual"
    window_start: date | None = None
    window_end: date | None = None
    instrument_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _window_ordered(self) -> "RunRequest":
        if self.window_start and self.window_end and self.window_start > self.window_end:
            raise ValueError("window_start must not be after window_end")
        if self.mode == "backfill" and not self.window_start:
            raise ValueError("a backfill needs window_start")
        return self


class RunItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    instrument_id: uuid.UUID
    symbol: str
    status: str
    fetched: int
    passed: int
    corrected: int
    rejected: int
    revised: int
    gaps: int
    error: str | None


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: str
    mode: str
    status: str
    requested_by: str
    window_start: date | None
    window_end: date | None
    ruleset_version: str | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunDetailOut(RunOut):
    report: dict[str, Any] | None
    items: list[RunItemOut]


class RejectedBarOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    instrument_id: uuid.UUID
    symbol: str
    session_date: date | None
    rules: list[str]
    payload: dict[str, Any]


class DataQualityOut(BaseModel):
    instrument_id: uuid.UUID
    symbol: str
    last_session: date | None
    bars: int
    open_gaps: int
    flagged_bars: int


class ReplaySessionIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    instrument_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    start_time: datetime
    end_time: datetime
    speed: float = Field(default=1.0, gt=0, le=1000)

    @model_validator(mode="after")
    def _window_valid(self) -> "ReplaySessionIn":
        # FR-MKT-008; the database enforces the same rule (NFR-INT-003)
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class ReplaySessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    instrument_ids: list[uuid.UUID]
    start_time: datetime
    end_time: datetime
    speed: float
    status: str
    created_by: uuid.UUID
    created_at: datetime
