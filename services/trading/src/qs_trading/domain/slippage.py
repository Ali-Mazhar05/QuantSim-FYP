"""Slippage model interface (frozen for task A11, which adds the implementations).

Two models are planned (A-FR-09): fixed basis points, and volume based
(``bps * quantity / bar volume``). Slippage always moves the price against the trader: a
buy fills higher than the reference price and a sale lower.

The implementations (A11) are Pydantic models stored as the portfolio's ``slippage_model``
JSON and rebuilt with :func:`slippage_model_from_json`:

* ``{"kind": "fixed_bps", "bps": "5"}``: every fill moves ``bps / 10_000`` of the
  reference price against the trader.
* ``{"kind": "volume", "bps": "10"}``: the move is ``bps / 10_000 * quantity / volume``.
  The participation ``quantity / volume`` is capped at 1, and a bar with zero (unknown)
  volume counts as full participation. So the volume model charges between nothing and
  ``bps``, never more than the fixed model at the same ``bps``, and a thin or missing
  volume figure cannot push a price to zero or below.

``bps`` is below 10,000 (100 %), so a sale never fills at a negative price. The fill price
is rounded half to even to 8 places; because the reference price is already on that grid,
rounding never turns adverse slippage into a favourable one. A sale is floored at the
smallest price step so it stays above zero.
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from qs_trading.domain.accounting import Side
from qs_trading.domain.costs import ExactDecimal
from qs_trading.domain.money import PRICE_STEP, price


class SlippageModel(Protocol):
    """Returns the fill price for an order of ``quantity`` shares whose reference price
    (the open, or the limit price) is ``reference_price``, on a bar that traded
    ``bar_volume`` shares. The result is a price (8 decimal places, above zero)."""

    def fill_price(
        self, side: Side, quantity: int, reference_price: Decimal, bar_volume: Decimal
    ) -> Decimal: ...


BPS = Decimal("10000")

Bps = Annotated[ExactDecimal, Field(ge=0, lt=10000)]


def _slipped(side: Side, reference_price: Decimal, fraction: Decimal) -> Decimal:
    reference = price(reference_price)
    if Side(side) is Side.BUY:
        return price(reference * (1 + fraction))
    return price(max(reference * (1 - fraction), PRICE_STEP))


def _check_quantity(quantity: int) -> None:
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError(f"quantity must be a whole number above zero, got {quantity!r}")


class FixedBpsSlippage(BaseModel):
    """A fixed ``bps`` move against the trader on every fill."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["fixed_bps"] = "fixed_bps"
    bps: Bps = Decimal("0")

    def fill_price(
        self, side: Side, quantity: int, reference_price: Decimal, bar_volume: Decimal
    ) -> Decimal:
        _check_quantity(quantity)
        return _slipped(side, reference_price, self.bps / BPS)

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class VolumeSlippage(BaseModel):
    """``bps * min(quantity / volume, 1)`` against the trader; zero volume counts as 1."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["volume"] = "volume"
    bps: Bps = Decimal("0")

    def participation(self, quantity: int, bar_volume: Decimal) -> Decimal:
        """The share of the bar's volume the order takes, capped at 1."""
        _check_quantity(quantity)
        if bar_volume <= 0:
            return Decimal(1)
        return min(Decimal(quantity) / bar_volume, Decimal(1))

    def fill_price(
        self, side: Side, quantity: int, reference_price: Decimal, bar_volume: Decimal
    ) -> Decimal:
        fraction = self.bps / BPS * self.participation(quantity, bar_volume)
        return _slipped(side, reference_price, fraction)

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


SlippageConfig = Annotated[FixedBpsSlippage | VolumeSlippage, Field(discriminator="kind")]
"""Either slippage model, chosen by its ``kind``."""

_SLIPPAGE = TypeAdapter[FixedBpsSlippage | VolumeSlippage](SlippageConfig)


def slippage_model_from_json(data: Mapping[str, Any]) -> FixedBpsSlippage | VolumeSlippage:
    """Rebuild a slippage model from the portfolio's stored ``slippage_model`` JSON. Raises a
    Pydantic ``ValidationError`` for an unknown ``kind``, unknown keys, floats or a ``bps``
    outside ``[0, 10000)``."""
    return _SLIPPAGE.validate_python(dict(data))
