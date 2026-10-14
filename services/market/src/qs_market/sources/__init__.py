"""Price vendors behind one small interface, so adding or swapping a vendor never touches
the cleaning gate or the pipeline."""

from datetime import date
from typing import Any, Protocol


class VendorError(Exception):
    """A vendor call failed. ``retryable`` failures are tried again with backoff."""

    retryable = True

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class SymbolNotFound(VendorError):
    retryable = False


class VendorRejected(VendorError):
    """The vendor refused the request (bad key, bad parameters); retrying will not help."""

    retryable = False


class RateLimited(VendorError):
    """Our own or the vendor's request budget is used up for now."""


class PriceSource(Protocol):
    name: str

    async def fetch_daily(self, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
        """Raw vendor records for ``symbol`` between ``start`` and ``end`` (inclusive)."""

    def normalise(self, record: dict[str, Any]) -> dict[str, Any]:
        """Map one raw record onto the gate's fields: date, open, high, low, close,
        volume, adj_close, split_factor, dividend."""
