from __future__ import annotations

from datetime import datetime

from _helpers import make_context

from qat.domain.strategies.base import FeatureSnapshot


def test_symbol_context_holds_bars_technical_and_fundamentals():
    context = make_context("AAA", [100.0, 101.0, 102.0])
    assert context.symbol == "AAA"
    assert len(context.bars) == 3
    assert "return_1d" in context.technical
    assert context.fundamentals.symbol == "AAA"


def test_feature_snapshot_exposes_universe():
    ctx_a = make_context("AAA", [100.0, 101.0])
    ctx_b = make_context("BBB", [50.0, 51.0])
    snapshot = FeatureSnapshot(
        symbol="AAA",
        as_of=datetime(2024, 1, 1),
        context=ctx_a,
        universe={"AAA": ctx_a, "BBB": ctx_b},
    )
    assert snapshot.symbol == "AAA"
    assert set(snapshot.universe) == {"AAA", "BBB"}
