from __future__ import annotations

import pytest

from qat.domain.backtester.costs import CostModel


def test_total_bps_is_sum_of_commission_and_slippage():
    assert CostModel(commission_bps=5.0, slippage_bps=3.0).total_bps == 8.0


def test_apply_scales_notional_by_total_bps():
    model = CostModel(commission_bps=10.0, slippage_bps=0.0)
    assert model.apply(10_000.0) == pytest.approx(10.0)


def test_zero_cost_model_applies_nothing():
    model = CostModel(commission_bps=0.0, slippage_bps=0.0)
    assert model.apply(50_000.0) == 0.0
    assert model.total_bps == 0.0
