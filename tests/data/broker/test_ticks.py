"""M123: an off-tick price is not a worse price, it is a rejected order."""

from __future__ import annotations

from decimal import Decimal

import pytest

from qat.data.broker.ticks import (
    ASX_ORDINARY_EQUITY_TICK_PROFILE,
    is_on_tick,
    previous_raw_order_tick,
    round_to_tick,
    tick_size,
)


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        (0.05, "0.001"),  # below $0.10
        (0.099, "0.001"),
        (0.10, "0.005"),  # the first boundary, inclusive of the upper band
        (1.91, "0.005"),  # MGR.AX on 21 August - the case this exists for
        (1.999, "0.005"),
        (2.00, "0.01"),  # the second boundary
        (173.04, "0.01"),  # RIO.AX
    ],
)
def test_the_asx_bands_are_what_the_operating_rules_say(price, expected) -> None:
    assert tick_size(price, "ASX") == Decimal(expected)


@pytest.mark.parametrize(
    ("price", "expected"),
    [("0.10", "0.099"), ("2.00", "1.995"), ("0.011", "0.010")],
)
def test_previous_tick_crosses_asx_bands_without_float_drift(price, expected) -> None:
    assert previous_raw_order_tick(Decimal(price), "ASX") == Decimal(expected)


def test_asx_band_edges_use_the_upper_band() -> None:
    assert tick_size(Decimal("0.10"), "ASX") == Decimal("0.005")
    assert tick_size(Decimal("2.00"), "ASX") == Decimal("0.01")


def test_asx_tick_profile_carries_auditable_source_metadata() -> None:
    profile = ASX_ORDINARY_EQUITY_TICK_PROFILE

    assert profile.version == "asx-ordinary-equity-price-steps-2026-10-02"
    assert profile.source_url.startswith("https://www.asx.com.au/")
    assert profile.retrieved_on.isoformat() == "2026-10-02"
    assert len(profile.content_sha256) == 64
    assert profile.effective_from is not None


def test_previous_tick_refuses_a_price_without_a_positive_predecessor() -> None:
    with pytest.raises(ValueError, match="predecessor"):
        previous_raw_order_tick(Decimal("0.0005"), "ASX")


def test_the_us_tick_is_a_cent_everywhere_this_system_trades() -> None:
    assert tick_size(105.47, "US") == Decimal("0.01")
    assert tick_size(0.5, "US") == Decimal("0.0001")


def test_the_swing_stop_that_prompted_this() -> None:
    """MGR.AX at 1.91 with an ATR stop. 1.8734 is not a price on the ASX, and
    IBKR rejects it rather than rounding it for us."""
    assert not is_on_tick(1.8734, "ASX")

    # The stop protects a long, so it is a SELL and rounds up - tighter.
    assert round_to_tick(1.8734, "ASX", "sell") == 1.875
    assert is_on_tick(1.875, "ASX")


def test_buys_round_down_and_sells_round_up() -> None:
    assert round_to_tick(1.8734, "ASX", "buy") == 1.870
    assert round_to_tick(1.8734, "ASX", "sell") == 1.875
    assert round_to_tick(173.047, "ASX", "buy") == 173.04
    assert round_to_tick(173.041, "ASX", "sell") == 173.05


def test_rounding_never_loosens_protection() -> None:
    """The property, stated as a property. A sell-stop may only move UP, which
    is toward the market and therefore toward triggering sooner."""
    for raw in (1.8734, 4.6612, 7.2649, 0.0834, 173.0401):
        rounded = round_to_tick(raw, "ASX", "sell")
        assert rounded >= raw
        assert rounded - raw < float(tick_size(raw, "ASX"))


def test_rounding_never_pays_more() -> None:
    for raw in (1.8734, 4.6612, 7.2649, 0.0834, 173.0401):
        rounded = round_to_tick(raw, "ASX", "buy")
        assert rounded <= raw
        assert raw - rounded < float(tick_size(raw, "ASX"))


def test_a_price_already_on_a_tick_is_left_alone() -> None:
    for price in (1.875, 2.00, 173.04, 0.005):
        assert round_to_tick(price, "ASX", "buy") == price
        assert round_to_tick(price, "ASX", "sell") == price


def test_rounding_up_across_a_band_boundary_lands_on_the_new_band() -> None:
    """1.9999 rounds up past $2.00, where the tick becomes a cent. 2.0000 is
    valid there; 1.9999's own band would have said 2.000 either way, but the
    destination band is the one that has to bless the result."""
    result = round_to_tick(1.9999, "ASX", "sell")

    assert result == 2.00
    assert is_on_tick(result, "ASX")


def test_a_sub_tick_price_never_floors_to_zero() -> None:
    """Not reachable on either exchange, and returning 0.0 to a broker is the
    kind of thing that is discovered by a rejection rather than by reading."""
    assert round_to_tick(0.0004, "ASX", "buy") == 0.001


def test_a_non_positive_price_is_refused_rather_than_rounded() -> None:
    with pytest.raises(ValueError, match="non-positive"):
        round_to_tick(0.0, "ASX", "buy")


def test_is_on_tick_uses_decimal_not_float_arithmetic() -> None:
    """0.1 + 0.2 != 0.3 in binary, and this is exactly that comparison. A float
    modulo here reports valid prices as invalid."""
    assert is_on_tick(1.875, "ASX")
    assert is_on_tick(0.3, "ASX")
    assert not is_on_tick(1.8731, "ASX")
