"""Vendor adapters: where end-of-day prices come from, behind one narrow interface.

The cleaning gate never learns which vendor sent a record. Each adapter hands it records
in the gate's own shape, so replacing the vendor changes one module and nothing else.
"""

from qs_market.vendor.base import (
    BudgetExhausted,
    BudgetUnavailable,
    PriceSource,
    UnknownSymbol,
    VendorAuthError,
    VendorError,
    VendorProtocolError,
    VendorTransientError,
)

__all__ = [
    "BudgetExhausted",
    "BudgetUnavailable",
    "PriceSource",
    "UnknownSymbol",
    "VendorAuthError",
    "VendorError",
    "VendorProtocolError",
    "VendorTransientError",
]
