"""QuantSim M1: market data.

Owns the instrument master and every price the platform uses. Bars are fetched from a
vendor, land untouched in staging, and are published only after passing the cleaning
gate (FR-MKT-011). Returns and volatility are computed once and stored (FR-MKT-003), so
no other service recomputes them.
"""
