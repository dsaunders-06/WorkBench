"""Bridges SignalEvent (from StrategyEngine, M3) to OMS.submit_order (M6) -
the connector that makes strategy signals actually become pending-signoff
orders. Not itself a spec-named module; a necessary piece the M9 wiring
needs, since nothing else in the system turns a strategy signal into an
order candidate.

This is where signal->order *policy* lives, deliberately kept out of OMS
(which stays a pure mechanism: "submit this order"). Two rules matter most,
both added in M11 after a deployed strategy produced ~75k blotter rows:

* Idempotence. Strategies re-emit a signal on every tick for as long as the
  condition holds, so an unguarded bridge queues a duplicate order per tick.
  A symbol with an order already awaiting sign-off, or already holding the
  position the signal is asking for, produces nothing further.
* Long-only by default. A "sell" closes an existing holding (sized to what is
  actually held, via OMS.submit_exit_order) and is otherwise dropped, rather
  than opening a short in a symbol the account never owned. Set
  allow_short_selling to opt into the old behaviour.

Win-rate/win-loss-ratio inputs to sizing come from `EdgeEstimator` (M35),
which measures each strategy on its own closed trades. The documented
defaults - 0.55 and 1.5 - are still what a strategy sizes on until it has
`edge_min_trades` of its own history, because Kelly reacts violently to a
small sample.

`existing_returns` carries real per-symbol return series (M33), built from
the same warm-started aggregator as the candidate's own. It was an empty
dict behind a comment calling that a documented simplification, which left
the correlated-cluster cap with nothing to correlate against and
PortfolioRiskChecker computing VaR and ES for a book it believed was empty.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol, cast

import pandas as pd

from qat.config import Settings
from qat.data.bars import MultiSymbolAggregator
from qat.data.broker.adapter import Position
from qat.data.earnings import EarningsCalendar, NullEarningsCalendar
from qat.data.features import compute_atr
from qat.domain.bus import EventBus
from qat.domain.events import (
    EntryPriceCorrectedEvent,
    MarketDataEvent,
    OrderFilledEvent,
    SignalEvent,
)
from qat.domain.oms.oms import OMS
from qat.domain.performance.edge import ClosedTradeSource, EdgeEstimator
from qat.domain.risk_engine.engine import OrderCandidate

logger = logging.getLogger(__name__)

_ENTRIES_FILENAME = "open_position_entries.json"
# A recorded entry price within this of what the broker charged is the same
# price. Relative rather than absolute, for the reason M59 gives: a book holding
# WFC at 87 and GS at 1,040 cannot share an absolute epsilon.
_ENTRY_PRICE_TOLERANCE = 1e-4


class _LotStore(Protocol):
    """The slice of the trade ledger this bridge needs to rebuild entry lots.

    Narrower than passing TradeLedger itself: the bridge already takes the
    ledger as a ClosedTradeSource for sizing, and that protocol is about closed
    trades. Restoring lots is a different question and gets its own shape.
    """

    def open_lots(self, symbol: str | None = None) -> list[Any]: ...

    def restore_open_lot(
        self,
        symbol: str,
        quantity: float,
        price: float,
        stop_price: float | None,
        strategy: str | None,
        opened_at: datetime,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class _Entry:
    opened_at: datetime
    price: float
    stop_price: float | None
    # The profit target the entry went in with (M33). Re-arming restored only
    # the stop, because this was the one level nothing recorded - so six
    # positions came back with downside protection and no way to bank a gain.
    target_price: float | None = None
    # Which strategy opened it (M49). The promotion gate counts closed trades
    # PER STRATEGY, so a lot restored without this would rebuild the trade and
    # still not count towards anything.
    strategy: str | None = None


def _returns_by_ts(bars: pd.DataFrame) -> pd.Series:
    """Close-to-close returns indexed by TIMESTAMP, not bar number.

    Correlating two symbols on a positional index compares AAPL's fifth bar to
    MSFT's fifth bar, which are the same day only if both have exactly the same
    history - true right after a warm start and not true after a symbol misses
    a tick. A risk rail cannot rest on "usually lines up", so the join key is
    the timestamp and pairs with too little overlap are dropped upstream.
    """
    if len(bars) < 2 or "ts" not in bars or "close" not in bars:
        return pd.Series(dtype=float)
    frame = bars[["ts", "close"]]
    # One row per timestamp, latest wins (M38). A duplicated timestamp reaching
    # PortfolioRiskChecker fails the entire portfolio check, because pandas
    # cannot reindex from a duplicated axis - which refused every order for a
    # full session on 3 August. Guarding at the source as well as at the
    # consumer, because this series is handed to several callers.
    frame = frame[~frame["ts"].duplicated(keep="last")]
    if len(frame) < 2:
        return pd.Series(dtype=float)
    closes = frame["close"].astype(float)
    closes.index = pd.DatetimeIndex(frame["ts"])
    return closes.pct_change().dropna()


def _earnings_distance(calendar: EarningsCalendar, symbol: str) -> int | None:
    """Sessions to the next print, or None if nothing can answer (M57).

    Wrapped rather than called directly so that a calendar which misbehaves
    cannot stop an order being evaluated. The rail this feeds only ever makes a
    position smaller, so losing the answer costs the protection and nothing
    else - whereas raising here would refuse a trade the rules permit.
    """
    try:
        return calendar.trading_days_until(symbol)
    except Exception:  # noqa: BLE001 - an optional rail must never block an order
        logger.debug("Earnings distance unavailable for %s", symbol, exc_info=True)
        return None


def _trading_days_between(start: datetime, end: datetime) -> int:
    """Weekdays elapsed. An approximation of trading days that ignores market
    holidays - which shortens a ten-day hold by at most a day or two a quarter,
    and is not worth a calendar dependency in a churn rail."""
    if end <= start:
        return 0
    days = 0
    cursor = start.date()
    last = end.date()
    while cursor < last:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            days += 1
    return days


_MIN_HISTORY_FOR_SIZING = 2


def _meta_price(meta: dict[str, object], key: str) -> float | None:
    """Reads a price out of SignalEvent.meta, which is an untyped dict any
    strategy can put anything into - so a missing or non-numeric value is
    treated as absent rather than allowed to raise inside the order path."""
    value = meta.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    return None


class SignalToOrderBridge:
    name = "signal-to-order-bridge"

    def __init__(
        self,
        bus: EventBus,
        oms: OMS,
        default_win_rate: float = 0.55,
        default_win_loss_ratio: float = 1.5,
        max_history: int = 250,
        settings: Settings | None = None,
        bar_interval_seconds: float = 60.0,
        trade_ledger: ClosedTradeSource | None = None,
        earnings_calendar: EarningsCalendar | None = None,
        warm_symbols: tuple[str, ...] = (),
    ) -> None:
        self.bus = bus
        self.oms = oms
        self.settings = settings or Settings()
        # Optional by design (M57). Absent, every candidate reports an unknown
        # distance and the event-risk rail abstains - which is the behaviour
        # this bridge had before the rail existed.
        self.earnings_calendar: EarningsCalendar = earnings_calendar or NullEarningsCalendar()
        # What to pre-fetch dates for at startup (M57c). Empty means no warm
        # pass, which is what every test and the null calendar want.
        self._warm_symbols = warm_symbols
        self._warm_task: asyncio.Task[None] | None = None
        self.default_win_rate = default_win_rate
        self.default_win_loss_ratio = default_win_loss_ratio
        # Kept, not just handed to the estimator: startup also has to give the
        # ledger back the open lots it does not persist (M49).
        self.trade_ledger = trade_ledger
        # What the strategy has actually achieved, once it has achieved enough
        # to measure (M35). Without a ledger this returns the defaults for
        # everything, which is exactly the previous behaviour.
        self.edge = EdgeEstimator(
            trade_ledger,
            settings=self.settings,
            default_win_rate=default_win_rate,
            default_win_loss_ratio=default_win_loss_ratio,
        )
        self.max_history = max_history
        # Real OHLC bars, not one-point-per-tick (M14). This is the most
        # load-bearing of the three aggregators in the app: the ATR computed
        # from these bars sets the stop distance, and the stop distance sets
        # the position size.
        self.bars = MultiSymbolAggregator(
            interval_seconds=bar_interval_seconds, max_bars=max_history
        )
        # Churn control state (M31), persisted since M31b. Rebuilt only from
        # live fill events, it was empty after every restart - and the minimum
        # hold and time stop both treat an unknown entry as "never applies", so
        # a restart silently disarmed both rails on everything already held.
        self._entries_path = Path(self.settings.data_dir) / _ENTRIES_FILENAME
        self._entries: dict[str, _Entry] = self._load_entries()
        self._entry_times: list[datetime] = []
        self._time_stopped: set[str] = set()
        self._hold_blocked: set[str] = set()
        self._sweep_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.bus.subscribe(MarketDataEvent, self._on_market_data)
        self.bus.subscribe(SignalEvent, self._on_signal)
        self.bus.subscribe(OrderFilledEvent, self._on_fill)
        self.bus.subscribe(EntryPriceCorrectedEvent, self._on_entry_price_corrected)
        # Before restore_open_lots, or the ledger is rebuilt from the price the
        # order was SIZED against rather than the one it filled at (M65).
        await self.reconcile_entry_prices()
        await self.restore_open_lots()
        await self.replay_missed_exits()
        await self.rearm_protective_stops()
        self._sweep_task = asyncio.create_task(self._sweep_protection())
        self._warm_task = asyncio.create_task(self._warm_earnings())

    async def _warm_earnings(self) -> None:
        """Fill the earnings cache off the event loop, before the bell (M57c).

        The lookup itself is cache-only, so a cold cache silently abstains
        rather than blocking - which is safe but means the rail does nothing
        until something warms it. This is that something: one pass over the
        watchlist, in a thread, so a hundred vendor calls cannot hold up the
        loop that is meanwhile placing orders.

        Failure is logged and dropped. A cold cache costs the protection; a
        raising warm task would cost the session.
        """
        if not self._warm_symbols:
            return
        try:
            fetched = await asyncio.to_thread(self.earnings_calendar.refresh, self._warm_symbols)
        except Exception:  # noqa: BLE001 - diagnostics must not end a session
            logger.warning("Could not warm the earnings calendar", exc_info=True)
            return
        if fetched:
            logger.info(
                "Earnings calendar warmed for %d symbol(s) - trades within %d trading days of a "
                "print are sized at %.0f%%",
                fetched,
                self.settings.earnings_blackout_days,
                self.settings.earnings_event_size_scalar * 100,
            )

    async def replay_missed_exits(self) -> list[str]:
        """Records exits that executed while this application was not running.

        `restore_open_lots` rebuilds lots for what is HELD, which is exactly the
        set that excludes these: a stop that fired while the app was down closed
        its position, so the symbol is gone from the broker and nothing at
        startup would rebuild the lot its exit needs to close against. The
        replayed sell would then find no lot and record nothing - the M49 defect
        surviving inside the M50 fix.

        So the fills are looked at BEFORE they are absorbed, the entry lot is
        rebuilt from the recorded entry, and only then is the exit applied.

        The quantity is not touched for these - `adopt_broker_positions` already
        read the post-exit position list from the broker. That separation is the
        whole difficulty of M50 and it lives in `absorb_broker_fills`; this
        method exists only to make sure the record has something to attach to.
        """
        ledger = self._lot_store()
        # The symbols this app believed it held when it last ran. Without this
        # the query asks about nothing at all: the broker has dropped the closed
        # position and a fresh process adopted a book that never mentioned it,
        # so both of the sets the OMS can build on its own are empty for exactly
        # the symbol whose exit needs recording.
        self.oms.watch_symbols_for_fills(self._entries)
        try:
            missed = await self.oms.missed_fills()
        except Exception:
            logger.exception("Could not check for exits missed while the app was not running")
            return []
        if not missed:
            return []

        if ledger is not None:
            for fill in missed:
                entry = self._entries.get(fill.symbol)
                if fill.side != "sell" or entry is None or ledger.open_lots(fill.symbol):
                    continue
                ledger.restore_open_lot(
                    symbol=fill.symbol,
                    quantity=fill.quantity,
                    price=entry.price,
                    stop_price=entry.stop_price,
                    strategy=entry.strategy or self._sole_deployed_strategy(),
                    opened_at=entry.opened_at,
                )

        absorbed = await self.oms.absorb_broker_fills(record_only=True)
        replayed = sorted({fill.symbol for fill in absorbed})
        if replayed:
            # Counted by side (M81). "These are recorded as closed trades now"
            # was true only of sells, and this method replays buys too - a
            # position opened at the broker while the app was down. Saying it
            # of a buy is checkable against closed_trades.csv and wrong.
            exits = sorted({f.symbol for f in absorbed if f.side == "sell"})
            entries = sorted({f.symbol for f in absorbed if f.side == "buy"})
            parts = []
            if exits:
                parts.append(f"{', '.join(exits)} closed a position and is now a closed trade")
            if entries:
                parts.append(
                    f"{', '.join(entries)} OPENED a position at the broker and now has a lot "
                    "with no stop and no strategy"
                )
            logger.warning(
                "Replayed %d execution(s) that happened while this application was not "
                "running: %s. The position counts were already correct, because startup reads "
                "them from the broker.",
                len(absorbed),
                "; ".join(parts),
            )
        return replayed

    async def reconcile_entry_prices(self) -> list[str]:
        """Corrects a recorded entry price to what the broker actually charged
        (M65).

        `OMS._announce_fill` publishes when an order reaches "filled" OR
        "transmitted", taking `order.filled_price or order.reference_price`. At
        transmit there is no fill price, so it publishes the REFERENCE - and
        `_on_fill` stores that with `setdefault`, so the genuine fill can never
        replace it. Nothing corrected it afterwards either: an entry this app
        transmitted is in `_broker_order_ids`, so `absorb_broker_fills` skips it
        by design.

        Measured on the live book, 8 of 10 positions held a price that differed
        from what was paid - AMD by 141 bps. `restore_open_lots` passes
        `entry.price` as the lot's cost basis, so realised P&L and the
        R-multiple DENOMINATOR were both wrong by that drift, and both feed the
        promotion gate.

        Asks the broker, because the broker is the authority on what was paid
        exactly as it is the authority on what is held. That heals records
        already written rather than only preventing new ones, which matters
        because the eight wrong ones are sitting on disk right now.

        Runs BEFORE `restore_open_lots`, or the ledger would be rebuilt from the
        very number this removes.

        Only the price moves. The stop is the level the risk budget was spent on
        and re-arming reads it; the open date drives the churn rails.
        """
        if not self._entries:
            return []
        try:
            positions = await self.oms.broker.positions()
        except Exception:
            # A wrong price is bad; a price overwritten from a failed read is
            # worse, so this degrades to leaving the record alone.
            logger.exception("Could not read positions to reconcile recorded entry prices")
            return []

        corrected: list[str] = []
        for position in positions:
            entry = self._entries.get(position.symbol)
            if entry is None or not position.avg_price:
                continue
            # A corporate action changes avg_entry_price legitimately - a
            # 2-for-1 split halves it - so correcting to the post-event figure
            # would silently rewrite the basis of a position M60 exists to stop
            # anything touching.
            if self.oms.anomalies.is_quarantined(position.symbol):
                continue
            paid = float(position.avg_price)
            if abs(paid - entry.price) <= _ENTRY_PRICE_TOLERANCE * abs(entry.price):
                continue
            self._entries[position.symbol] = replace(entry, price=paid)
            corrected.append(position.symbol)

        if corrected:
            self._save_entries()
            logger.warning(
                "Corrected the recorded entry price for %s to what the broker charged. The "
                "record held the price the order was SIZED against, not the price it filled "
                "at, so P&L and every R-multiple on these was wrong by that difference.",
                ", ".join(
                    f"{symbol} -> {self._entries[symbol].price:g}" for symbol in sorted(corrected)
                ),
            )
        return corrected

    async def restore_open_lots(self) -> list[str]:
        """Gives the trade ledger back the entry lots it forgot (M49).

        Here for the same reason `rearm_protective_stops` is: this is the only
        component holding both halves. The broker knows what is held and in
        what size; `_entries` knows what each position was opened at and
        against which stop - and the stop is not decoration, it is the
        denominator of every R-multiple the promotion gate reads.

        Runs before the sweep, so a position whose protection is repaired in
        the same startup already has a lot waiting for the eventual exit.

        A position with NO entry record is skipped and named. The broker knows
        its average price but not when it was opened, and a fabricated open
        date would put invented holding periods into the evidence the trial
        exists to produce. Better a visibly missing trade than a quietly wrong
        one - the same rule `rearm_protective_stops` applies to an unknown
        stop.
        """
        ledger = self._lot_store()
        if ledger is None:
            return []
        try:
            positions = await self.oms.broker.positions()
        except Exception:
            logger.exception("Could not read positions to restore the trade ledger's open lots")
            return []

        restored: list[str] = []
        unknown: list[str] = []
        quarantined: list[str] = []
        for position in positions:
            quantity = abs(position.quantity)
            if quantity <= 0:
                continue
            if self.oms.anomalies.is_quarantined(position.symbol):
                quarantined.append(position.symbol)
                continue
            entry = self._entries.get(position.symbol)
            if entry is None:
                unknown.append(position.symbol)
                continue
            if ledger.restore_open_lot(
                symbol=position.symbol,
                quantity=quantity,
                price=entry.price,
                stop_price=entry.stop_price,
                strategy=entry.strategy or self._sole_deployed_strategy(),
                opened_at=entry.opened_at,
            ):
                restored.append(position.symbol)

        if restored:
            logger.info(
                "Restored %d open lot(s) to the trade ledger: %s. Without this a stop firing "
                "on a position opened in an earlier session records no closed trade at all.",
                len(restored),
                ", ".join(sorted(restored)),
            )
        if unknown:
            logger.warning(
                # Says what it knows, not what it predicts (M81). This used to
                # end "produces no closed trade and no P&L", which was a
                # forecast, and `replay_missed_exits` falsified it seconds later
                # in the same startup: a buy absorbed from the broker publishes
                # OrderFilledEvent and the ledger opens a lot for it. The
                # operator was told the exit would vanish; it will not.
                "No entry record for %s, so no lot could be restored HERE. If the position was "
                "opened at the broker rather than by this app, the replay below opens a thin "
                "lot for it - carrying the price paid, but no stop and no strategy, so a trade "
                "closed from it has no R-multiple and no attribution. Otherwise its exit is "
                "absorbed and records no closed trade at all.",
                ", ".join(sorted(unknown)),
            )
        if quarantined:
            # A visibly missing lot rather than a quietly wrong one - the rule
            # this module already applies to an unknown stop. Quantity comes
            # from the broker and basis from `_entries`, so after an external
            # quantity change the lot would be built at the post-event size on
            # the pre-event basis, and nothing would say so.
            logger.warning(
                "No lot restored for quarantined position(s) %s - the entry basis on record "
                "does not match what the broker holds, so a lot built from it would be wrong "
                "by the same factor. These produce no closed trade until corrected.",
                ", ".join(sorted(quarantined)),
            )
        return restored

    async def _is_flat(self, symbol: str) -> bool:
        """Whether the position is actually gone, asked of the broker (M53).

        The broker is the authority on what is held - the lesson M50 paid for
        twice. A sell event says shares left; only the account says whether any
        remain.

        A failed query answers "not flat", which KEEPS the entry record. The
        conservative direction here is to retain: a stale record for a closed
        position is cleaned up by the time stop within a sweep, where a deleted
        record for an open one cannot be recovered at all.
        """
        try:
            positions = await self.oms.broker.positions()
        except Exception:
            logger.exception(
                "Could not confirm whether %s is flat - keeping its entry record", symbol
            )
            return False
        held = next((p.quantity for p in positions if p.symbol == symbol), 0.0)
        return abs(held) < 1e-6

    def _lot_store(self) -> _LotStore | None:
        """The ledger, if it can hold entry lots. A ClosedTradeSource that
        cannot is still perfectly usable for sizing, so its absence is not an
        error - it simply means there is nothing to restore into."""
        ledger = self.trade_ledger
        if ledger is None or not hasattr(ledger, "restore_open_lot"):
            return None
        return cast("_LotStore", ledger)

    def _sole_deployed_strategy(self) -> str | None:
        """The strategy to credit an entry that predates M49's record of one.

        Resolved from what is actually deployed rather than hard-coded, and
        only when there is exactly one candidate - with two running, which
        opened a given position is genuinely unknown and guessing would put a
        fabricated attribution into a per-strategy promotion decision.
        """
        deployed = self.settings.deployed_strategies_tuple
        return deployed[0] if len(deployed) == 1 else None

    def return_series(self, symbols: Iterable[str]) -> dict[str, pd.Series]:
        """The daily return series this bridge feeds the risk engine.

        Public so a screen can be shown the correlation the RAIL measures. The
        Risk Console was correlating its own ~60 intraday tick samples - about
        the last hour - while the cluster cap correlates 60 daily bars, about
        three months. Handing over the same series is what stops the screen and
        the rail describing different quantities.

        Same construction as `_submit_sized` uses, indexed by timestamp rather
        than bar number: correlating two symbols positionally compares AAPL's
        fifth bar to MSFT's fifth, which are the same day only until one misses
        a tick.
        """
        series: dict[str, pd.Series] = {}
        for symbol in symbols:
            returns = _returns_by_ts(self.bars.frame(symbol))
            if not returns.empty:
                series[symbol] = returns
        return series

    def opened_symbols(self) -> set[str]:
        """Positions this app opened, from the persisted entry record.

        Survives a restart, which is the entire point - the in-memory view is
        empty at launch, and launch is exactly when the adoption banner runs.
        """
        return set(self._entries)

    async def rearm_protective_stops(self) -> list[str]:
        """Proposes a stop for every held position that has none (M31d).

        Runs here because this is the only component that holds both halves:
        the OMS knows what the broker is protecting, and `_entries` knows the
        stop each position was SIZED against - which is the level the risk
        budget was spent on, so re-arming anywhere else would protect the
        position at a distance nobody approved.

        A position with no recorded entry stop is left alone and logged. The
        honest options there are a level invented now from an ATR that has
        moved since entry, or nothing; nothing is visible, and an invented
        stop would look identical to a real one on every screen in the app.

        Orders are pending sign-off, not transmitted. The gate holds even for
        an order that only reduces risk.
        """
        try:
            naked = await self.oms.naked_positions()
        except Exception:
            logger.exception("Could not determine which positions are unprotected")
            return []
        if not naked:
            return []

        proposed: list[str] = []
        unknown: list[str] = []
        quarantined: list[str] = []
        for symbol, quantity in naked:
            if self.oms.anomalies.is_quarantined(symbol):
                quarantined.append(symbol)
                continue
            entry = self._entries.get(symbol)
            if entry is None or entry.stop_price is None:
                unknown.append(symbol)
                continue
            await self.oms.submit_protective_stop(
                symbol, abs(quantity), entry.stop_price, entry.target_price
            )
            proposed.append(symbol)

        if proposed:
            logger.warning(
                "Proposed protective stops for %d unprotected position(s): %s. "
                "They are pending sign-off and rest at the broker once approved.",
                len(proposed),
                ", ".join(sorted(proposed)),
            )
        if unknown:
            logger.error(
                "POSITION UNPROTECTED with no recorded entry stop: %s. No stop can be proposed "
                "for these without inventing a level - close them or stop them manually.",
                ", ".join(sorted(unknown)),
            )
        if quarantined:
            # The liquidation guard. The recorded entry stop predates whatever
            # quarantined the position, so re-arming from it after a 4-for-1
            # split rests a sell-stop at roughly four times the new price -
            # which triggers immediately and liquidates at the next open.
            logger.error(
                "POSITION UNPROTECTED and quarantined: %s. The recorded entry stop is from "
                "before the change that quarantined it, so re-arming from it would rest "
                "protection at a level that liquidates. No stop is proposed - protect or "
                "close these manually.",
                ", ".join(sorted(quarantined)),
            )
        return proposed

    async def stop(self) -> None:
        self.bus.unsubscribe(MarketDataEvent, self._on_market_data)
        self.bus.unsubscribe(SignalEvent, self._on_signal)
        self.bus.unsubscribe(OrderFilledEvent, self._on_fill)
        self.bus.unsubscribe(EntryPriceCorrectedEvent, self._on_entry_price_corrected)
        if self._sweep_task is not None:
            self._sweep_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sweep_task
            self._sweep_task = None
        if self._warm_task is not None:
            self._warm_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._warm_task
            self._warm_task = None

    async def _sweep_protection(self) -> None:
        """Re-arms lost protection on an interval, not only at startup (M33e).

        A stop that vanishes at 14:00 is not less urgent than one found at
        launch - it is more so, because nobody is about to restart the app.
        Running the same repair on a timer is what makes the rail work
        unattended.

        The M33d duplicate guard is what makes this safe to run repeatedly: a
        symbol with a protective order already pending gets that one back
        rather than another.
        """
        while True:
            await asyncio.sleep(self.settings.protection_sweep_seconds)
            try:
                await self.rearm_protective_stops()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one bad sweep must not end the rail
                logger.exception("Protection sweep failed; continuing")

    async def _on_fill(self, event: OrderFilledEvent) -> None:
        """Remembers when each position was opened, for the churn rails (M31).

        Tracked here rather than read from the broker because a Position
        carries no entry time, and the risk that matters - how long this has
        been held, and how far it has moved against the stop it was sized on -
        cannot be answered without one.
        """
        if event.side == "buy":
            self._entries.setdefault(
                event.symbol,
                _Entry(
                    opened_at=event.ts,
                    price=event.price,
                    stop_price=event.stop_price,
                    target_price=event.take_profit_price,
                    strategy=event.strategy,
                ),
            )
            self._entry_times.append(event.ts)
        elif await self._is_flat(event.symbol):
            self._entries.pop(event.symbol, None)
            self._time_stopped.discard(event.symbol)
        else:
            # A PARTIAL exit leaves a position behind, and its entry record is
            # the only thing that can protect it (M53). Dropping the record on
            # the first piece of a multi-piece sell left the remainder with no
            # stop to re-arm to, no minimum hold, no time stop, and no way for a
            # later exit to ever become a closed trade - because the entry it
            # would be measured from was gone.
            #
            # On 5 August a CVS stop filled 30 of 47 and the record went with
            # the first 30. It happened to be harmless only because the rest
            # filled seconds later and the position went flat anyway.
            logger.info(
                "%s partially exited - keeping its entry record for the %s that remain",
                event.symbol,
                "shares",
            )
        self._save_entries()

    async def _on_entry_price_corrected(self, event: EntryPriceCorrectedEvent) -> None:
        """Puts the price actually paid into the entry record, mid-session (M70).

        `_on_fill` stores the announced price with `setdefault`, so the genuine
        one could never replace it and the record stayed wrong until the next
        launch healed it. What `reconcile_entry_prices` does at startup, this
        does the moment the broker says what it charged.

        Only the price moves - the same rule, for the same reasons: the stop is
        the level the risk budget was spent on and re-arming reads it, and the
        open date drives the churn rails.
        """
        entry = self._entries.get(event.symbol)
        if entry is None:
            return
        self._entries[event.symbol] = replace(entry, price=event.price)
        self._save_entries()

    def _load_entries(self) -> dict[str, _Entry]:
        """Entry dates for positions this app already holds.

        A missing or unreadable file is not an error - it is a first run, or a
        machine where the previous session never opened anything. It reads as
        "no known entries", which is exactly the pre-M31b behaviour.
        """
        try:
            raw = json.loads(self._entries_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        entries: dict[str, _Entry] = {}
        for symbol, row in raw.items():
            try:
                entries[symbol] = _Entry(
                    opened_at=datetime.fromisoformat(row["opened_at"]),
                    price=float(row["price"]),
                    stop_price=(
                        float(row["stop_price"]) if row.get("stop_price") is not None else None
                    ),
                    # .get, not [...]: every file written before M33 lacks this
                    # key, and a restart that discarded its entry dates over a
                    # missing target would disarm the churn rails to add one.
                    target_price=(
                        float(row["target_price"]) if row.get("target_price") is not None else None
                    ),
                    # Same reasoning for M49's addition. A file written before
                    # it names no strategy, and the fallback is resolved at
                    # restore time from what is actually deployed rather than
                    # guessed here.
                    strategy=row.get("strategy") or None,
                )
            except (KeyError, TypeError, ValueError):
                logger.warning("Ignoring an unreadable entry record for %s", symbol)
        if entries:
            logger.info(
                "Restored entry dates for %d held position(s): %s",
                len(entries),
                ", ".join(sorted(entries)),
            )
        return entries

    def _save_entries(self) -> None:
        """Written on every change rather than at shutdown: a process that is
        killed never gets to run a shutdown hook, and this file exists
        precisely for the restart that was not planned."""
        payload = {
            symbol: {
                "opened_at": entry.opened_at.isoformat(),
                "price": entry.price,
                "stop_price": entry.stop_price,
                "target_price": entry.target_price,
                "strategy": entry.strategy,
            }
            for symbol, entry in self._entries.items()
        }
        try:
            self._entries_path.parent.mkdir(parents=True, exist_ok=True)
            self._entries_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            logger.exception("Could not persist position entry dates")

    async def _on_market_data(self, event: MarketDataEvent) -> None:
        self.bars.add_tick(event.symbol, event.ts, event.price, event.volume)
        await self._check_time_stop(event.symbol, event.price, event.ts)

    async def _check_time_stop(self, symbol: str, price: float, now: datetime) -> None:
        """Forces an exit on a thesis that never resolved (M31).

        Checked on the tick rather than from a timer: the bridge already sees
        every tick, and the broker is only asked for positions on the rare
        occasion the stop actually fires.
        """
        if not self.settings.enforce_time_stop:
            return
        entry = self._entries.get(symbol)
        if entry is None or symbol in self._time_stopped:
            return
        if _trading_days_between(entry.opened_at, now) < self.settings.time_stop_trading_days:
            return

        positions = await self.oms.broker.positions()
        held = next((p.quantity for p in positions if p.symbol == symbol), 0.0)
        if held <= 0:
            self._entries.pop(symbol, None)
            return
        self._time_stopped.add(symbol)
        logger.info(
            "TIME STOP on %s after %d trading days - exiting a thesis that never resolved",
            symbol,
            self.settings.time_stop_trading_days,
        )
        await self.oms.submit_exit_order(symbol, quantity=held, price=price, reason="time_stop")

    async def _on_signal(self, event: SignalEvent) -> None:
        # A strategy re-emits its signal on EVERY tick for as long as its
        # condition holds - a signal is a state, not a one-off instruction. So
        # this must be idempotent: the same signal arriving repeatedly has to
        # produce at most one order, or the blotter fills with duplicates.
        #
        # The pending check is local and free, so it goes first: once a symbol
        # has something awaiting sign-off, subsequent ticks cost nothing and
        # never hit the broker.
        if event.symbol in self.oms.pending_signoff_symbols():
            return

        bars = self.bars.frame(event.symbol)
        if len(bars) < _MIN_HISTORY_FOR_SIZING:
            return  # not enough history to size a stop yet

        price = float(bars["close"].iloc[-1])

        positions = await self.oms.broker.positions()
        held = next(
            (pos.quantity for pos in positions if pos.symbol == event.symbol),
            0.0,
        )

        if event.side == "sell":
            await self._handle_sell(event.symbol, held, price)
            return

        if held > 0:
            return  # already long - re-signalling must not pyramid the position

        # A committed order counts even before it fills (M46). Positions alone
        # miss the window between transmitting an order and the broker
        # reporting the holding, which is where the duplicate MS entry came
        # from.
        if self.oms.has_live_buy(event.symbol):
            return

        await self._submit_entry(event, bars, price, positions)

    def _blocked_by_minimum_hold(self, symbol: str, price: float) -> bool:
        """Whether a SIGNAL-driven exit is too early to act on (M31).

        Only signal-driven exits reach here. The resting broker stop, the
        delever sweep and the kill-switch take other paths, so no protective
        exit can be delayed by this.

        The loss escape is what makes the rail defensible: a minimum hold on
        its own would sit through a broken thesis to save $12 of commission,
        and once the position is down min_holding_loss_escape_r the commission
        is small against the risk still on the table.
        """
        if not self.settings.enforce_min_holding_period:
            return False
        entry = self._entries.get(symbol)
        if entry is None:
            return False  # unknown entry: never trap a position we cannot date

        held_days = _trading_days_between(entry.opened_at, datetime.now(UTC))
        if held_days >= self.settings.min_holding_trading_days:
            return False

        if entry.stop_price is not None and entry.stop_price < entry.price:
            risk = entry.price - entry.stop_price
            loss_r = (entry.price - price) / risk
            if loss_r >= self.settings.min_holding_loss_escape_r:
                logger.info(
                    "%s is %.2fR down after %d trading days - the minimum hold does not "
                    "apply to a thesis this far wrong",
                    symbol,
                    loss_r,
                    held_days,
                )
                return False

        if symbol not in self._hold_blocked:
            self._hold_blocked.add(symbol)
            logger.info(
                "Signal exit on %s held back: %d of %d trading days, and not far enough "
                "down to escape the minimum hold",
                symbol,
                held_days,
                self.settings.min_holding_trading_days,
            )
        return True

    async def _handle_sell(self, symbol: str, held: float, price: float) -> None:
        if held > 0 and self._blocked_by_minimum_hold(symbol, price):
            return
        if held > 0:
            # Close exactly what is held rather than letting the entry sizer
            # invent an unrelated quantity.
            await self.oms.submit_exit_order(symbol, quantity=held, price=price, reason="signal")
            return
        if not self.settings.allow_short_selling:
            return  # long-only: nothing to sell, and opening a short is not wanted
        # Shorting is explicitly enabled, so treat this as a new position.
        bars = self.bars.frame(symbol)
        if not bars.empty:
            positions = await self.oms.broker.positions()
            await self._submit_short(symbol, bars, price, positions)

    def _entries_this_week(self, now: datetime) -> int:
        cutoff = now - timedelta(days=7)
        self._entry_times = [ts for ts in self._entry_times if ts >= cutoff]
        return len(self._entry_times)

    async def _submit_entry(
        self, event: SignalEvent, bars: pd.DataFrame, price: float, positions: list[Position]
    ) -> None:
        # Turnover budget (M31). Ten concurrent positions turned over weekly
        # costs 6.2% of a $100k account in commission before a single losing
        # trade; this bounds the rate at which that can happen. Entries only -
        # a budget that blocked exits would be a rail against de-risking.
        taken = self._entries_this_week(datetime.now(UTC))
        if taken >= self.settings.max_entries_per_week:
            logger.info(
                "Turnover budget reached: %d entries in the last seven days, limit %d - "
                "%s not opened",
                taken,
                self.settings.max_entries_per_week,
                event.symbol,
            )
            return
        # A strategy that has done the work of proposing a stop and target
        # (Swing, Breakout) gets those honoured, both for sizing and for the
        # bracket attached at the broker. A strategy that has not falls back to
        # the risk engine's own ATR stop.
        await self._submit_sized(
            event.symbol,
            event.side,
            bars,
            price,
            positions,
            strategy=event.strategy,
            stop_price=_meta_price(event.meta, "stop_price"),
            take_profit_price=_meta_price(event.meta, "target_price"),
        )

    def _days_to_earnings(self, symbol: str) -> int | None:
        return _earnings_distance(self.earnings_calendar, symbol)

    def _earnings_date(self, symbol: str) -> date | None:
        """The announcement date, for the record rather than for the rail (M41).

        Same guarding as the distance: cache-only underneath, and a calendar
        that misbehaves yields None rather than stopping an order.
        """
        try:
            return self.earnings_calendar.next_earnings(symbol)
        except Exception:  # noqa: BLE001 - a diagnostic must never block an order
            logger.debug("Earnings date unavailable for %s", symbol, exc_info=True)
            return None

    async def _submit_short(
        self,
        symbol: str,
        bars: pd.DataFrame,
        price: float,
        positions: list[Position],
        strategy: str | None = None,
    ) -> None:
        await self._submit_sized(symbol, "sell", bars, price, positions, strategy=strategy)

    async def _submit_sized(
        self,
        symbol: str,
        side: Literal["buy", "sell"],
        bars: pd.DataFrame,
        price: float,
        positions: list[Position],
        strategy: str | None = None,
        stop_price: float | None = None,
        take_profit_price: float | None = None,
    ) -> None:
        atr_series = compute_atr(bars["high"], bars["low"], bars["close"])
        last_atr = atr_series.iloc[-1]
        atr = 0.0 if pd.isna(last_atr) else float(last_atr)
        if atr <= 0:
            return  # can't size a stop without a valid ATR yet

        edge = self.edge.estimate(strategy)
        candidate = OrderCandidate(
            symbol=symbol,
            side=side,
            price=price,
            atr=atr,
            win_rate=edge.win_rate,
            win_loss_ratio=edge.win_loss_ratio,
            candidate_returns=_returns_by_ts(bars),
            strategy=strategy,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            days_to_earnings=self._days_to_earnings(symbol),
            earnings_date=self._earnings_date(symbol),
        )

        # A broker blip must REFUSE the signal, not throw it (M54).
        #
        # This call sat outside every guard. On 6 August Alpaca returned HTTP
        # 500 for ninety seconds, the exception escaped through the event bus,
        # and the signal vanished - no order, no refusal, no journal entry,
        # nothing on any screen. Only the stack trace said it had ever existed.
        #
        # M38 made exactly this argument about the risk evaluation inside
        # OMS.submit_order and wrapped it there; this fetch is upstream of that
        # guard and was missed. The neighbouring paths already got it right -
        # `_current_positions` falls back to its cache, the equity poll logs and
        # continues - so the rail that threw was the odd one out.
        #
        # A rail that refuses is visible and auditable. A rail that throws is
        # neither, and the trial is built on the record rather than on the fill.
        try:
            account = await self.oms.broker.account()
        except Exception as exc:  # noqa: BLE001 - surfaced as a refusal, never swallowed
            logger.warning(
                "Could not read the account to size %s (%s: %s) - the signal is refused and "
                "recorded rather than lost. It will be reconsidered on the next tick.",
                symbol,
                type(exc).__name__,
                exc,
            )
            self.oms.record_unsized_signal(
                symbol, side, strategy, f"account unavailable: {type(exc).__name__}"
            )
            return
        existing_weights = {pos.symbol: pos.quantity * pos.avg_price for pos in positions}
        # Real return series for what is already held (M33). This was an empty
        # dict with a comment calling it a documented simplification, and it
        # made two rails inert rather than lenient: the correlated-cluster cap
        # has nothing to correlate against, and PortfolioRiskChecker computes
        # portfolio VaR and ES from a book it believes is empty.
        #
        # The warm start already seeds this aggregator with 300 daily bars per
        # watchlist symbol, so the history exists - it was simply never handed
        # over. Same source as the candidate's own series, so the two are
        # measured the same way.
        existing_returns: dict[str, pd.Series] = {}
        for position in positions:
            if position.symbol == symbol or abs(position.quantity) <= 0:
                continue
            series = _returns_by_ts(self.bars.frame(position.symbol))
            if not series.empty:
                existing_returns[position.symbol] = series

        await self.oms.submit_order(
            candidate, account.net_liquidation, existing_weights, existing_returns
        )
