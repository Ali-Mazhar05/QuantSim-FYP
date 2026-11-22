"""Projections of the trade log (task A15): the pure fold of events into projection rows
(:mod:`.fold`), hash-chain verification (:mod:`.verify`), the row-for-row comparison
(:mod:`.compare`), their trading_db reads and writes (:mod:`.persist`) and the rebuild,
verify and point-in-time commands on top (:mod:`.rebuild`, imported on its own because it
builds on the engine store, which builds on the fold)."""

from qs_trading.projections.compare import TableDifference, compare_projections
from qs_trading.projections.fold import (
    Ledger,
    PortfolioSnapshot,
    ProjectedEvent,
    Projection,
    ProjectionError,
    ProjectionRows,
    fold,
    project_log,
    snapshot_at,
)
from qs_trading.projections.verify import ChainReport, StoredEvent, verify_chain

__all__ = [
    "ChainReport",
    "Ledger",
    "PortfolioSnapshot",
    "ProjectedEvent",
    "Projection",
    "ProjectionError",
    "ProjectionRows",
    "StoredEvent",
    "TableDifference",
    "compare_projections",
    "fold",
    "project_log",
    "snapshot_at",
    "verify_chain",
]
