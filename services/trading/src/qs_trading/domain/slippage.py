"""Slippage model interface (frozen for task A11, which adds the implementations).

Two models are planned (A-FR-09): fixed basis points, and volume based
(``bps * quantity / bar volume``). Slippage always moves the price against the trader: a
buy fills higher than the reference price and a sale lower.
"""

from decimal import Decimal
from typing import Protocol

from qs_trading.domain.accounting import Side


class SlippageModel(Protocol):
    """Returns the fill price for an order of ``quantity`` shares whose reference price
    (the open, or the limit price) is ``reference_price``, on a bar that traded
    ``bar_volume`` shares. The result is a price (8 decimal places, above zero)."""

    def fill_price(
        self, side: Side, quantity: int, reference_price: Decimal, bar_volume: Decimal
    ) -> Decimal: ...
