"""The two things calibration needs from outside the service, as ports (B15).

``PriceWindowSource`` reads the adjusted closes of an instrument (the market service, or a recorded
file in tests and offline); ``Calibrator`` fits a model to them (``qs_quant``, K5, owned by Lane C).
Both are small protocols, so the job and the API are tested with simple doubles and the real
adapters are swapped in where the service is built.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol
from uuid import UUID

from qs_simulation.domain.calibration import FitResult, Model, PricePoint


class PriceSourceError(Exception):
    """The prices could not be read now (the market service is down, slow or open-circuited). The
    job is retried: the data may well be there next time."""


class InstrumentNotFound(Exception):
    """The market service does not know this instrument."""


class CalibratorUnavailable(Exception):
    """No fitting code exists for this model yet (K5 has not delivered it)."""

    def __init__(self, model: str) -> None:
        self.model = model
        super().__init__(f"the {model} fit is not available yet")


@dataclass(frozen=True)
class InstrumentInfo:
    instrument_id: UUID
    symbol: str
    name: str
    status: str


class PriceWindowSource(Protocol):
    async def instrument(self, instrument_id: UUID) -> InstrumentInfo:
        """The instrument's symbol and name; raises ``InstrumentNotFound``."""
        ...

    async def window(self, instrument_id: UUID, start: date, end: date) -> list[PricePoint]:
        """The adjusted closes of the sessions in ``[start, end]``, in any order; raises
        ``InstrumentNotFound`` or ``PriceSourceError``, and refuses a bar without an adjusted
        close (``CalibrationRefused``) instead of passing a raw price off as an adjusted one."""
        ...


class Calibrator(Protocol):
    @property
    def version(self) -> str:
        """The version of the fitting code, stored beside every result."""
        ...

    def supports(self, model: Model) -> bool: ...

    def fit(self, model: Model, points: list[PricePoint]) -> FitResult:
        """Fit; reports a refusal in ``FitResult.refusal_reason``. Raises ``CalibratorUnavailable``
        for a model with no fitting code."""
        ...


class Getter(Protocol):
    """The part of the service client (K3) the market adapter uses: a GET that returns the JSON
    body, raising when the answer is an error. ``qs_template.service_client.ServiceClient`` has it,
    with its timeouts, retries and circuit breaker."""

    async def get_json(self, path: str, *, params: Mapping[str, Any] | None = None) -> Any: ...
