"""What the broker BILLS, as distinct from what a backtest must model (M175).

The figures are the live ones. The audit of 10 September reconciled a SEK.AX
exit: modelled commission 33.88, IBKR's actual commission 33.88, modelled
slippage 19.25, ledger exit_cost 53.13. The ledger was charging the slippage
of a fill whose price already contained it.
"""

from __future__ import annotations

import pytest

from qat.domain.backtester.costs import CostModel

_ASX_FIXED = CostModel(commission_bps=8.8, slippage_bps=5.0, min_commission=6.60)


def test_charge_is_the_commission_and_never_the_slippage():
    assert _ASX_FIXED.charge(38_500.0) == pytest.approx(33.88)
    # apply() is unchanged: it is still the pre-trade and backtest figure.
    assert _ASX_FIXED.apply(38_500.0) == pytest.approx(53.13)


def test_charge_keeps_the_per_order_floor():
    assert _ASX_FIXED.charge(1_000.0) == pytest.approx(6.60)


def test_charge_includes_fees_the_broker_passes_through():
    tiered = CostModel(
        commission_bps=8.8, slippage_bps=5.0, min_commission=5.50, third_party_bps=0.45375
    )
    assert tiered.charge(100_000.0) == pytest.approx(88.0 + 4.5375)


def test_bhp_average_cost_converts_back_to_its_fill():
    """BHP.AX, 11 September: IBKR's avgCost 64.1263816 over 793 shares is a
    64.07 fill - an exact tick, against a 64.08 reference."""
    assert _ASX_FIXED.fill_price_from_average_cost(64.1263816, 793) == pytest.approx(
        64.07, abs=1e-6
    )


def test_below_the_floor_the_floor_branch_is_used():
    # 10 shares at 50.00 = 500 notional: 8.8 bp is 0.44, so the 6.60 floor binds.
    average = 50.0 + 6.60 / 10
    assert _ASX_FIXED.fill_price_from_average_cost(average, 10) == pytest.approx(50.0)


@pytest.mark.parametrize("fill", [0.89, 5.49, 64.07, 135.736])
@pytest.mark.parametrize("quantity", [10.0, 793.0, 64_229.0])
def test_the_inverse_undoes_the_charge(fill, quantity):
    average = fill + _ASX_FIXED.charge(fill * quantity) / quantity
    assert _ASX_FIXED.fill_price_from_average_cost(average, quantity) == pytest.approx(
        fill, rel=1e-12
    )


def test_no_quantity_returns_the_average_unchanged():
    assert _ASX_FIXED.fill_price_from_average_cost(64.1263816, 0) == 64.1263816
