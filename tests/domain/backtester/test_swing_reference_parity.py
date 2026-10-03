"""Cross-check Phase 2 arithmetic and evidence against independent oracles."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from qat.data.broker.ticks import previous_raw_order_tick
from qat.domain.backtester.swing_artifacts import _json_bytes
from qat.domain.backtester.swing_method_audit import PowerRequirement, plan_holdout_duration
from qat.domain.backtester.swing_reference import _exact_binomial_upper
from qat.domain.backtester.swing_statistics import romano_wolf_stepdown, wcr_s_pvalue
from qat.domain.strategies.authoritative_swing.evidence import stable_decision_id
from qat.domain.strategies.authoritative_swing.indicators import ema, wilder_atr
from qat.domain.strategies.authoritative_swing.numeric import (
    SplitFactor,
    to_analytical_price,
    to_raw_price,
)
from qat.domain.strategies.authoritative_swing.resistance import find_resistance_zones
from qat.domain.strategies.authoritative_swing.sizing import size_for_risk
from scripts.research.run_authoritative_swing import _COSTS, _LIQUIDITY, _golden_bar, main
from tests.reference import authoritative_swing_reference as oracle


def test_exact_price_tick_indicators_and_sizing_match_independent_arithmetic() -> None:
    factor = SplitFactor(3, 10)
    for raw in (Decimal("1.91"), Decimal("10.17"), Decimal("37.333")):
        analytical = to_analytical_price(raw, factor)
        assert analytical == oracle.analytical_price(raw, 3, 10)
        assert to_raw_price(analytical, factor) == oracle.raw_price(analytical, 3, 10)
    for price in map(Decimal, ("0.10", "0.105", "1.8734", "2.00", "2.007")):
        assert previous_raw_order_tick(price, "ASX") == oracle.prior_asx_tick(price)

    closes = tuple(Decimal(value) for value in ("9", "10", "11", "9", "8", "12", "10"))
    assert ema(closes, 3) == oracle.ema(closes, 3)
    bars = tuple(
        _golden_bar(
            "REF.AX",
            date(2022, 1, 3) + timedelta(days=index),
            high=close + 1,
            low=close - 1,
            close=close,
            open_price=close,
        )
        for index, close in enumerate(closes)
    )
    assert wilder_atr(bars, 3) == oracle.atr(
        tuple((bar.adjusted.high, bar.adjusted.low, bar.adjusted.close) for bar in bars), 3
    )
    quantity = size_for_risk(Decimal("10000"), Decimal("10"), Decimal("9"), _COSTS, _LIQUIDITY)
    assert quantity.quantity == oracle.risk_quantity(
        Decimal("10000"),
        Decimal("10"),
        Decimal("9"),
        _COSTS.commission_bps,
        _COSTS.min_commission,
        _LIQUIDITY.entry_impact_bps,
        _LIQUIDITY.stop_exit_impact_bps,
    )


def test_resistance_zone_matches_independent_peak_enumeration() -> None:
    highs = [Decimal(5)] * 70
    highs[10], highs[35], highs[60] = Decimal("10"), Decimal("10.05"), Decimal("10.06")
    bars = tuple(
        _golden_bar("ZONE.AX", date(2022, 1, 3) + timedelta(days=index), high=high)
        for index, high in enumerate(highs)
    )
    production = tuple((zone.lower, zone.upper) for zone in find_resistance_zones(bars))
    assert production == oracle.resistance_zones(highs)


def test_inference_and_incidence_match_independent_enumeration() -> None:
    months = (
        (Decimal("0.7"), Decimal("0.4")),
        (Decimal("-0.2"),),
        (Decimal("1.1"), Decimal("0.3"), Decimal("0.1")),
        (Decimal("-0.4"), Decimal("0.2")),
    )
    weights = tuple(
        tuple(1 if (draw >> column) & 1 else -1 for column in range(4)) for draw in range(16)
    )
    observed, expected_p = oracle.wcr_s_pvalue(months, weights)
    assert wcr_s_pvalue(months, weights=weights) == expected_p
    samples = {
        "ema": months,
        "flag": tuple(tuple(value / 2 for value in month) for month in months),
    }
    expected_order, expected_adjusted = oracle.romano_wolf(samples, weights)
    adjusted = romano_wolf_stepdown(samples, weights=weights)
    assert adjusted.order == expected_order
    assert dict(adjusted.adjusted_p_values) == expected_adjusted
    assert adjusted.observed_statistics["ema"] == pytest.approx(observed)
    for events, windows in ((0, 10), (2, 20), (5, 15)):
        assert float(_exact_binomial_upper(events, windows)) == pytest.approx(
            float(oracle.binomial_upper(events, windows)), abs=1e-12
        )


def test_constant_incidence_duration_matches_closed_form() -> None:
    names = ("ema", "flag", "bottom")
    development = {name: (2,) * 60 for name in names}
    validation = {name: (2,) * 24 for name in names}
    requirements = {
        name: PowerRequirement(name, 100, 42, Decimal("0.2"), Decimal("0.8")) for name in names
    }
    plan = plan_holdout_duration(
        development=development,
        validation=validation,
        requirements=requirements,
        available_months=120,
        simulations=20,
        seed=7,
    )
    assert plan.required_months == oracle.constant_month_duration(2, 100, 42)


def test_equivalent_decimal_spellings_have_same_decision_identity_and_output() -> None:
    first = {"raw": Decimal("9.80"), "factor": Decimal("0.300")}
    second = {"raw": Decimal("9.8"), "factor": Decimal("0.3")}
    assert stable_decision_id(first) == stable_decision_id(second)
    assert _json_bytes(first) == _json_bytes(second)
    bar = _golden_bar("REF.AX", date(2022, 1, 3), open_price=Decimal("9.80"))
    alternate = _golden_bar("REF.AX", date(2022, 1, 3), open_price=Decimal("9.8"))
    assert bar.digest == alternate.digest
    assert _json_bytes(bar.raw) == _json_bytes(alternate.raw)


def test_two_frozen_replays_write_identical_semantic_artifacts(tmp_path: Path) -> None:
    roots = (tmp_path / "one", tmp_path / "two")
    bundles = []
    for root in roots:
        assert main(["--catalog", "synthetic-golden", "--out", str(root)]) == 0
        bundles.append(next(path for path in root.iterdir() if path.is_dir()))
    assert bundles[0].name == bundles[1].name
    for filename in (
        "decisions.jsonl",
        "fills.csv",
        "trades.csv",
        "equity.csv",
        "metrics.json",
        "promotion.json",
    ):
        assert (bundles[0] / filename).read_bytes() == (bundles[1] / filename).read_bytes()
    manifests = [
        json.loads((bundle / "manifest.json").read_text(encoding="utf-8")) for bundle in bundles
    ]
    for manifest in manifests:
        manifest.pop("packaging")
        assert manifest["promotion_status"] != "PASS"
    assert manifests[0] == manifests[1]
