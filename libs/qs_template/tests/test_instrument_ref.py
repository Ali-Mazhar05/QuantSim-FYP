"""The instrument_ref projection's mapping from market's events (I2-14), without a
database; the upsert itself is covered by the services' database tests."""

import uuid

import pytest
from sqlalchemy import MetaData

from qs_template.events import EventEnvelope
from qs_template.instrument_ref import (
    INSTRUMENT_EVENTS,
    INSTRUMENT_TOPIC,
    instrument_ref_table,
    instrument_values,
)

ID = uuid.UUID(int=1)


def _event(event_type: str, **data: object) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        producer="market",
        aggregate_type="instrument",
        aggregate_id=str(ID),
        data={
            "instrument_id": str(ID),
            "symbol": "MSFT",
            "exchange": "NASDAQ",
            "status": "active",
            **data,
        },
    )


def test_the_topic_is_markets_instrument_topic() -> None:
    assert _event("instrument.created").topic == INSTRUMENT_TOPIC


@pytest.mark.parametrize("event_type", INSTRUMENT_EVENTS)
def test_every_instrument_event_maps_to_a_row(event_type: str) -> None:
    values = instrument_values(_event(event_type))
    assert values["id"] == str(ID)
    assert values["symbol"] == "MSFT"
    assert values["currency"] == "USD"


def test_a_retirement_marks_the_row_retired_whatever_its_payload_says() -> None:
    assert instrument_values(_event("instrument.retired"))["status"] == "retired"
    assert instrument_values(_event("instrument.annotated"))["status"] == "active"


def test_a_currency_in_the_event_is_kept() -> None:
    assert instrument_values(_event("instrument.created", currency="EUR"))["currency"] == "EUR"


def test_the_table_keeps_retired_rows_and_checks_the_status() -> None:
    table = instrument_ref_table(MetaData())
    constraints = {c.name for c in table.constraints}
    assert "instrument_ref_status_valid" in constraints
    assert {"id", "symbol", "exchange", "currency", "status", "updated_at"} <= set(table.c.keys())
