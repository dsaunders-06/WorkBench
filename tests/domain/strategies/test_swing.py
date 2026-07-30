from __future__ import annotations

from _helpers import make_context, make_snapshot

from qat.domain.regime import Regime
from qat.domain.strategies.base import FeatureSnapshot
from qat.domain.strategies.swing import SwingStrategy

_SYMBOL = "AAA"


def test_suitable_regimes():
    """Widened from the paper's Sideways-only by operator decision, 30 July
    2026: the regime engine classified Sideways on 6.2% of the 300 real
    sessions to 29 July, so the only promoted strategy in the system was
    eligible about one session in sixteen."""
    assert SwingStrategy().suitable_regimes() == {
        Regime.SIDEWAYS,
        Regime.BULL,
        Regime.LOW_VOL,
        Regime.RECOVERY,
    }


def test_stress_regimes_stay_excluded():
    """The half of the gate worth keeping: buying a pullback long-only into a
    bear or high-vol tape is knife-catching."""
    excluded = {Regime.BEAR, Regime.HIGH_VOL, Regime.RECESSION}

    assert not SwingStrategy().suitable_regimes() & excluded


def test_pullback_and_reclaim_in_uptrend_emits_buy_with_stop_and_target():
    base = [100.0 + i * 0.5 for i in range(60)]
    dip = base[-1] * 0.95
    reclaim = base[-1] * 1.02
    closes = base + [dip, reclaim]

    universe = {"AAA": make_context("AAA", closes)}
    snapshot = make_snapshot("AAA", universe)

    signals = SwingStrategy(fast_window=20, slow_window=50, atr_window=14).on_features(snapshot)

    assert len(signals) == 1
    assert signals[0].side == "buy"
    assert "stop_price" in signals[0].meta
    assert "target_price" in signals[0].meta
    assert signals[0].meta["stop_price"] < signals[0].meta["target_price"]


def test_no_pullback_emits_nothing():
    closes = [100.0 + i * 0.5 for i in range(60)]
    universe = {"AAA": make_context("AAA", closes)}
    snapshot = make_snapshot("AAA", universe)

    assert SwingStrategy().on_features(snapshot) == []


# --- Exits (M14) --------------------------------------------------------------
# Before M14 this strategy emitted buy-only, so a position it opened had no
# exit path at all short of a human noticing.


def _snapshot(closes: list[float], held: float = 0.0) -> FeatureSnapshot:
    universe = {_SYMBOL: make_context(_SYMBOL, closes)}
    return make_snapshot(_SYMBOL, universe, positions={_SYMBOL: held} if held else {})


def _uptrend(n: int = 80) -> list[float]:
    return [100.0 + i * 0.5 for i in range(n)]


def _rolled_over(n: int = 80) -> list[float]:
    """Rises then falls hard enough to pull the fast EMA under the slow one."""
    rising = [100.0 + i * 0.5 for i in range(n)]
    falling = [rising[-1] - i * 2.0 for i in range(1, 40)]
    return rising + falling


def test_a_held_position_exits_when_the_trend_breaks():
    signals = SwingStrategy().on_features(_snapshot(_rolled_over(), held=10.0))
    assert len(signals) == 1
    assert signals[0].side == "sell"
    assert signals[0].meta["exit_reason"] == "trend_broken"


def test_nothing_is_emitted_for_a_broken_trend_with_no_position():
    """No holding means no exit - and a broken trend is not an entry either."""
    assert SwingStrategy().on_features(_snapshot(_rolled_over(), held=0.0)) == []


def test_a_held_position_in_an_intact_trend_is_left_alone():
    """No exit, and critically no second buy - the bracket and target handle
    the other ways out."""
    assert SwingStrategy().on_features(_snapshot(_uptrend(), held=10.0)) == []


def test_a_held_position_never_produces_another_buy():
    """Pyramiding into a position the strategy already holds would break the
    per-trade risk budget the first entry was sized against."""
    for closes in (_uptrend(), _rolled_over()):
        signals = SwingStrategy().on_features(_snapshot(closes, held=25.0))
        assert all(signal.side != "buy" for signal in signals)


def test_the_exit_uses_the_bare_crossover_with_no_entry_buffer():
    """Entries require a meaningful trend gap; exits must not, or a position
    sits through the whole shallow part of a rollover."""
    strategy = SwingStrategy()
    closes = _uptrend()
    # Nudge the series until the EMAs are barely inverted.
    marginal = closes + [closes[-1] - i * 0.9 for i in range(1, 25)]
    signals = strategy.on_features(_snapshot(marginal, held=10.0))
    assert [s.side for s in signals] == ["sell"]


def test_missing_position_data_reads_as_holding_nothing():
    """An empty positions map must not be mistaken for a holding, or the
    strategy would emit exits for things it does not own."""
    snapshot = _snapshot(_rolled_over(), held=0.0)
    assert snapshot.held_quantity() == 0.0
    assert SwingStrategy().on_features(snapshot) == []
