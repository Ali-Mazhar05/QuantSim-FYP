"""Hand-computed fixtures for the slippage models (A-FR-09)."""

from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from qs_trading.domain.accounting import Side
from qs_trading.domain.slippage import (
    FixedBpsSlippage,
    VolumeSlippage,
    slippage_model_from_json,
)

VOLUME = D("1000000")


class TestFixedBps:
    def test_buy_fills_higher(self) -> None:
        # 100 * (1 + 5 / 10000) = 100.05
        model = FixedBpsSlippage(bps=D("5"))
        assert model.fill_price(Side.BUY, 10, D("100"), VOLUME) == D("100.05000000")

    def test_sale_fills_lower(self) -> None:
        model = FixedBpsSlippage(bps=D("5"))
        assert model.fill_price(Side.SELL, 10, D("100"), VOLUME) == D("99.95000000")

    def test_ignores_quantity_and_volume(self) -> None:
        model = FixedBpsSlippage(bps=D("5"))
        assert model.fill_price(Side.BUY, 1, D("100"), D("0")) == D("100.05000000")

    def test_rounds_to_eight_places(self) -> None:
        # 12.34567891 * 1.0003 = 12.349382613673 -> 12.34938261
        model = FixedBpsSlippage(bps=D("3"))
        assert model.fill_price(Side.BUY, 1, D("12.34567891"), VOLUME) == D("12.34938261")

    def test_zero_bps_fills_at_the_reference(self) -> None:
        assert FixedBpsSlippage().fill_price(Side.SELL, 1, D("42"), VOLUME) == D("42.00000000")


class TestVolume:
    def test_buy_scales_with_participation(self) -> None:
        # 10 bps * 5000 / 1,000,000 = 0.05 bps; 50 * 1.000005 = 50.00025
        model = VolumeSlippage(bps=D("10"))
        assert model.fill_price(Side.BUY, 5000, D("50"), VOLUME) == D("50.00025000")

    def test_sale_scales_with_participation(self) -> None:
        model = VolumeSlippage(bps=D("10"))
        assert model.fill_price(Side.SELL, 5000, D("50"), VOLUME) == D("49.99975000")

    def test_participation_is_capped_at_the_bar_volume(self) -> None:
        # 3000 shares on a 1000-share bar: participation 1, so the full 10 bps
        model = VolumeSlippage(bps=D("10"))
        assert model.participation(3000, D("1000")) == 1
        assert model.fill_price(Side.BUY, 3000, D("50"), D("1000")) == D("50.05000000")

    @pytest.mark.parametrize("volume", [D("0"), D("-1")])
    def test_unknown_volume_counts_as_full_participation(self, volume: D) -> None:
        model = VolumeSlippage(bps=D("10"))
        assert model.fill_price(Side.SELL, 1, D("50"), volume) == D("49.95000000")


class TestStoredJson:
    @pytest.mark.parametrize(
        ("data", "kind"),
        [
            ({"kind": "fixed_bps", "bps": "5"}, FixedBpsSlippage),
            ({"kind": "volume", "bps": "12.5"}, VolumeSlippage),
        ],
    )
    def test_round_trip(self, data: dict[str, str], kind: type[object]) -> None:
        model = slippage_model_from_json(data)
        assert isinstance(model, kind)
        assert model.to_json() == data
        assert slippage_model_from_json(model.to_json()) == model

    @pytest.mark.parametrize(
        "data",
        [
            {},
            {"bps": "5"},
            {"kind": "spread", "bps": "5"},
            {"kind": "fixed_bps", "bps": 5.0},
            {"kind": "fixed_bps", "bps": "-1"},
            {"kind": "volume", "bps": "10000"},
            {"kind": "volume", "bps": "5", "cap": "1"},
        ],
    )
    def test_refuses_invalid(self, data: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            slippage_model_from_json(data)


def test_a_sale_never_reaches_zero() -> None:
    model = FixedBpsSlippage(bps=D("9999.99"))
    assert model.fill_price(Side.SELL, 1, D("0.00000001"), VOLUME) == D("0.00000001")


@pytest.mark.parametrize("quantity", [0, -3])
def test_refuses_a_bad_quantity(quantity: int) -> None:
    with pytest.raises(ValueError):
        VolumeSlippage(bps=D("1")).fill_price(Side.BUY, quantity, D("10"), VOLUME)
