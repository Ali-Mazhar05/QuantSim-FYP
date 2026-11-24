"""The schema built by the migrations: it matches the models exactly, and the database itself
refuses what must never exist (B-FR-12, B-NFR-07, B-NFR-08). Every rule has a positive control (a
valid row is accepted) and a refusal that names the constraint, tested with raw SQL on real
PostgreSQL so no application code can be the reason a bad row is rejected."""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, Numeric, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from qs_simulation import models
from qs_template.messaging import messaging_metadata

from .conftest import run

pytestmark = pytest.mark.db

Row = dict[str, Any]


# ---- helpers: raw SQL only, one transaction per statement ----


def _statement(table: str, values: Row) -> tuple[Any, Row]:
    marks = ", ".join(
        f"CAST(:{key} AS jsonb)" if isinstance(value, dict | list) else f":{key}"
        for key, value in values.items()
    )
    params = {k: json.dumps(v) if isinstance(v, dict | list) else v for k, v in values.items()}
    # table and column names are literals from this file, never user input
    return text(f"INSERT INTO {table} ({', '.join(values)}) VALUES ({marks})"), params  # noqa: S608


def insert(url: str, table: str, values: Row) -> None:
    statement, params = _statement(table, values)

    async def work() -> None:
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                await connection.execute(statement, params)
        finally:
            await engine.dispose()

    run(work())


def scalar(url: str, query: str, **params: Any) -> Any:
    async def work() -> Any:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:
                return (await connection.execute(text(query), params)).scalar_one()
        finally:
            await engine.dispose()

    return run(work())


def execute(url: str, query: str, **params: Any) -> None:
    async def work() -> None:
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                await connection.execute(text(query), params)
        finally:
            await engine.dispose()

    run(work())


def refuses(url: str, table: str, values: Row, constraint: str) -> None:
    """The database refuses the row, and the error names the rule that refused it."""
    with pytest.raises(DBAPIError) as caught:
        insert(url, table, values)
    assert constraint in str(caught.value), str(caught.value)[:400]


# ---- valid rows, each a complete answer to its table ----


def calibration_row(**override: Any) -> Row:
    return {
        "id": uuid.uuid4(),
        "model": "gbm",
        "instrument_id": uuid.uuid4(),
        "window_start": date(2019, 1, 2),
        "window_end": date(2024, 12, 31),
        "params": {"mu": 0.08, "sigma": 0.2},
        "std_errors": {"mu": 0.03, "sigma": 0.004},
        "log_likelihood": Decimal("1234.5"),
        "aic": Decimal("-2465.0"),
        "n_obs": 1500,
        "converged": True,
        "input_fingerprint": "abc123",
        "qs_quant_version": "0.1.0",
        "created_by": uuid.uuid4(),
    } | override


def run_row(**override: Any) -> Row:
    return {
        "id": uuid.uuid4(),
        "model": "gbm",
        "n_paths": 1000,
        "n_steps": 252,
        "seed": 42,
        "idempotency_key": uuid.uuid4().hex,
        "status": "queued",
        "storage_mode": "full",
        "created_by": uuid.uuid4(),
    } | override


def run_instrument_row(w: "World", **override: Any) -> Row:
    return {
        "run_id": w.run_id,
        "instrument_id": w.instrument_id,
        "calibration_id": w.calibration_id,
        "position": 0,
        "s0": Decimal("100"),
    } | override


def scenario_row(**override: Any) -> Row:
    return {
        "code": f"flash_crash_{uuid.uuid4().hex[:8]}",
        "name": "Flash crash",
        "type": "price_shock",
        "params": {"drop": 0.2, "at_step": 120},
    } | override


@dataclass
class World:
    """One valid calibration, run and run instrument to hang dependent rows on."""

    url: str
    instrument_id: uuid.UUID
    calibration_id: uuid.UUID
    run_id: uuid.UUID

    def other_instrument(self) -> tuple[uuid.UUID, uuid.UUID]:
        """A second instrument with its own calibration; returns (instrument_id, calibration_id)."""
        row = calibration_row()
        insert(self.url, "calibration", row)
        return row["instrument_id"], row["id"]


def make_world(url: str) -> World:
    calibration = calibration_row()
    insert(url, "calibration", calibration)
    created = run_row()
    insert(url, "run", created)
    world = World(url, calibration["instrument_id"], calibration["id"], created["id"])
    insert(url, "run_instrument", run_instrument_row(world))
    return world


# ---- the migrations and the models agree ----


def _combined_metadata() -> MetaData:
    combined = MetaData()
    for source in (models.metadata, messaging_metadata):
        for table in source.tables.values():
            table.to_metadata(combined)
    return combined


def _diff(connection: Connection) -> list[Any]:
    context = MigrationContext.configure(connection, opts={"compare_type": True})
    return list(compare_metadata(context, _combined_metadata()))


def test_models_match_the_migrations_exactly(migrated_database_url: str) -> None:
    async def work() -> list[Any]:
        engine = create_async_engine(migrated_database_url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(_diff)
        finally:
            await engine.dispose()

    assert run(work()) == []


def test_prices_and_statistics_are_numeric_never_float() -> None:
    for table in models.metadata.tables.values():
        for column in table.columns:
            if column.name in {"s0", "price", "mean_price", "var95", "cvar95", "log_likelihood"}:
                assert isinstance(column.type, Numeric), f"{table.name}.{column.name}"
            if column.name.startswith("q") and column.name[1:].isdigit():
                assert isinstance(column.type, Numeric), f"{table.name}.{column.name}"


# ---- B-FR-12: a run cannot use another instrument's calibration ----


def test_a_run_instrument_cannot_use_another_instruments_calibration(
    migrated_database_url: str,
) -> None:
    w = make_world(migrated_database_url)
    other_instrument, _ = w.other_instrument()
    # the calibration is AAPL's (w.instrument_id); the row claims it belongs to another instrument
    refuses(
        migrated_database_url,
        "run_instrument",
        run_instrument_row(w, instrument_id=other_instrument, position=1),
        "run_instrument_calibration_same_instrument",
    )


def test_a_run_instrument_may_use_its_own_calibration(migrated_database_url: str) -> None:
    w = make_world(migrated_database_url)
    other_instrument, other_calibration = w.other_instrument()
    insert(
        migrated_database_url,
        "run_instrument",
        run_instrument_row(
            w, instrument_id=other_instrument, calibration_id=other_calibration, position=1
        ),
    )


# ---- every table accepts a valid row, and deleting a run removes what hangs on it ----


def test_every_table_accepts_valid_rows_and_a_run_takes_its_dependents_with_it(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    w = make_world(url)
    insert(url, "instrument_ref", {"instrument_id": w.instrument_id, "symbol": "AAPL"})
    insert(
        url,
        "run_correlation",
        {
            "run_id": w.run_id,
            "size": 2,
            "matrix": [[1, 0.5], [0.5, 1]],
            "repair_applied": False,
            "min_eigenvalue_before": Decimal("0.5"),
            "frobenius_change": Decimal("0"),
        },
    )
    insert(
        url,
        "run_statistics",
        {
            "run_id": w.run_id,
            "instrument_id": w.instrument_id,
            "mean_price": Decimal("108"),
            "median_price": Decimal("107"),
            "p5_price": Decimal("80"),
            "p95_price": Decimal("140"),
            "var95": Decimal("0.2"),
            "cvar95": Decimal("0.3"),
        },
    )
    for path_index in (0, 1):
        insert(
            url,
            "path_value",
            {
                "run_id": w.run_id,
                "instrument_id": w.instrument_id,
                "path_index": path_index,
                "step": 1,
                "price": Decimal("101.5"),
            },
        )
    insert(
        url,
        "path_quantile",
        {
            "run_id": w.run_id,
            "instrument_id": w.instrument_id,
            "step": 1,
            **{
                q: Decimal(v)
                for q, v in zip(
                    ("q01", "q05", "q25", "q50", "q75", "q95", "q99"), range(90, 97), strict=True
                )
            },
        },
    )
    # a stressed run: it names its parent and its scenario; a harsher crash is just another row
    scenario = scenario_row(code="severe_crash", params={"drop": 0.6, "at_step": 10})
    insert(url, "scenario", scenario)
    scenario_id = scalar(url, "SELECT id FROM scenario WHERE code = 'severe_crash'")
    insert(url, "run", run_row(parent_run_id=w.run_id, scenario_id=scenario_id))
    insert(url, "run", run_row(status="completed", median_path_index=7))

    counts = {
        table: scalar(url, f"SELECT count(*) FROM {table} WHERE run_id = :r", r=w.run_id)  # noqa: S608
        for table in (
            "run_instrument",
            "run_correlation",
            "run_statistics",
            "path_value",
            "path_quantile",
        )
    }
    assert counts == {
        "run_instrument": 1,
        "run_correlation": 1,
        "run_statistics": 1,
        "path_value": 2,
        "path_quantile": 1,
    }
    assert scalar(url, "SELECT count(*) FROM run WHERE parent_run_id = :r", r=w.run_id) == 1
    # a base run cannot be deleted while a stressed run that derives from it exists
    with pytest.raises(DBAPIError) as caught:
        execute(url, "DELETE FROM run WHERE id = :r", r=w.run_id)
    assert "run_parent" in str(caught.value)


def test_deleting_a_run_deletes_its_instruments_statistics_and_paths(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    w = make_world(url)
    insert(
        url,
        "path_value",
        {
            "run_id": w.run_id,
            "instrument_id": w.instrument_id,
            "path_index": 0,
            "step": 1,
            "price": Decimal("100"),
        },
    )
    insert(
        url,
        "run_correlation",
        {
            "run_id": w.run_id,
            "size": 1,
            "matrix": [[1]],
            "repair_applied": False,
            "min_eigenvalue_before": Decimal("1"),
            "frobenius_change": Decimal("0"),
        },
    )
    execute(url, "DELETE FROM run WHERE id = :r", r=w.run_id)
    for table in ("run_instrument", "path_value", "run_correlation"):
        assert scalar(url, f"SELECT count(*) FROM {table} WHERE run_id = :r", r=w.run_id) == 0  # noqa: S608


# ---- the database refuses bad rows, naming the rule ----

Build = Callable[[World], tuple[str, Row]]


def _calibration(**o: Any) -> Build:
    return lambda w: ("calibration", calibration_row(**o))


def _run(**o: Any) -> Build:
    return lambda w: ("run", run_row(**o))


def _scenario(**o: Any) -> Build:
    return lambda w: ("scenario", scenario_row(**o))


def _second_instrument(**o: Any) -> Build:
    def build(w: World) -> tuple[str, Row]:
        instrument, calibration = w.other_instrument()
        return "run_instrument", run_instrument_row(
            w, instrument_id=instrument, calibration_id=calibration, position=1
        ) | o

    return build


def _duplicate_key(w: World) -> tuple[str, Row]:
    first = run_row(idempotency_key="same-key")
    insert(w.url, "run", first)
    return "run", run_row(idempotency_key="same-key")


def _own_parent(_: World) -> tuple[str, Row]:
    same = uuid.uuid4()
    return "run", run_row(id=same, parent_run_id=same, scenario_id=uuid.uuid4())


def _path(**o: Any) -> Build:
    return lambda w: (
        "path_value",
        {
            "run_id": w.run_id,
            "instrument_id": w.instrument_id,
            "path_index": 0,
            "step": 1,
            "price": Decimal("100"),
        }
        | o,
    )


def _quantiles(**o: Any) -> Build:
    base = dict(
        zip(
            ("q01", "q05", "q25", "q50", "q75", "q95", "q99"),
            map(Decimal, range(90, 97)),
            strict=True,
        )
    )
    return lambda w: (
        "path_quantile",
        {"run_id": w.run_id, "instrument_id": w.instrument_id, "step": 1} | base | o,
    )


def _statistics(**o: Any) -> Build:
    base = {
        "mean_price": Decimal("108"),
        "median_price": Decimal("107"),
        "p5_price": Decimal("80"),
        "p95_price": Decimal("140"),
        "var95": Decimal("0.2"),
        "cvar95": Decimal("0.3"),
    }
    return lambda w: (
        "run_statistics",
        {"run_id": w.run_id, "instrument_id": w.instrument_id} | base | o,
    )


def _correlation(**o: Any) -> Build:
    base = {
        "size": 2,
        "matrix": [[1, 0.5], [0.5, 1]],
        "repair_applied": False,
        "min_eigenvalue_before": Decimal("0.5"),
        "frobenius_change": Decimal("0"),
    }
    return lambda w: ("run_correlation", {"run_id": w.run_id} | base | o)


REFUSALS: list[tuple[str, Build]] = [
    # calibration
    ("calibration_model", _calibration(model="heston")),
    (
        "calibration_window_valid",
        _calibration(window_start=date(2024, 1, 1), window_end=date(2024, 1, 1)),
    ),
    (
        "calibration_window_valid",
        _calibration(window_start=date(2024, 6, 1), window_end=date(2024, 1, 1)),
    ),
    ("calibration_enough_observations", _calibration(n_obs=59)),
    ("calibration_json_objects", _calibration(params=[1, 2])),
    ("calibration_fingerprint", _calibration(input_fingerprint="")),
    # run
    ("run_model", _run(model="heston")),
    ("run_status", _run(status="done")),
    ("run_storage_mode", _run(storage_mode="disk")),
    ("run_paths_within_limits", _run(n_paths=0)),
    ("run_paths_within_limits", _run(n_paths=100_001, storage_mode="quantiles")),
    ("run_steps_within_limits", _run(n_steps=0)),
    ("run_steps_within_limits", _run(n_steps=2_521, storage_mode="quantiles")),
    ("run_seed_not_negative", _run(seed=-1)),
    ("run_full_storage_within_rule", _run(n_paths=1000, n_steps=253, storage_mode="full")),
    ("run_lineage_complete", lambda w: ("run", run_row(parent_run_id=w.run_id))),
    ("run_lineage_complete", _run(scenario_id=uuid.uuid4())),
    ("run_not_its_own_parent", _own_parent),
    ("run_median_path_in_range", _run(median_path_index=1000)),
    ("run_median_path_in_range", _run(median_path_index=-1)),
    ("run_completed_has_median_path", _run(status="completed")),
    ("run_idempotency_key", _duplicate_key),
    # run_instrument
    ("run_instrument_pk", lambda w: ("run_instrument", run_instrument_row(w, position=5))),
    ("run_instrument_position", _second_instrument(position=0)),
    ("run_instrument_position_not_negative", _second_instrument(position=-1)),
    ("run_instrument_start_price_positive", _second_instrument(s0=Decimal("0"))),
    (
        "run_instrument_run",
        lambda w: ("run_instrument", run_instrument_row(w, run_id=uuid.uuid4())),
    ),
    # run_correlation
    ("run_correlation_size", _correlation(size=0, matrix=[])),
    ("run_correlation_matrix_size", _correlation(size=3)),
    ("run_correlation_matrix_size", _correlation(matrix={"not": "a matrix"})),
    (
        "run_correlation_change_not_negative",
        _correlation(repair_applied=True, frobenius_change=Decimal("-1")),
    ),
    (
        "run_correlation_repair_recorded",
        _correlation(repair_applied=False, frobenius_change=Decimal("0.5")),
    ),
    # run_statistics
    ("run_statistics_var_not_above_cvar", _statistics(var95=Decimal("0.4"), cvar95=Decimal("0.3"))),
    ("run_statistics_percentiles_ordered", _statistics(p5_price=Decimal("120"))),
    ("run_statistics_percentiles_ordered", _statistics(p95_price=Decimal("100"))),
    ("run_statistics_run_instrument", _statistics(instrument_id=uuid.uuid4())),
    # path_value and path_quantile
    ("path_value_price_positive", _path(price=Decimal("0"))),
    ("path_value_index_and_step", _path(step=0)),
    ("path_value_index_and_step", _path(path_index=-1)),
    ("path_value_run_instrument", _path(instrument_id=uuid.uuid4())),
    ("path_quantile_ordered", _quantiles(q05=Decimal("99"))),
    ("path_quantile_ordered", _quantiles(q01=Decimal("0"))),
    ("path_quantile_step", _quantiles(step=0)),
    # scenario: kind, code and parameter bounds (a bad parameter is named by its rule)
    ("scenario_type", _scenario(type="earthquake")),
    ("scenario_code_format", _scenario(code="Flash Crash")),
    ("scenario_name_length", _scenario(name="")),
    ("scenario_params_object", _scenario(params=[0.2, 120])),
    ("scenario_price_shock_bounds", _scenario(params={"drop": 1.0, "at_step": 10})),
    ("scenario_price_shock_bounds", _scenario(params={"drop": 0, "at_step": 10})),
    ("scenario_price_shock_bounds", _scenario(params={"at_step": 10})),
    ("scenario_price_shock_bounds", _scenario(params={"drop": "large", "at_step": 10})),
    ("scenario_price_shock_bounds", _scenario(params={"drop": 0.2, "at_step": 0})),
    ("scenario_price_shock_bounds", _scenario(params={"drop": 0.2, "at_step": 1.5})),
    (
        "scenario_vol_multiplier_bounds",
        _scenario(type="vol_multiplier", params={"multiplier": 0.5, "from_step": 1, "to_step": 5}),
    ),
    (
        "scenario_vol_multiplier_bounds",
        _scenario(type="vol_multiplier", params={"multiplier": 11, "from_step": 1, "to_step": 5}),
    ),
    (
        "scenario_vol_multiplier_bounds",
        _scenario(type="vol_multiplier", params={"multiplier": 3, "from_step": 0, "to_step": 5}),
    ),
    (
        "scenario_vol_multiplier_bounds",
        _scenario(type="vol_multiplier", params={"multiplier": 3, "from_step": 1}),
    ),
]


@pytest.mark.parametrize(
    ("constraint", "build"), REFUSALS, ids=[f"{i:02d}-{c}" for i, (c, _) in enumerate(REFUSALS)]
)
def test_the_database_refuses_the_bad_row_and_names_the_rule(
    migrated_database_url: str, constraint: str, build: Build
) -> None:
    w = make_world(migrated_database_url)
    table, values = build(w)
    refuses(migrated_database_url, table, values, constraint)


def test_a_scenario_code_and_an_instrument_ref_are_unique_and_checked(
    migrated_database_url: str,
) -> None:
    url = migrated_database_url
    insert(
        url,
        "scenario",
        scenario_row(
            code="vol_spike",
            type="vol_multiplier",
            params={"multiplier": 3, "from_step": 1, "to_step": 5},
        ),
    )
    refuses(url, "scenario", scenario_row(code="vol_spike"), "scenario_code")
    refuses(
        url,
        "instrument_ref",
        {"instrument_id": uuid.uuid4(), "symbol": ""},
        "instrument_ref_symbol",
    )
    refuses(
        url,
        "instrument_ref",
        {"instrument_id": uuid.uuid4(), "symbol": "X", "status": "gone"},
        "instrument_ref_status",
    )
