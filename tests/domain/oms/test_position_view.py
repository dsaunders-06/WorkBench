"""Positions panel view builder (positions panel brief, piece 4).

Pure and testable: no I/O, no globals, and every time-based rule reads the
injected clock rather than the wall clock (this repo has found nine
wall-clock assumptions - this module adds no tenth).

The operator spent an hour hand-computing what these tests assert should be a
lookup: what was paid, how it is tracking, how close it is to being sold, and
what would stop a sell transmitting right now.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.domain.oms.position_view import PositionView, build_position_views
from qat.domain.oms.signal_bridge import PositionEntry
from qat.domain.risk_engine.governor import ExposureSnapshot

_NOW = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)


def _clock() -> datetime:
    return _NOW


def _entry(
    opened_at: datetime = datetime(2026, 7, 1, tzinfo=UTC),
    price: float = 100.0,
    stop_price: float | None = 90.0,
    target_price: float | None = 120.0,
    strategy: str | None = "swing",
) -> PositionEntry:
    return PositionEntry(
        opened_at=opened_at,
        price=price,
        stop_price=stop_price,
        target_price=target_price,
        strategy=strategy,
    )


def _position(symbol: str = "AAA", quantity: float = 100.0, avg_price: float = 91.18) -> Position:
    return Position(symbol=symbol, quantity=quantity, avg_price=avg_price)


def _snapshot(
    equity: float = 100_000.0, risk_by_symbol: dict[str, float] | None = None
) -> ExposureSnapshot:
    risk_by_symbol = risk_by_symbol or {}
    return ExposureSnapshot(
        position_count=len(risk_by_symbol),
        risk_at_stop_dollars=sum(risk_by_symbol.values()),
        gross_exposure_dollars=0.0,
        equity=equity,
        risk_by_symbol=risk_by_symbol,
    )


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


class _NoBars:
    """A `bars_for` that always answers 'nothing recorded' - the shape a
    real strategy's `on_features` guard already treats as too little
    history."""

    def __call__(self, symbol: str) -> pd.DataFrame | None:
        return None


class _SwingLike:
    """A strategy that offers `exit_distance`, the way SwingStrategy does."""

    name = "swing"

    def exit_distance(self, bars: pd.DataFrame) -> float | None:
        return 0.0063


class _NoExitDistance:
    """A strategy without the optional accessor - M84/M85's shape."""

    name = "price-action"


def _build(
    *,
    positions: list[Position] | None = None,
    entries: dict[str, PositionEntry] | None = None,
    resting_stops: dict[str, float] | None = None,
    snapshot: ExposureSnapshot | None = None,
    settings: Settings | None = None,
    bars_for=None,
    strategies=None,
    clock=_clock,
) -> tuple[PositionView, ...]:
    return build_position_views(
        positions=positions if positions is not None else [_position()],
        entries=entries if entries is not None else {"AAA": _entry()},
        resting_stops=resting_stops if resting_stops is not None else {"AAA": 90.0},
        snapshot=snapshot if snapshot is not None else _snapshot(risk_by_symbol={"AAA": 1000.0}),
        settings=settings or _settings(),
        bars_for=bars_for or _NoBars(),
        strategies=strategies if strategies is not None else [_SwingLike()],
        clock=clock,
    )


# --- entry_price: the app's own record, never the broker's avg_price ---------


def test_entry_price_is_the_apps_record_not_the_broker_avg_price():
    """MNST's broker basis sat at $91.18 through a 2-for-1 split - a different
    fact from what this app actually paid, and they must not be confused."""
    views = _build(
        positions=[_position(avg_price=91.18)],
        entries={"AAA": _entry(price=45.59)},
    )
    assert views[0].entry_price == 45.59


def test_no_entry_record_makes_entry_price_and_everything_derived_from_it_none():
    """Do not silently fall back to the broker's avg_price - that is a
    different fact and has disagreed with the app's own record before."""
    views = _build(positions=[_position()], entries={})

    view = views[0]
    assert view.entry_price is None
    assert view.pnl_pct is None
    assert view.pnl_r is None
    # Not derived from entry_price - independently observable.
    assert view.symbol == "AAA"
    assert view.quantity == 100.0


def test_last_price_prefers_the_brokers_live_mark_over_avg_price():
    views = _build(
        positions=[Position(symbol="AAA", quantity=100.0, avg_price=91.18, current_price=95.0)]
    )
    assert views[0].last_price == 95.0


def test_last_price_is_none_with_no_broker_mark():
    """C1: MockBroker/SimulatedBroker construct positions with avg_price as
    the fill/cost basis and no current_price at all - `avg_price` is a
    different fact from a live mark, and must never stand in for one. A P&L
    display's dangerous error is stating a number at all, not under-stating
    one - the opposite of the governor's own risk tiering, which this
    function must not mirror."""
    views = _build(positions=[Position(symbol="AAA", quantity=100.0, avg_price=91.18)])
    view = views[0]
    assert view.last_price is None
    assert view.pnl_pct is None
    assert view.pnl_r is None
    assert view.stop_distance is None


# --- pnl_pct / pnl_r -----------------------------------------------------------


def test_pnl_pct_and_pnl_r_from_the_entry_price_and_the_lots_own_stop():
    views = _build(
        positions=[Position(symbol="AAA", quantity=100.0, avg_price=100.0, current_price=94.0)],
        entries={"AAA": _entry(price=100.0, stop_price=90.0)},
    )
    view = views[0]
    assert view.pnl_pct == pytest.approx(-0.06)
    # (94 - 100) / (100 - 90) = -0.6R
    assert view.pnl_r == pytest.approx(-0.6)


def test_pnl_r_is_none_when_the_lot_carries_no_stop():
    """No stop means no risk denominator - None, never zero."""
    views = _build(
        positions=[Position(symbol="AAA", quantity=100.0, avg_price=100.0, current_price=94.0)],
        entries={"AAA": _entry(price=100.0, stop_price=None)},
    )
    view = views[0]
    assert view.pnl_pct == pytest.approx(-0.06)
    assert view.pnl_r is None


def test_pnl_r_is_none_when_the_recorded_stop_is_not_below_the_entry():
    """A stop at or above entry is not a valid risk denominator."""
    views = _build(
        positions=[Position(symbol="AAA", quantity=100.0, avg_price=100.0, current_price=94.0)],
        entries={"AAA": _entry(price=100.0, stop_price=105.0)},
    )
    assert views[0].pnl_r is None


# --- risk_share: against the BUDGET, not equity -------------------------------


def test_risk_share_is_against_the_aggregate_budget_not_equity():
    """1.0 means this position alone fills the whole cap. The measured book
    sums to about 1.27 of budget, which is correct and is why entries are
    refused - so a share above 1.0 must be representable, not clamped."""
    settings = _settings(max_aggregate_risk_at_stop_pct=0.05)
    snapshot = _snapshot(equity=100_000.0, risk_by_symbol={"AAA": 3_500.0})
    views = _build(snapshot=snapshot, settings=settings)

    # Budget = 100,000 * 0.05 = 5,000; share = 3,500 / 5,000 = 0.70
    assert views[0].risk_share == pytest.approx(0.70)


def test_risk_share_can_exceed_one_when_the_book_is_over_budget():
    settings = _settings(max_aggregate_risk_at_stop_pct=0.05)
    snapshot = _snapshot(equity=100_000.0, risk_by_symbol={"AAA": 6_350.0})
    views = _build(snapshot=snapshot, settings=settings)

    assert views[0].risk_share == pytest.approx(1.27)


# --- stop_distance ---------------------------------------------------------


def test_stop_distance_is_the_fraction_of_last_price_down_to_the_resting_stop():
    views = _build(
        positions=[Position(symbol="AAA", quantity=100.0, avg_price=100.0, current_price=100.0)],
        resting_stops={"AAA": 95.0},
    )
    assert views[0].stop_distance == pytest.approx(0.05)


def test_stop_distance_is_none_with_no_resting_stop():
    views = _build(
        positions=[Position(symbol="AAA", quantity=100.0, avg_price=100.0, current_price=100.0)],
        resting_stops={},
    )
    assert views[0].stop_distance is None


# --- exit_distance: asked of the strategy, getattr-guarded -------------------


def test_exit_distance_comes_from_the_strategy_that_opened_the_position():
    bars = pd.DataFrame({"close": [1.0]})
    views = _build(
        entries={"AAA": _entry(strategy="swing")},
        bars_for=lambda symbol: bars,
        strategies=[_SwingLike()],
    )
    assert views[0].exit_distance == pytest.approx(0.0063)


def test_exit_distance_is_none_for_a_strategy_without_the_optional_accessor():
    """M84/M85's shape - degrade to 'not available' via getattr, never raise."""
    views = _build(
        entries={"AAA": _entry(strategy="price-action")},
        strategies=[_NoExitDistance()],
        bars_for=lambda symbol: pd.DataFrame({"close": [1.0]}),
    )
    assert views[0].exit_distance is None


def test_exit_distance_is_none_with_no_bars_available():
    views = _build(entries={"AAA": _entry(strategy="swing")}, bars_for=_NoBars())
    assert views[0].exit_distance is None


def test_exit_distance_is_none_with_no_entry_record_to_attribute_a_strategy():
    views = _build(entries={})
    assert views[0].exit_distance is None


# --- notes (positions panel brief review, M9: not all of these are reasons a
# sell WON'T fire - "time stop <date>" is a reason one WILL) -----------------


def test_no_stop_resting_is_first_and_alarming():
    views = _build(resting_stops={}, entries={"AAA": _entry(opened_at=_NOW)})
    assert views[0].notes[0] == "no stop resting"


def test_held_until_blocks_a_signal_exit_inside_the_minimum_hold():
    settings = _settings(min_holding_trading_days=5, enforce_time_stop=False)
    views = _build(
        positions=[Position(symbol="AAA", quantity=100.0, avg_price=100.0, current_price=98.0)],
        entries={
            "AAA": _entry(opened_at=datetime(2026, 8, 3, tzinfo=UTC), price=100.0, stop_price=90.0)
        },
        settings=settings,
        clock=lambda: datetime(2026, 8, 6, tzinfo=UTC),  # 3 trading days in
    )
    assert "held until 2026-08-10" in views[0].notes


def test_the_loss_escape_suppresses_the_minimum_hold_blocker():
    """0.6R down against a 0.5R escape - the minimum hold no longer applies to
    a thesis this far wrong."""
    settings = _settings(
        min_holding_trading_days=5, min_holding_loss_escape_r=0.5, enforce_time_stop=False
    )
    views = _build(
        positions=[Position(symbol="AAA", quantity=100.0, avg_price=100.0, current_price=94.0)],
        entries={
            "AAA": _entry(opened_at=datetime(2026, 8, 3, tzinfo=UTC), price=100.0, stop_price=90.0)
        },
        settings=settings,
        clock=lambda: datetime(2026, 8, 6, tzinfo=UTC),
    )
    assert not any(b.startswith("held until") for b in views[0].notes)


def test_a_near_miss_escape_does_not_suppress_the_blocker():
    """0.35R down against a 0.50R escape - the exact scenario the brief warns
    a naive projection would get wrong."""
    settings = _settings(
        min_holding_trading_days=5, min_holding_loss_escape_r=0.5, enforce_time_stop=False
    )
    views = _build(
        positions=[Position(symbol="AAA", quantity=100.0, avg_price=100.0, current_price=96.5)],
        entries={
            "AAA": _entry(opened_at=datetime(2026, 8, 3, tzinfo=UTC), price=100.0, stop_price=90.0)
        },
        settings=settings,
        clock=lambda: datetime(2026, 8, 6, tzinfo=UTC),
    )
    assert any(b.startswith("held until") for b in views[0].notes)


def test_held_until_says_the_escape_is_unknown_with_no_broker_mark():
    """I2: under the C1 fix, a broker reporting no mark makes `last_price`
    None - and the loss escape cannot be evaluated at all without one. The
    gate must say it could not check, not assert it is definitely on."""
    settings = _settings(
        min_holding_trading_days=5, min_holding_loss_escape_r=0.5, enforce_time_stop=False
    )
    views = _build(
        # No current_price - the C1 no-mark case.
        positions=[Position(symbol="AAA", quantity=100.0, avg_price=100.0)],
        entries={
            "AAA": _entry(opened_at=datetime(2026, 8, 3, tzinfo=UTC), price=100.0, stop_price=90.0)
        },
        settings=settings,
        clock=lambda: datetime(2026, 8, 6, tzinfo=UTC),
    )
    assert "held until 2026-08-10 (escape unknown)" in views[0].notes


def test_held_until_has_no_unknown_suffix_when_there_is_no_stop_to_escape_from():
    """No stop means no possible escape route regardless of price - that is a
    known fact, not an unknown one, so no suffix belongs on it even with no
    broker mark."""
    settings = _settings(min_holding_trading_days=5, enforce_time_stop=False)
    views = _build(
        positions=[Position(symbol="AAA", quantity=100.0, avg_price=100.0)],
        entries={
            "AAA": _entry(opened_at=datetime(2026, 8, 3, tzinfo=UTC), price=100.0, stop_price=None)
        },
        settings=settings,
        clock=lambda: datetime(2026, 8, 6, tzinfo=UTC),
    )
    assert "held until 2026-08-10" in views[0].notes
    assert "held until 2026-08-10 (escape unknown)" not in views[0].notes


def test_time_stop_shows_only_within_five_trading_days():
    settings = _settings(time_stop_trading_days=10, enforce_min_holding_period=False)
    views = _build(
        positions=[Position(symbol="AAA", quantity=100.0, avg_price=100.0, current_price=100.0)],
        entries={"AAA": _entry(opened_at=datetime(2026, 8, 3, tzinfo=UTC))},
        settings=settings,
        clock=lambda: datetime(2026, 8, 11, tzinfo=UTC),  # 6 trading days in, 4 remain
    )
    assert "time stop 2026-08-17" in views[0].notes


def test_time_stop_is_absent_when_more_than_five_trading_days_remain():
    settings = _settings(time_stop_trading_days=10, enforce_min_holding_period=False)
    views = _build(
        positions=[Position(symbol="AAA", quantity=100.0, avg_price=100.0, current_price=100.0)],
        entries={"AAA": _entry(opened_at=datetime(2026, 8, 3, tzinfo=UTC))},
        settings=settings,
        clock=lambda: datetime(2026, 8, 6, tzinfo=UTC),  # 3 trading days in, 7 remain
    )
    assert not any(b.startswith("time stop") for b in views[0].notes)


def test_time_stop_is_absent_once_it_is_already_in_the_past():
    """M3: a lot already past its time stop must not render a date in the
    past in a column of forward-looking warnings. In practice the bridge's
    own `_check_time_stop` would have exited this on the next tick; this
    guards the display defensively regardless."""
    settings = _settings(time_stop_trading_days=10, enforce_min_holding_period=False)
    views = _build(
        positions=[Position(symbol="AAA", quantity=100.0, avg_price=100.0, current_price=100.0)],
        entries={"AAA": _entry(opened_at=datetime(2026, 7, 1, tzinfo=UTC))},
        settings=settings,
        # Well past the 10-trading-day time stop.
        clock=lambda: datetime(2026, 8, 6, tzinfo=UTC),
    )
    assert not any(b.startswith("time stop") for b in views[0].notes)


def test_notes_is_empty_when_nothing_blocks():
    """Empty must be distinguishable from 'we could not tell' - it is a
    tuple either way, but it is reachable and means 'nothing is stopping
    this'."""
    settings = _settings(enforce_min_holding_period=False, enforce_time_stop=False)
    views = _build(
        positions=[Position(symbol="AAA", quantity=100.0, avg_price=100.0, current_price=100.0)],
        entries={"AAA": _entry(opened_at=datetime(2020, 1, 1, tzinfo=UTC))},
        resting_stops={"AAA": 90.0},
        settings=settings,
    )
    assert views[0].notes == ()


def test_a_flat_position_is_not_reported():
    views = _build(positions=[_position(quantity=0.0)])
    assert views == ()
