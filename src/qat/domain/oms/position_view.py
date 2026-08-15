"""Turns held positions into what an operator actually needs to see: what was
paid, how it is tracking, how close it is to being sold, and what is stopping
it (positions panel brief, piece 4).

Prompted by an hour of hand analysis that should have been a screen. The
governor already loops every position applying the three-tier price rule
that fixed a 27% risk understatement (M66/M90); the swing strategy already
computes the two EMAs its exit condition compares; the bridge already keeps
the entry record. This module computes nothing new - it reads what those
three already produce and shapes it, the way `adopted.py` shapes the
governor's own numbers into a banner rather than re-deriving them.

**A display that states something false is the defect class this project has
been bitten by most (M81, M82).** So the rule throughout is: show nothing
rather than guess. `None` and zero are different facts, and a value this
module cannot support is `None`, never `0` or `0.0`.

**The exit column is a DISTANCE, not a forecast.** `exit_distance` says how
far the strategy's own crossover condition is from firing; it says nothing
about *when*, because a projection that ignores the gates below lies in the
useful direction. A position can sit 0.63% from its EMA crossover, inside its
minimum hold, and only 0.35R down against a 0.50R loss escape - "sells in a
few sessions" would have been wrong on all three counts at once.

Pure and injectable: no I/O, no globals, and every time-based rule below
reads `clock()` rather than the wall clock.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.domain.oms.signal_bridge import PositionEntry, _trading_days_between
from qat.domain.risk_engine.governor import ExposureSnapshot
from qat.domain.strategies.base import Strategy

# How close a time stop has to be before it is worth a row on the panel. Any
# further out and it is permanent furniture rather than something to act on -
# the same reasoning `_check_time_stop`'s neighbour, the minimum hold, gets
# from its own loss escape: a rail that is always visible is one the operator
# learns to stop reading.
_TIME_STOP_WARNING_WINDOW_TRADING_DAYS = 5


@dataclass(frozen=True, slots=True)
class PositionView:
    """One row of the positions panel. Every optional field is `None` when
    the system genuinely cannot say - never a substitute zero."""

    symbol: str
    quantity: float
    entry_price: float | None
    """The app's own entry record, never the broker's avg_price - the two are
    different facts and have disagreed (MNST's broker basis stayed at $91.18
    through a 2-for-1 split)."""
    last_price: float | None
    pnl_pct: float | None
    pnl_r: float | None
    """(last - entry) / (entry - stop). None when the lot carries no stop -
    there is no R without a risk denominator."""
    exit_distance: float | None
    """The strategy's own answer, asked rather than re-derived. None when the
    strategy has no accessor, there is no record of which strategy opened
    this, or there are too few bars to judge."""
    stop_distance: float | None
    """Fraction of last price down to the RESTING stop - the level that
    would actually trigger a sell, which may differ from the stop the lot
    was originally sized against."""
    risk_share: float | None
    """This position's risk-at-stop against the aggregate BUDGET, not
    equity: 1.0 means this position alone fills the whole cap, and the figure
    is allowed to exceed 1.0 - the measured book sums to about 1.27 of
    budget, which is correct and is why entries are refused."""
    blockers: tuple[str, ...]
    """Why a sell would not transmit right now, most alarming first. Empty
    means nothing blocks - distinguishable from every individual field above
    being unable to say anything at all."""


def _first_session_that_clears(opened_at: datetime, trading_days: int) -> date:
    """The first date on which `trading_days` trading days will have elapsed
    since `opened_at`.

    Built from `_trading_days_between` itself rather than a second calendar:
    stepping one calendar day at a time and asking the same function whether
    enough trading days have passed yet cannot disagree with it about what a
    trading day is, because it never computes that independently.
    """
    candidate = opened_at
    while _trading_days_between(opened_at, candidate) < trading_days:
        candidate += timedelta(days=1)
    return candidate.date()


def _blockers(
    *,
    symbol: str,
    entry: PositionEntry | None,
    resting_stops: Mapping[str, float],
    last_price: float | None,
    settings: Settings,
    now: datetime,
) -> tuple[str, ...]:
    blockers: list[str] = []

    # First and alarming: an exit signal has nothing resting to protect this
    # position in the meantime, which is a different and more urgent fact
    # than any gate below.
    if symbol not in resting_stops:
        blockers.append("no stop resting")

    if entry is None:
        # Nothing below is knowable without the app's own entry record - the
        # minimum hold and time stop are both measured from `opened_at`.
        return tuple(blockers)

    held_days = _trading_days_between(entry.opened_at, now)

    if settings.enforce_min_holding_period and held_days < settings.min_holding_trading_days:
        # The loss escape - the same one `_blocked_by_minimum_hold` applies -
        # is what keeps a minimum hold from sitting through a broken thesis
        # to save a few dollars of commission. Reproduced here rather than
        # called there because the bridge's version acts (submits an exit);
        # this one only reports.
        escaped = False
        stop = entry.stop_price
        if stop is not None and stop < entry.price and last_price is not None:
            risk = entry.price - stop
            loss_r = (entry.price - last_price) / risk
            escaped = loss_r >= settings.min_holding_loss_escape_r
        if not escaped:
            clears_on = _first_session_that_clears(
                entry.opened_at, settings.min_holding_trading_days
            )
            blockers.append(f"held until {clears_on:%Y-%m-%d}")

    if settings.enforce_time_stop:
        remaining = settings.time_stop_trading_days - held_days
        if remaining <= _TIME_STOP_WARNING_WINDOW_TRADING_DAYS:
            fires_on = _first_session_that_clears(entry.opened_at, settings.time_stop_trading_days)
            blockers.append(f"time stop {fires_on:%Y-%m-%d}")

    return tuple(blockers)


def _last_price(position: Position) -> float | None:
    """The broker's live mark, falling back to the average cost when none is
    reported (M66's tier 2/3, without the UI-only override tier 1 - nothing
    on this panel's path ever supplies one)."""
    if position.current_price is not None:
        return position.current_price
    return position.avg_price


def build_position_views(
    *,
    positions: Iterable[Position],
    entries: Mapping[str, PositionEntry],
    resting_stops: Mapping[str, float],
    snapshot: ExposureSnapshot,
    settings: Settings,
    bars_for: Callable[[str], pd.DataFrame | None],
    strategies: Iterable[Strategy],
    clock: Callable[[], datetime],
) -> tuple[PositionView, ...]:
    """One `PositionView` per held position. Pure: every input is handed in,
    nothing is read from a global, a broker, or the wall clock.

    `snapshot` must already carry `risk_by_symbol` - built by
    `PortfolioGovernor.snapshot()`, never recomputed here, for the reason
    piece 1 of the brief gives: a second derivation of per-position risk
    would drift from the one the aggregate cap is actually gated on.
    """
    by_strategy_name = {strategy.name: strategy for strategy in strategies}
    now = clock()
    budget_dollars = snapshot.equity * settings.max_aggregate_risk_at_stop_pct

    views: list[PositionView] = []
    for position in positions:
        if position.quantity == 0:
            continue
        symbol = position.symbol
        entry = entries.get(symbol)
        last_price = _last_price(position)

        pnl_pct: float | None = None
        pnl_r: float | None = None
        if entry is not None and last_price is not None and entry.price != 0:
            pnl_pct = (last_price - entry.price) / entry.price
            # No stop on the lot means no risk denominator - None, not zero
            # (piece 4's own rule, restated from the aggregate risk one).
            if entry.stop_price is not None and entry.stop_price < entry.price:
                risk = entry.price - entry.stop_price
                pnl_r = (last_price - entry.price) / risk

        exit_distance: float | None = None
        if entry is not None and entry.strategy is not None:
            strategy = by_strategy_name.get(entry.strategy)
            # Optional by design (other strategies, e.g. M84/M85, do not have
            # this) - discovered with getattr and degraded to "not
            # available" exactly as BrokerAdapter's optional methods are.
            accessor = getattr(strategy, "exit_distance", None)
            if accessor is not None:
                bars = bars_for(symbol)
                if bars is not None and not bars.empty:
                    exit_distance = accessor(bars)

        stop_distance: float | None = None
        resting_stop = resting_stops.get(symbol)
        if resting_stop is not None and last_price is not None and last_price > 0:
            stop_distance = (last_price - resting_stop) / last_price

        risk_share: float | None = None
        if budget_dollars > 0:
            symbol_risk = snapshot.risk_by_symbol.get(symbol)
            if symbol_risk is not None:
                # Against the BUDGET, not equity: 1.0 fills the whole cap,
                # and this is allowed to exceed 1.0 - a book at 1.27 of
                # budget is why entries are being refused, and that is
                # exactly what this figure should say.
                risk_share = symbol_risk / budget_dollars

        views.append(
            PositionView(
                symbol=symbol,
                quantity=position.quantity,
                entry_price=entry.price if entry is not None else None,
                last_price=last_price,
                pnl_pct=pnl_pct,
                pnl_r=pnl_r,
                exit_distance=exit_distance,
                stop_distance=stop_distance,
                risk_share=risk_share,
                blockers=_blockers(
                    symbol=symbol,
                    entry=entry,
                    resting_stops=resting_stops,
                    last_price=last_price,
                    settings=settings,
                    now=now,
                ),
            )
        )
    return tuple(views)
