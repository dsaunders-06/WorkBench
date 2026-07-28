"""IBKR Australia pricing, checked against the vendor's own arithmetic (M27).

Live trading starts on ASX, and IBKR prices each market differently, so a flat
commission would be modelling the wrong broker. These figures are transcribed
from the APAC stocks pricing page and the ASX/Cboe third-party fee schedules,
all inclusive of GST, which is the basis the operator actually pays on.

The worked example below is IBKR's own. It is the strongest test in this file:
if the model reproduces the number the broker publishes, the rate, the basis
and the arithmetic are all right together.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.domain.backtester.costs import (
    MARKET_COST_PROFILES,
    CostModel,
)


def _model(pricing_model: str = "fixed") -> CostModel:
    settings = Settings(
        _env_file=None, market="ASX", ibkr_pricing_model=pricing_model, slippage_bps=0.0
    )
    return CostModel.from_settings(settings)


def test_the_vendors_own_worked_example_reproduces() -> None:
    """IBKR publishes: 400 shares @ AUD 50 = AUD 17.60 inclusive of GST.

    The same trade is AUD 16.00 exclusive, which is the 0.08% rate before the
    10% GST uplift - so getting both right confirms the basis, not just the
    multiplication.
    """
    inclusive = _model()
    assert inclusive.apply(400 * 50) == pytest.approx(17.60)

    exclusive = CostModel(commission_bps=8.0, slippage_bps=0.0, min_commission=6.00)
    assert exclusive.apply(400 * 50) == pytest.approx(16.00)


def test_the_asx_floor_binds_below_seventy_five_hundred() -> None:
    """AUD 6.60 / 0.088% = AUD 7,500.

    Below it the charge is flat, so cost-to-risk falls as the position grows;
    above it the charge is proportional and the ratio goes flat. Scaling up is
    a cost lever only up to this point, which is worth knowing before assuming
    bigger trades keep getting cheaper.
    """
    profile = MARKET_COST_PROFILES[("ASX", "fixed")]
    assert profile.floor_binds_below == pytest.approx(7_500.0)

    model = _model()
    assert model.apply(5_000.0) == pytest.approx(6.60)  # floor
    assert model.apply(7_500.0) == pytest.approx(6.60)  # exactly at it
    assert model.apply(10_000.0) == pytest.approx(8.80)  # rate


def test_tiered_passes_third_party_fees_through_and_fixed_does_not() -> None:
    """The distinction that decides which model to sign up for.

    Tier I matches Fixed on rate (0.088%) with a lower floor (AUD 5.50), but
    adds exchange and clearing on top. Fixed lists third-party fees as None.
    """
    assert _model("fixed").third_party_bps == 0.0
    assert _model("tiered").third_party_bps == pytest.approx(0.45375)


def test_fixed_wins_above_the_crossover_and_the_gap_widens() -> None:
    """Tiered's advantage is capped at about a dollar; Fixed's is not.

    Below ~AUD 7,130 Tiered is marginally cheaper because of its lower floor.
    Above it both pay 0.088% and only Tiered adds pass-through fees, so Fixed
    wins by a margin that grows with trade size - which is the direction trade
    values are expected to move.
    """
    fixed, tiered = _model("fixed"), _model("tiered")

    assert tiered.apply(2_000.0) < fixed.apply(2_000.0)
    assert tiered.apply(2_000.0) == pytest.approx(5.59, abs=0.01)

    for value in (10_000.0, 20_000.0, 50_000.0):
        assert fixed.apply(value) < tiered.apply(value)
    # And the gap is monotonically widening, not a fixed handicap.
    assert (tiered.apply(50_000.0) - fixed.apply(50_000.0)) > (
        tiered.apply(10_000.0) - fixed.apply(10_000.0)
    )


def test_the_floor_applies_to_commission_not_to_pass_through_fees() -> None:
    """Why third_party_bps is separate from the commission rate.

    Folding exchange and clearing into the rate would let the per-order minimum
    swallow them on small orders - understating exactly the trades where every
    dollar is a large share of the risk.
    """
    tiered = _model("tiered")
    small = 1_000.0

    # Commission is at its AUD 5.50 floor here, and the pass-through is charged
    # on top of it rather than absorbed into it.
    assert tiered.apply(small) > 5.50
    assert tiered.apply(small) == pytest.approx(5.50 + small * 0.45375 / 10_000.0)


def test_an_explicit_setting_beats_the_published_profile() -> None:
    """A deliberate override must never be silently replaced by a schedule."""
    settings = Settings(_env_file=None, market="ASX", broker_min_commission=99.0, slippage_bps=0.0)

    assert CostModel.from_settings(settings).min_commission == 99.0


def test_us_trading_does_not_inherit_australian_pricing() -> None:
    """The whole point of a per-market profile.

    There is no published US profile here yet, so US falls back to the
    configured defaults rather than quietly charging ASX rates.
    """
    assert ("US", "fixed") not in MARKET_COST_PROFILES

    us = CostModel.from_settings(Settings(_env_file=None, market="US"))
    assert us.third_party_bps == 0.0
