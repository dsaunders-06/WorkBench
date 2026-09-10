"""Order Management System (spec §I): order lifecycle enforcement and the
mandatory human sign-off gate. Order/OrderStatus/BrokerAdapter/MockBroker
all exist since M1 - this builds the state machine that actually enforces
new -> pending_signoff -> transmitted -> filled/cancelled/rejected.

The safety-critical invariant: submit_order() runs the risk pipeline and,
if approved, creates an Order with status="pending_signoff" - it NEVER
calls broker.place_order(). Only sign_off(order_id, operator) (an explicit
call representing the human action) transitions to "transmitted" and calls
the broker. See tests/safety/test_no_order_without_signoff.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

import pandas as pd

from qat.config import Settings
from qat.data.broker.adapter import (
    BrokerAdapter,
    BrokerFill,
    Order,
    is_protective_leg,
    spendable_from,
)
from qat.data.broker.mock_broker import new_order_id
from qat.domain.bus import EventBus
from qat.domain.decision_journal import DecisionJournal, JournalEntry
from qat.domain.events import (
    BrokerOrderIdResolvedEvent,
    EntryPriceCorrectedEvent,
    ExitPriceCorrectedEvent,
    OrderFilledEvent,
    OrderPendingSignoffEvent,
    OrderRejectedEvent,
)
from qat.domain.oms.anomaly import PositionAnomalyStore
from qat.domain.oms.resting_order_anomaly import RestingOrderAnomalyStore
from qat.domain.oms.resting_orders import (
    WORKING_STATUSES,
    SymbolOrderDivergence,
    unjustified_resting_risk,
)
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

logger = logging.getLogger(__name__)

# Share counts are floats on the wire, so an exact == 0 comparison is not safe.
# The same 1e-6 the reconciliation and cancel paths already use.
_POSITION_EPSILON = 1e-6


@dataclass(frozen=True, slots=True)
class _AbsorbedFill:
    """How much of one broker order this app has already counted (M53).

    Quantity, not just a timestamp: a partially filling order reports the same
    id repeatedly with a growing `filled_qty`, so "have I seen this id" is the
    wrong question and answering it cost a session on 5 August.
    """

    filled_at: datetime
    quantity: float
    price: float
    # False only for a record written before M53, which stored a timestamp and
    # no quantity. See _absorbed_from_json for why that must read as "finished".
    quantity_known: bool = True


def _absorbed_from_json(entry: object) -> _AbsorbedFill:
    """One `absorbed` entry, in either the M50 or the M53 shape.

    M50 wrote a bare timestamp per order id and no quantity. Such a record is
    loaded as ALREADY FINISHED, and the direction matters more than it looks.

    The alternative - treating the unknown quantity as zero absorbed - makes the
    whole of that order eligible to be counted a second time. On the file
    written on 5 August that is a 47-share CVS stop of which 30 were already
    recorded: re-absorbing it would drive the tracked quantity to -47, record a
    duplicate closed trade, and trip the kill-switch. That is M46 again, arriving
    through the migration of the fix for M50.

    So the worst this costs is one legacy fill under-recorded, in a file that is
    at most a few days old and holds only orders the previous build already
    absorbed. Under-recording is correctable by hand; double-subtracting halts a
    session.
    """
    if isinstance(entry, str):
        return _AbsorbedFill(
            filled_at=datetime.fromisoformat(entry),
            quantity=0.0,
            price=0.0,
            quantity_known=False,
        )
    if isinstance(entry, dict):
        quantity = float(entry.get("quantity") or 0.0)
        return _AbsorbedFill(
            filled_at=datetime.fromisoformat(str(entry["filled_at"])),
            quantity=quantity,
            price=float(entry.get("price") or 0.0),
            # A dict with no flag was written by the build that persisted a
            # migrated record without one. Zero absorbed is exactly that case,
            # and it has to keep reading as "finished" rather than as "none of
            # it counted yet".
            quantity_known=bool(entry.get("quantity_known", quantity > 0.0)),
        )
    raise ValueError("unrecognised absorbed-fill record")


_FILL_STATE_FILENAME = "absorbed_fills.json"
# How long an absorbed fill's id is remembered. Only needs to outlast the gap
# How old a restored watermark can be before the replay it implies is worth a
# warning. Two hours: long enough that a normal overnight gap does not fire it
# on a market that closes at 16:00 and opens at 10:00, short enough that the
# four-and-a-half-hour replay of 24 August would have announced itself.
_WIDE_REPLAY_WARNING = timedelta(hours=2)
# between the watermark and now - days, not weeks - but the file is tiny and a
# generous window costs nothing against the risk of recording a trade twice.
_ABSORBED_ID_RETENTION = timedelta(days=30)
# A resting stop is "the same level" within a RELATIVE tolerance. An absolute
# epsilon cannot serve a book holding both WFC at 87 and GS at 1,040 - one
# loose enough to absorb rounding on the latter is blind to a real move on the
# former. At 1e-4 this absorbs cent-level rounding on every price in the book.
_STOP_LEVEL_TOLERANCE = 1e-4
# The same relative test, for the same reason, applied to what an order paid
# or received against what its announcement claimed - an entry (M70) or an
# exit (M71). Matches the tolerance `reconcile_entry_prices` heals to at
# startup, so the live correction and the startup one cannot disagree about
# whether a price needs correcting.
_ANNOUNCED_PRICE_TOLERANCE = 1e-4


class OMS:
    def __init__(
        self,
        broker: BrokerAdapter,
        risk_engine: RiskEngine,
        kill_switch: KillSwitch,
        max_order_pct_of_cash: float | None = None,
        symbol_allow_list: set[str] | None = None,
        entry_allow_list: set[str] | None = None,
        bus: EventBus | None = None,
        journal: DecisionJournal | None = None,
        settings: Settings | None = None,
        corporate_actions: object | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.broker = broker
        # The fourth injectable clock in the trading path, and the fourth for
        # the same reason (W2 step 6). `_load_fill_state` falls back to "now"
        # when there is no state file, which is every replay given its own
        # scratch data_dir: the harness then asks the broker for fills since the
        # WALL clock, every simulated 2026 fill is older than that, and the
        # absorb sweep records nothing while reporting success.
        #
        # Assigned before `_load_fill_state` runs below, or `_now` reads an
        # attribute that does not exist yet. Defaults to the wall clock, so live
        # behaviour is unchanged.
        self._clock = clock
        # Every order decision is journalled, in every execution mode (M20).
        # Until then only the autonomous executor wrote here, so a
        # recommend-mode session - the default - left no record of why an
        # order was proposed or refused. Optional so an OMS built without one
        # (every existing test) behaves exactly as before.
        self.journal = journal
        self.risk_engine = risk_engine
        self.kill_switch = kill_switch
        # From settings unless a caller pins it. It was a bare default argument
        # of 50_000.0 until 24 August 2026, with no comment and no way to change
        # it without editing this file - the only risk rail in the system with
        # no recorded reasoning, and the only one that was an absolute sum
        # rather than a fraction. `Settings.max_order_pct_of_cash` carries both.
        self.max_order_pct_of_cash = (
            max_order_pct_of_cash
            if max_order_pct_of_cash is not None
            else (settings or Settings()).max_order_pct_of_cash
        )
        self.symbol_allow_list = symbol_allow_list
        # Entries only (M61). `symbol_allow_list` above gates exits too, so it
        # cannot be used to narrow what may be OPENED without also making
        # everything else unsellable - see Settings.entry_allow_list.
        self.entry_allow_list = entry_allow_list
        self.bus = bus
        self._orders: dict[str, Order] = {}
        self._filled_quantities: dict[str, float] = {}
        self._adopted_baseline: dict[str, float] = {}
        # Stops this session attached to its own entries, kept so the portfolio
        # governor can measure aggregate risk-at-stop without re-querying open
        # orders from the broker on every candidate.
        self._position_stops: dict[str, float] = {}
        # Symbols that have already spent their one-check reprieve while a
        # replacement protective order sits awaiting sign-off. Cleared the
        # moment a stop is seen resting again. See `verify_position_stops`.
        self._protection_grace_used: set[str] = set()
        # Watermark for absorbing broker-side executions (M34), now surviving a
        # restart (M50).
        #
        # It started at construction, which reads as "a fill before this process
        # existed is already in the adopted baseline" - true of the QUANTITY and
        # false of the RECORD. Adoption re-baselines what is held; it says
        # nothing about what closed. So a stop firing while the app was down
        # left no closed trade at all, and the app restarted three times during
        # the 4 August session alone.
        #
        # `_absorbed_fills` is what makes replaying safe: the watermark alone
        # cannot say whether a fill on the boundary was already recorded, and
        # guessing either way loses a trade or records it twice.
        self.settings = settings
        self._fill_state_path = (
            Path(settings.data_dir) / _FILL_STATE_FILENAME if settings is not None else None
        )
        self._absorbed_fills: dict[str, _AbsorbedFill] = {}
        # When an order THIS app sent was first seen partially filled (M70).
        # In memory only, and deliberately: it exists to widen one query window
        # while a fill is outstanding, and an order still filling across a
        # restart is re-read from the broker by adoption anyway.
        self._own_partial_fill_stamps: dict[str, datetime] = {}
        self._fill_watch_hint: set[str] = set()
        self._last_fill_scan = self._load_fill_state()
        # Why a position ended, keyed by symbol until the fill arrives. After
        # the fact the price alone cannot separate a time stop from a signal.
        self._exit_reasons: dict[str, str] = {}
        # Broker-assigned ids for orders THIS app transmitted (M46).
        #
        # `_orders` is keyed by the app's own id, but the adapter overwrites
        # order.order_id with the broker's on transmit. So a fill arriving from
        # the broker carries an id that is never a key of `_orders`, and the
        # "did this app send it" test in absorb_broker_fills matched nothing:
        # every entry fill was absorbed as if it were a resting protective
        # order firing, counted a second time, and reconciliation answered the
        # doubled quantity with the kill-switch. That is what halted the
        # session on 4 August.
        self._broker_order_ids: set[str] = set()
        # Serialises sign-off so the "re-check cash against the CURRENT
        # balance" step below is actually a check. Concurrently signed orders
        # each fetch the balance before either has spent it, so both see the
        # same cash and both pass - the documented failure mode where several
        # individually-affordable orders collectively overdraw the account.
        # Bulk human sign-off and unattended execution both hit this path.
        self._signoff_lock = asyncio.Lock()
        # Positions in a state the ordinary path must not treat as ordinary
        # (M39/M43). Persisted, because adoption reseeds tracked quantities
        # from the broker at every launch and would otherwise launder the very
        # divergence this records.
        self.anomalies = PositionAnomalyStore(settings.data_dir if settings is not None else None)
        # Separate from `anomalies`, and separate ON PURPOSE (M141, item 23).
        # `PositionAnomalyStore.explains` suppresses the reconciliation halt;
        # this store has no such method, so quarantining a flat symbol here
        # cannot grant it immunity from the halt that caught the real mismatch
        # on 24 August.
        self.resting_order_anomalies = RestingOrderAnomalyStore(
            settings.data_dir if settings is not None else None
        )
        # The corporate-action monitor, when one is running (M39). Optional,
        # so an OMS built without it refuses exactly what it refused before.
        self.corporate_actions = corporate_actions
        # Explained divergences are logged once per session, not once per poll.
        self._explained_logged: set[str] = set()
        # Same idea, for the resting-order scan (I5, final review). With
        # cancelling off - the default - an unresolved divergence is detected
        # again on every poll, and logging it every time turned one incident
        # into ~78 identical ERROR blocks across a trading day, drowning
        # `session_check.ps1`'s output exactly when the rail fires. Keyed by
        # (symbol, side) rather than symbol alone, because the two sides net
        # independently in `unjustified_resting_risk`. The value is the excess
        # last logged, so a CHANGE (not just a re-detection) still gets a line.
        self._resting_order_logged: dict[tuple[str, str], float] = {}
        # Order ids this OMS has handed to a broker. Guards against a second
        # transmission independently of the status field - see `_sign_off_locked`.
        self._transmitted: set[str] = set()
        # Item 56 / Task 3: `place_order`'s bounded permId wait (Task 2) can
        # still lose to a slow TWS acknowledgement. `IBAdapter._adopt_from_broker`
        # learns the resolved id moments later regardless - modify and cancel
        # need it - and publishes BrokerOrderIdResolvedEvent for exactly that
        # case. Subscribing here, rather than the adapter importing OMS and
        # calling it directly, follows the direction this dependency already
        # runs: the adapter holds the bus and publishes domain events on it
        # (see KillSwitchEvent), and consumers subscribe from their own
        # constructor. Optional so an OMS built without a bus (every test
        # predating this) behaves exactly as before.
        if self.bus is not None:
            self.bus.subscribe(BrokerOrderIdResolvedEvent, self._on_broker_order_id_resolved)
            # 3 September / Task 5b: the adapter learns a rejection is final
            # (`IBAdapter._on_ib_error`) and publishes rather than reaching in
            # here directly - same reasoning as BrokerOrderIdResolvedEvent
            # just above. Optional bus, same as every other subscription in
            # this constructor.
            self.bus.subscribe(OrderRejectedEvent, self._on_order_rejected)

    def entry_permitted(self, symbol: str) -> str | None:
        """Why an entry in `symbol` would be refused by the allow lists, or None.

        Pure: no logging, no state, no order. Extracted so the symbol verdict
        can report the identical decision without proposing anything, rather
        than growing a second copy of a two-line rule - which is exactly how
        `minimum_hold_status`'s two callers had drifted before it was pulled
        out, with nothing pinning them together.

        The symbol allow list is checked first because it is the broader rule:
        it governs HOLDING as well as entering, so it is the refusal worth
        naming when both would fire.

        An EMPTY set is not None. None permits everything; an empty set permits
        nothing, which is what a cleared entry allow list means.
        """
        if self.symbol_allow_list is not None and symbol not in self.symbol_allow_list:
            return "symbol not on the allow list"
        if self.entry_allow_list is not None and symbol not in self.entry_allow_list:
            return "symbol not on the entry allow list (machinery test in progress)"
        return None

    async def submit_order(
        self,
        candidate: OrderCandidate,
        equity: float,
        existing_weights: dict[str, float],
        existing_returns: dict[str, pd.Series],
        sector_by_symbol: dict[str, str] | None = None,
    ) -> Order:
        refusal = self.entry_permitted(candidate.symbol)
        if refusal is not None:
            return self._new_rejected_order(candidate, 0.0, refusal)

        # Ahead of the kill-switch check so the refusal names the anomaly
        # rather than a generic halt, and ahead of the risk pipeline because
        # sizing against a quantity known to be wrong is wrong however
        # carefully it is done.
        anomaly = self.anomalies.get(candidate.symbol)
        if anomaly is not None:
            return self._new_rejected_order(candidate, 0.0, f"position anomaly - {anomaly.reason}")

        # Beside the position anomaly for the same reason, and separately
        # because the two stores answer different questions (M141, item 23). A
        # symbol carrying resting orders the book cannot justify may be about
        # to acquire a position nobody asked for; sizing a new entry into it
        # sizes against a quantity with a known expiry.
        resting_anomaly = self.resting_order_anomalies.get(candidate.symbol)
        if resting_anomaly is not None:
            return self._new_rejected_order(
                candidate, 0.0, f"resting order anomaly - {resting_anomaly.reason}"
            )

        # Beside the anomaly check for the same reason (M39): a pending split
        # means the share count and the per-share price are both about to
        # change, so an entry sized now is sized against a number with a known
        # expiry. Refusing MORE than before is what keeps this inside the
        # freeze - the argument M60 was accepted under. Entries only; the exit
        # path below says nothing about pending actions, because a rail whose
        # effect is "the account may not de-risk" is a broken rail.
        pending = self._pending_action(candidate.symbol)
        if pending is not None:
            return self._new_rejected_order(
                candidate,
                0.0,
                f"corporate action pending - {pending} changes the size basis, so an entry "
                f"now would be sized against a price and share count about to move",
            )

        if self.kill_switch.tripped:
            return self._new_rejected_order(candidate, 0.0, "kill-switch tripped")

        # OMS owns the broker reference, so it fetches cash itself rather than
        # trusting every caller to pass it - a no-leverage rule that a caller
        # can bypass by omission is not a rule (spec M12).
        account = await self.broker.account()
        # Portfolio state is fetched here, by the component that owns the broker
        # reference, for the same reason cash is (spec M12/M15): a cap a caller
        # can bypass by not passing an argument is not a cap. Pending orders are
        # included because an order awaiting sign-off is committed exposure.
        # An unexpected failure here becomes a REJECTED ORDER, not an
        # exception (M38).
        #
        # On 3 August every one of 1,438 signals raised inside the portfolio
        # check and the exception propagated out through the event bus. The
        # bus logged "EventBus handler failed" and moved on, so the session
        # produced no orders, no refusals, no journal entries and nothing on
        # any screen. A full trading day looked from the Dashboard exactly
        # like a day with no setups.
        #
        # A rail that refuses is visible and auditable. A rail that throws is
        # neither, and this is the boundary where that distinction has to be
        # enforced: submit_order already answers every other failure with a
        # rejected order carrying a reason.
        try:
            decision = self.risk_engine.evaluate_order(
                candidate,
                equity,
                existing_weights,
                existing_returns,
                sector_by_symbol,
                available_cash=account.cash,
                positions=await self.broker.positions(),
                position_stops=self.position_stops(),
                pending_orders=self.pending_orders(),
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as a refusal, never swallowed
            logger.exception(
                "Risk evaluation FAILED for %s - refusing the order rather than "
                "letting the signal disappear",
                candidate.symbol,
            )
            return self._new_rejected_order(
                candidate, 0.0, f"risk evaluation failed: {type(exc).__name__}: {exc}"
            )
        if not decision.approved or decision.final_shares <= 0:
            return self._new_rejected_order(
                candidate, 0.0, decision.reason or "risk engine rejected"
            )

        # Whole shares only (M31a). Every buy leaves here with a protective
        # bracket, and Alpaca refuses a fractional quantity that carries one:
        #   {"code":42210000,"message":"fractional orders must be simple orders"}
        # The sizer works in continuous shares - 1% of equity over a stop
        # distance almost never lands on an integer - so before this, every
        # auto-signed order was refused by the broker and nothing could fill.
        #
        # Floored rather than rounded: rounding up would take slightly more
        # risk than the sizer approved, and the whole point of the sizing chain
        # is that the number it produces is a ceiling.
        shares = float(int(decision.final_shares))
        if shares < 1:
            return self._new_rejected_order(
                candidate,
                0.0,
                f"sized at {decision.final_shares:.4g} shares, below one whole share - "
                "a fractional quantity cannot carry a protective bracket",
            )

        # TRIMMED, not refused (operator decision, 24 August 2026). The
        # concentration cap beside this one has trimmed since M31c for the
        # reason recorded at that setting - a limit that refuses makes the
        # trade disappear, a limit that trims makes it the size the limit
        # believes in. This rail was the last one still saying no rather than
        # less, and on 24 August it refused the first real ASX entry signal
        # this system ever produced, 48 times in a row.
        #
        # Trimming can only ever REDUCE risk: the stop is per-share and
        # unchanged, so fewer shares is proportionally less at stake than the
        # sizer approved. The audit trail keeps the sizer's own figure, so a
        # trimmed order and its risk decision will legitimately differ - which
        # is why the trim is logged rather than applied quietly.
        # FAIL CLOSED on an unknown cash balance. The cap is a fraction of cash,
        # so without cash there is no cap - and silently skipping a risk limit
        # because its input is missing is the failure this codebase already has
        # a test named for (test_cash_check_fails_closed_without_a_price).
        if account.cash is None:
            return self._new_rejected_order(
                candidate,
                0.0,
                "the broker did not report cash, so the per-order cap "
                "(a share of available cash) cannot be computed",
            )

        # ⚠️ SPENDABLE, not raw cash (item 22). `min_cash_reserve` is money this
        # application has already declared unspendable, and the no-leverage rail
        # already subtracts it (`engine.py:242`) while the Balances panel already
        # shows `spendable_cash(...)`. A cap on raw cash was a THIRD basis for
        # one question - the shape that hurt `trading_date` and
        # `minimum_hold_status` before each was extracted.
        #
        # The arithmetic is immaterial at today's $1 reserve: one share on a
        # 100-share order. That is not the argument. As cash approaches the
        # reserve the two diverge without limit, and a cap on RAW cash can
        # authorise an order the no-leverage rail then refuses - one rail
        # permitting what another forbids. The reserve exists to be raised.
        # ⚠️ `spendable_from`, not `AccountBalances.spendable_cash`: the broker
        # returns an `AccountSummary`, which does not carry that method. My own
        # test fixture returned the wrong type and hid this - mypy caught it.
        #
        # A missing `settings` means no configured reserve, so the cap falls back
        # to raw cash. That is the OLD behaviour, not a new hazard: the only
        # callers without settings are tests, and `min_cash_reserve` is `gt=0` in
        # production so a real run always has one.
        reserve = self.settings.min_cash_reserve if self.settings is not None else 0.0
        spendable = spendable_from(account.cash, reserve)
        if spendable is None:
            return self._new_rejected_order(
                candidate,
                0.0,
                "the broker did not report cash, so the per-order cap "
                "(a share of spendable cash) cannot be computed",
            )
        cap = self.max_order_pct_of_cash * spendable
        notional = shares * candidate.price
        if notional > cap:
            trimmed = float(int(cap / candidate.price)) if candidate.price > 0 else 0.0
            if trimmed < 1:
                return self._new_rejected_order(
                    candidate,
                    0.0,
                    f"the per-order cap of {self.max_order_pct_of_cash:.1%} of SPENDABLE "
                    f"cash ({cap:,.0f}) does not cover one share at "
                    f"{candidate.price:,.2f}",
                )
            logger.info(
                "%s trimmed from %g to %g shares by the per-order cap of %.1f%% of "
                "SPENDABLE cash (%.0f of %.0f): notional %.0f -> %.0f. The risk decision in the "
                "audit trail keeps the sizer's own figure, so the two will differ for "
                "this order.",
                candidate.symbol,
                shares,
                trimmed,
                self.max_order_pct_of_cash * 100,
                cap,
                spendable,
                notional,
                trimmed * candidate.price,
            )
            shares = trimmed

        # The broker's own ceiling, applied AFTER the cash cap so the log reads
        # in the order the trims happened. Not queryable through the API, so it
        # is a configured belief that Error 383 audits rather than a fact.
        ceiling = self.settings.broker_max_order_shares if self.settings is not None else None
        if ceiling is not None and shares > ceiling:
            logger.info(
                "%s trimmed from %g to %g shares by the broker's order-size ceiling "
                "(broker_max_order_shares). Above it the broker STAGES the order for "
                "manual confirmation rather than transmitting it, which on 3 September "
                "booked a position the exchange never took.",
                candidate.symbol,
                shares,
                float(ceiling),
            )
            shares = float(ceiling)

        order = self._new_pending_order(
            candidate.symbol,
            candidate.side,
            shares,
            candidate.price,
            candidate.strategy,
            # The strategy's stop when it proposed one, otherwise the ATR stop
            # the sizer used. Either way the position reaches the broker with a
            # bracket rather than naked.
            stop_price=candidate.stop_price or decision.stop_price,
            take_profit_price=candidate.take_profit_price,
            earnings_date=candidate.earnings_date,
        )
        await self._announce_pending(order)
        return order

    async def _release_protective_legs(self, symbol: str, quantity: float, reason: str) -> bool:
        """Cancel this symbol's resting protective legs. False means do not sell.

        ⚠️ CANCEL FIRST, NOT SELL FIRST, and the two failure modes are why -
        they are not symmetric:

        * cancel first and the sell then fails -> the position is UNPROTECTED,
          which `verify_position_stops` detects and `signal_bridge` RE-ARMS on
          its own ("Proposed protective stops for N unprotected position(s)").
          Self-healing, on a position you meant to hold.
        * sell first and the cancel then fails -> the legs are ORPHANED,
          detected by a rail that explicitly does not cancel anything, and if
          one fills you own an unintended SHORT with no bound.

        ⚠️ A PARTIAL exit RELEASES ITS LEGS TOO, reversed 9 September 2026.
        This used to leave them alone, reasoning that the de-lever sweep trims a
        position which still needs protecting. That is true of the intent and
        false of the result: the legs keep the PRE-TRIM size, so a 100-share
        bracket ends up guarding a 60-share holding, and a stop firing then
        sells 100 against 60 held and puts the account SHORT 40 - in a falling
        market, which is when stops fire. The sweep trims EVERY position at
        once, so one breach left the whole book over-covered.

        ⚠️ WHY CANCEL RATHER THAN RESIZE, and it is the same asymmetry again:
        `naked_positions` reports a position with NO stop resting and is BLIND
        to one that is merely the wrong SIZE. Resizing in place fails into a
        state nothing detects; cancelling fails into one that
        `verify_position_stops` shouts about and `rearm_protective_stops` heals
        by itself, at `abs(quantity)` - the current holding - off the recorded
        entry stop. Cancelling fails into the state the system can see.

        ⚠️ The remainder is therefore briefly unprotected, bounded by
        `protection_sweep_seconds`. That is a real cost, accepted deliberately,
        and it is the same window this method already accepts when a full exit
        is cancelled and then fails.

        ⚠️ Only protective legs, per `is_protective_leg`. A working BUY on the
        symbol is an intruder and is left strictly alone: cancelling one
        silently is how an account came to hold 4x the intended position on
        24 August (M139).
        """
        source = getattr(self.broker, "open_orders", None)
        cancel = getattr(self.broker, "cancel_order", None)
        if source is None or cancel is None:
            # An adapter that models neither cannot be orphaning anything.
            return True
        try:
            working = await source()
        except Exception:
            logger.exception(
                "Could not read open orders before exiting %s - refusing the exit rather "
                "than selling into legs that may be resting",
                symbol,
            )
            return False

        legs = [o for o in working if o.symbol == symbol and is_protective_leg(o)]
        if not legs:
            return True

        held = await self._broker_quantity(symbol)
        if held is not None and abs(quantity) + 1e-9 < abs(held):
            logger.warning(
                "Exit on %s is PARTIAL (%g of %g held), so its %d protective leg(s) are "
                "RELEASED like any other exit - they carry the pre-trim size and would "
                "guard %g shares against a %g holding. The remainder is left unprotected "
                "on purpose: that state is what `naked_positions` can see, and "
                "`rearm_protective_stops` re-arms it at the reduced size.",
                symbol,
                quantity,
                held,
                len(legs),
                held,
                abs(held) - abs(quantity),
            )

        for leg in legs:
            try:
                await cancel(leg.order_id)
            except Exception:
                logger.exception("Could not cancel protective leg %s on %s", leg.order_id, symbol)

        # ⚠️ RE-READ. The cancel's own response is not evidence: on 19 August
        # one reported PendingCancel while being rejected outright (10147).
        try:
            still = [o for o in await source() if o.symbol == symbol and is_protective_leg(o)]
        except Exception:
            logger.exception("Could not verify the leg cancellation on %s", symbol)
            return False
        if still:
            logger.error(
                "%d protective leg(s) on %s are STILL RESTING after a cancel was sent "
                "(%s). The exit is refused: the position keeps its protection, and "
                "selling into a resting leg is what orphaned A2M.AX.",
                len(still),
                symbol,
                ", ".join(o.order_id for o in still),
            )
            return False
        logger.info(
            "Cancelled %d protective leg(s) on %s before exiting (%s)",
            len(legs),
            symbol,
            reason,
        )
        return True

    async def submit_exit_order(
        self,
        symbol: str,
        quantity: float,
        price: float,
        reason: str = "signal",
        *,
        legs_already_released: bool = False,
    ) -> Order:
        """Closes an existing position at exactly `quantity` shares (spec §I).

        Separate from submit_order() rather than a flag on it, because the two
        size orders completely differently - an entry is sized by the risk
        engine, an exit is sized by what is actually held. Like submit_order(),
        this only ever creates a pending_signoff order and NEVER calls
        broker.place_order(): sign_off() remains the sole path to the broker.
        """
        if self.symbol_allow_list is not None and symbol not in self.symbol_allow_list:
            return self._new_rejected_order_for(symbol, "sell", 0.0)

        anomaly = self.anomalies.get(symbol)
        if anomaly is not None:
            if reason == "delever":
                # A trim sized against a quantity known to be wrong is the trim
                # doing the damage. Exits are allowed below; trims are not.
                return self._new_rejected_order_for(
                    symbol,
                    "sell",
                    0.0,
                    f"position anomaly - de-lever trim refused ({anomaly.reason})",
                )
            held = await self._broker_quantity(symbol)
            if held is None:
                # Refusing an exit is normally the M56c defect. Here the
                # alternative is selling a quantity this app has already
                # recorded as untrustworthy, and the refusal is a rejected
                # order carrying a reason rather than a silent gate.
                return self._new_rejected_order_for(
                    symbol,
                    "sell",
                    0.0,
                    f"position anomaly - could not read the broker to size the exit "
                    f"({anomaly.reason})",
                )
            logger.warning(
                "Exit on quarantined %s sized from the broker at %g, not the tracked %g",
                symbol,
                held,
                quantity,
            )
            quantity = held

        # ⚠️ CANCEL THE PROTECTIVE LEGS BEFORE SELLING, and refuse the exit if
        # they will not go. On 4 September the escaped-hold rule exited A2M.AX
        # through this method, the sell filled, and BOTH OCA legs stayed at full
        # size on a flat position - 9,636 shares of resting SELL with a stop
        # about 4% under the last. A naked short waiting to happen. The
        # resting-order rail found it and named the ids; the operator cancelled
        # them by hand, because that rail says "The ORDERS ARE NOT CANCELLED by
        # this."
        #
        # `PositionCloser` (M163) already did this properly for the OPERATOR's
        # close. The autonomous paths - the time stop and the signal exit - came
        # straight here and walked away, and those are the exits that run when
        # nobody is watching the scan.
        # ⚠️ `PositionCloser` passes True: it has ALREADY cancelled the legs,
        # re-read to prove they are gone, and holds recovery logic to re-place
        # the bracket if this sell then fails (M163). Repeating the work here
        # let two layers disagree about the same broker state and refused six
        # manual closes outright. The operator path owns its own release; every
        # other caller gets the default.
        if not legs_already_released and not await self._release_protective_legs(
            symbol, quantity, reason
        ):
            return self._new_rejected_order_for(
                symbol,
                "sell",
                0.0,
                "protective legs are still resting at the broker and could not be "
                "cancelled - selling into them is the double-fill that turns a "
                "protected long into a short, so the exit is refused and the "
                "position stays protected",
            )

        self._exit_reasons[symbol] = reason
        decision = self.risk_engine.evaluate_exit(symbol, quantity, price)
        if not decision.approved or decision.final_shares <= 0:
            return self._new_rejected_order_for(symbol, "sell", 0.0)

        # NO per-order cap on an exit, deliberately (24 August 2026).
        #
        # This used to refuse a sell above the cap, which meant a position
        # larger than the cap COULD NOT BE CLOSED BY THIS APPLICATION AT ALL -
        # and the half-Kelly sizer asks for roughly 12.5% of equity, well above
        # a fixed $50,000 at this account size. The rail that blocked the entry
        # would have trapped the position had one ever been opened another way.
        #
        # Nor is it trimmed. A trimmed exit leaves a residual the operator
        # believes is closed, which is worse than either alternative. The
        # autonomy gate already draws this exact line - "risk-reducing orders
        # are not gated on appetite limits" - and a notional cap is an appetite
        # limit. An exit is not an expression of appetite.

        order = self._new_pending_order(symbol, "sell", decision.final_shares, price)
        await self._announce_pending(order)
        return order

    async def _announce_pending(self, order: Order) -> None:
        """Publishes OrderPendingSignoffEvent when a bus is wired. Optional so
        an OMS built without one (every test predating M13) still works."""
        if self.bus is None or order.status != "pending_signoff":
            return
        await self.bus.publish(
            OrderPendingSignoffEvent(
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                strategy=order.strategy,
            )
        )

    # Committed exposure the broker has not yet reported as a position. Both,
    # because in AUTO mode `pending_signoff` lasts milliseconds (item 58).
    _COMMITTED_STATUSES = ("pending_signoff", "transmitted")

    def awaiting_signoff(self) -> list[Order]:
        """Orders that have not yet been decided on.

        ⚠️ **Narrower than `pending_orders`, and the difference is load-bearing
        (item 58).** They answer different questions and must not be merged
        again: this one is "has a decision been made", `pending_orders` is "what
        exposure is committed".

        The duplicate guard on protective stops needs THIS one. A protective
        order that has been signed off is `transmitted` and RESTING at the
        broker - it does not fill until it triggers - so treating it as pending
        turns a duplicate guard into a one-shot LATCH, and a position whose stop
        was later cancelled could never be re-armed. `tests/safety/
        test_protective_stop_rearm.py` caught exactly that when the two were
        briefly the same call: *"The guard is about DUPLICATES, not a one-shot
        latch."*
        """
        return [order for order in self._orders.values() if order.status == "pending_signoff"]

    def pending_orders(self) -> list[Order]:
        """Orders awaiting a decision - committed exposure that has not filled.

        ⚠️ **`transmitted` counts, and its absence is item 58.** This matched
        only `pending_signoff`. In auto mode the executor signs off in
        milliseconds, so between sign-off and the broker reporting the position
        an order was in NEITHER `held` NOR here - invisible to the position cap.

        On 26 August two entries went out 173ms apart, both sized against a book
        of nine, and the book reached ELEVEN against a cap of 10. Because
        `governor.py:304` refuses at `>=`, returning to ten was still AT the cap,
        which cost the 27 August session 1,036 refusals and every entry it might
        have made.

        The docstring above is unchanged - it already said "committed exposure
        that has not filled", and the code simply did less than it claimed.

        ⚠️ `filled` stays OUT deliberately. It is already in the broker's
        positions, and `ExposureSnapshot` guards the COUNT with
        `if order.symbol not in held` but adds `gross` and `risk_at_stop_dollars`
        unconditionally - so counting a filled order here would double its
        exposure. A `transmitted` order that has filled without the OMS seeing
        the event is over-counted until reconciliation catches up, which refuses
        MORE rather than less and is the safe direction to be wrong in.
        """
        return [
            order for order in self._orders.values() if order.status in self._COMMITTED_STATUSES
        ]

    def pending_signoff_symbols(self) -> set[str]:
        """Symbols that already have an order awaiting the operator's decision -
        used by SignalToOrderBridge to avoid queueing duplicates while a
        strategy keeps re-emitting the same signal every tick."""
        return {
            order.symbol for order in self._orders.values() if order.status == "pending_signoff"
        }

    def _new_pending_order(
        self,
        symbol: str,
        side: Literal["buy", "sell"],
        quantity: float,
        reference_price: float | None = None,
        strategy: str | None = None,
        stop_price: float | None = None,
        take_profit_price: float | None = None,
        earnings_date: date | None = None,
    ) -> Order:
        order = Order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_id=new_order_id(),
            status="pending_signoff",
            reference_price=reference_price,
            strategy=strategy,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            earnings_date=earnings_date,
        )
        self._orders[order.order_id] = order
        self._record(order, "proposed", "awaiting sign-off")
        return order

    async def sign_off(self, order_id: str, operator: str) -> Order:
        """The only path that can move an order past pending sign-off - an
        explicit, operator-attributed action (spec §I).

        `operator` is a human in "recommend" mode and the autonomous executor's
        own identifier in "auto" mode. The distinction is recorded, never
        elided: the audit trail must show which orders a person approved.
        """
        async with self._signoff_lock:
            return await self._sign_off_locked(order_id, operator)

    async def _sign_off_locked(self, order_id: str, operator: str) -> Order:
        order = self._orders[order_id]
        if order.status != "pending_signoff":
            raise ValueError(f"Order {order_id} is not pending sign-off (status={order.status})")

        # ⚠️ INDEPENDENT OF STATUS, and that is the whole point (24 August 2026).
        #
        # The status check above is the primary guard and it was sufficient
        # right up until the moment an adapter failed to set a status. IBKR's
        # working states were missing from `_IB_STATUS_MAP`, so a transmitted
        # order came back still reading `pending_signoff`, sailed through that
        # check, and was transmitted again every sixty seconds by the retry
        # sweep - four times, for two symbols, leaving 4x the intended position
        # at the broker.
        #
        # This set does not depend on any adapter getting a mapping right. An
        # order this OMS has already handed to a broker is never handed over
        # again, whatever its status field happens to say. Belt and braces
        # deliberately: the cost of a false positive here is a refused
        # duplicate; the cost of a false negative is what happened on the 24th.
        if order_id in self._transmitted:
            raise ValueError(
                f"Order {order_id} has already been transmitted to the broker - "
                "refusing to transmit it a second time"
            )

        if self.kill_switch.tripped:
            order.status = "rejected"
            logger.info("Sign-off blocked by kill-switch: order=%s operator=%s", order_id, operator)
            # Journalled, like every other refusal in this method (item 43).
            # This one alone returned without recording, so an order refused
            # here appeared on the Blotter with an EMPTY reason column and no
            # journal row at all - the Blotter reads reasons from the journal
            # by order id. Observed on 25 August: order ab701dff, RHC.AX,
            # refused during the kill-switch window and absent from the journal
            # entirely, while three other kill-switch refusals the same window
            # - raised in `submit_order`, which does record - were all there.
            self._record(
                order, "rejected", f"kill-switch tripped: {self.kill_switch.reason}", operator
            )
            return order

        # ⚠️ RE-READ THE POSITION. A protective order is sized when PROPOSED and
        # transmitted when SIGNED OFF, and the holding can change in between.
        #
        # MEASURED 9 September 2026, and it was a near-miss rather than a loss.
        # A signal exit on SEK.AX filled in TEN partial executions over 28
        # seconds. `rearm_protective_stops` read the position at TWELVE seconds,
        # when 2,030 of 2,978 had filled, and proposed a protective sell of the
        # 948 it thought remained. Twenty-eight seconds later SEK was FLAT -
        # `IB.positions()` returned nine positions with no SEK among them - and
        # that order was retried every sixty seconds against a position that did
        # not exist. Signed off, it is a SHORT created by the rail whose entire
        # purpose is preventing one. What blocked it was the kill switch,
        # tripped seconds earlier on an unrelated error: luck, not design.
        #
        # Same shape as the resting-order cancel loop's TOCTOU guard, and for
        # the same reason - re-read immediately before committing, because the
        # snapshot the decision was made on is already stale.
        #
        # ⚠️ REFUSE, DO NOT RESIZE. The buy branch below says why: "silently
        # changing a quantity a human just approved would defeat the point of
        # the approval." A refusal is cheap because the protection sweep
        # proposes a correctly-sized replacement within
        # `protection_sweep_seconds`; a silent resize transmits a quantity
        # nobody approved.
        #
        # ⚠️ ONLY A SHORTFALL REFUSES. A protective order SMALLER than the
        # holding under-protects, which is a real problem and a far less urgent
        # one than selling shares that are not there - and refusing it would
        # leave the position with no protection at all.
        if order.is_protective_stop:
            held = await self._broker_quantity(order.symbol)
            if held is None:
                # Fails CLOSED, and `None` is not zero: `_broker_quantity`
                # keeps that distinction precisely so this branch can.
                order.status = "rejected"
                logger.warning(
                    "Sign-off blocked - the broker could not be read to confirm %s is still "
                    "held, and a protective sell cannot be sized against a position that "
                    "cannot be seen: order=%s operator=%s",
                    order.symbol,
                    order_id,
                    operator,
                )
                self._record(
                    order,
                    "rejected",
                    f"broker unreadable - cannot confirm {order.symbol} is still held",
                    operator,
                )
                return order
            if held <= _POSITION_EPSILON:
                order.status = "rejected"
                logger.warning(
                    "Sign-off blocked - %s is FLAT at the broker, so this protective sell of "
                    "%g would open a SHORT. It was sized when proposed and the position "
                    "closed before sign-off: order=%s operator=%s",
                    order.symbol,
                    order.quantity,
                    order_id,
                    operator,
                )
                self._record(
                    order,
                    "rejected",
                    f"{order.symbol} is flat at the broker - a protective sell would short it",
                    operator,
                )
                return order
            if held + _POSITION_EPSILON < order.quantity:
                order.status = "rejected"
                logger.warning(
                    "Sign-off blocked - %s has shrunk to %g since this protective order was "
                    "sized at %g, so it would be short by %g. The protection sweep will "
                    "propose one at the current size: order=%s operator=%s",
                    order.symbol,
                    held,
                    order.quantity,
                    order.quantity - held,
                    order_id,
                    operator,
                )
                self._record(
                    order,
                    "rejected",
                    f"{order.symbol} shrank to {held:g} since this was sized at "
                    f"{order.quantity:g} - refusing rather than resizing",
                    operator,
                )
                return order

        # Re-check cash against the CURRENT balance, not the balance at
        # submission (spec M12). This is load-bearing rather than belt-and-
        # braces: with bulk sign-off, ten orders each individually affordable
        # when submitted can collectively overdraw the account when approved
        # together. Reject rather than resize - silently changing a quantity a
        # human just approved would defeat the point of the approval.
        if order.side == "buy":
            account = await self.broker.account()
            price = await self._costing_price(order)
            if price is None:
                # Fails CLOSED. An unknown price used to fall back to 0.0, which
                # made cost 0 and let this check pass unconditionally - and
                # AlpacaAdapter raises on get_market_data by design, so with a
                # real Alpaca account that was every buy, not a rare outage.
                # A no-leverage guarantee that evaporates when a quote is
                # missing is not a guarantee.
                order.status = "rejected"
                logger.warning(
                    "Sign-off blocked - no price available to cost the order: "
                    "order=%s operator=%s symbol=%s",
                    order_id,
                    operator,
                    order.symbol,
                )
                self._record(order, "rejected", "no price available to cost the order", operator)
                return order
            cost = order.quantity * price
            spendable = account.cash - self.risk_engine.settings.min_cash_reserve
            if cost > spendable:
                order.status = "rejected"
                logger.info(
                    "Sign-off blocked - insufficient cash: order=%s operator=%s "
                    "cost=%.2f spendable=%.2f",
                    order_id,
                    operator,
                    cost,
                    spendable,
                )
                self._record(
                    order,
                    "rejected",
                    f"insufficient cash: cost {cost:.2f} > spendable {spendable:.2f}",
                    operator,
                )
                return order

        # The broker decides whether this is transmitted, not us (M31a).
        #
        # `order.status = "transmitted"` used to run BEFORE the call, so when
        # place_order raised, the order kept a status saying it was live at the
        # broker. Three orders showed as transmitted in the blotter on 31 July
        # while Alpaca held nothing at all, and reconciliation could not catch
        # it: that compares FILLED quantities, and an order that never reached
        # the broker has filled nothing on either side, so both agree.
        try:
            filled = await self.broker.place_order(order)
        except Exception as exc:  # noqa: BLE001 - the broker's refusal is the answer
            order.status = "rejected"
            self._orders[order_id] = order
            logger.exception(
                "Broker refused order %s (%s %s x%s)",
                order_id,
                order.side,
                order.symbol,
                order.quantity,
            )
            self._record(order, "rejected", f"broker refused: {exc}", operator)
            return order

        # No status assignment here at all: the returned order carries the
        # broker's own, mapped by the adapter (Alpaca's accepted/new/pending
        # become "transmitted", a same-second fill becomes "filled"). Setting
        # it ourselves would overwrite the one authoritative answer with a
        # guess - which is what the pre-call assignment was.
        # Recorded the instant the broker accepted it, before anything that
        # could fail - a duplicate guard that is only written on the happy path
        # is not a guard.
        self._transmitted.add(order_id)
        self._orders[order_id] = filled
        # ⚠️ ALIASED under the broker's id as well (item 56, measured live on
        # 31 August). `IBAdapter.place_order` returns an order RE-IDENTIFIED
        # with the permId, and storing it under the original key alone left the
        # dict key and the object's own `order_id` disagreeing. `pending_orders`
        # hands out the VALUE, so every caller that then looked it up by
        # `order.order_id` - `_consider` does exactly that - raised KeyError
        # once a minute and stalled autonomous execution.
        #
        # ALIAS, never move: the journal, the blotter and the decision record
        # all hold the id the order was created with, and re-keying would trade
        # one KeyError for another.
        if filled.order_id and str(filled.order_id) != order_id:
            self._orders[str(filled.order_id)] = filled
        # Recorded BEFORE anything else, so an absorb running concurrently can
        # never see this fill as foreign.
        if filled.order_id:
            self._broker_order_ids.add(str(filled.order_id))

        # A protective stop is RESTING, not filled (M31d). Counting it as a
        # sell would halve the tracked quantity against a broker that still
        # holds the whole position, and reconciliation would read that as a
        # discrepancy and trip the kill-switch on the very order sent to make
        # the book safer. It records protection, and nothing else.
        if filled.is_protective_stop:
            if filled.stop_price:
                self._position_stops[filled.symbol] = float(filled.stop_price)
            self._record(filled, "signed_off", "protective stop resting at the broker", operator)
            # The target goes in the line too (M33c). This is the audit trail
            # for "is the position actually protected", and printing only the
            # stop could not distinguish an OCO whose target leg rested from
            # one where the broker accepted the order and dropped it.
            logger.info(
                "Protective %s resting: order=%s operator=%s symbol=%s qty=%s stop=%.2f%s",
                "OCO" if filled.take_profit_price else "stop",
                order_id,
                operator,
                filled.symbol,
                filled.quantity,
                filled.stop_price or 0.0,
                f" target={filled.take_profit_price:.2f}" if filled.take_profit_price else "",
            )
            return filled

        signed_qty = filled.quantity if filled.side == "buy" else -filled.quantity
        self._filled_quantities[filled.symbol] = (
            self._filled_quantities.get(filled.symbol, 0.0) + signed_qty
        )

        if filled.side == "buy" and filled.stop_price:
            self._position_stops[filled.symbol] = float(filled.stop_price)
        elif filled.side == "sell" and abs(self._filled_quantities[filled.symbol]) < 1e-6:
            # Position closed - its stop went with it at the broker, so keeping
            # it here would overstate protection on a symbol no longer held.
            self._position_stops.pop(filled.symbol, None)
        self._record(filled, "signed_off", "transmitted to the broker", operator)
        logger.info(
            # ⚠️ BOTH IDS (item 56, 31 August). This line carried only the app's
            # own id, so every transmit back to 1 August logged a UUID and the
            # broker-native permId - the id every execution, modify and cancel
            # later arrives under - appeared nowhere. Reading a session could
            # not join a transmit to its executions. `broker=` is the app's id
            # again when the permId has not arrived yet, which is itself worth
            # seeing rather than hiding.
            "Order signed off and transmitted: order=%s broker=%s operator=%s symbol=%s qty=%s",
            order_id,
            filled.order_id,
            operator,
            filled.symbol,
            filled.quantity,
        )
        await self._announce_fill(filled, operator)
        return filled

    async def _announce_fill(self, order: Order, operator: str) -> None:
        """Publishes OrderFilledEvent so performance measurement has a source
        of realised outcomes. Optional bus, same as _announce_pending."""
        if self.bus is None or order.status not in ("filled", "transmitted"):
            return
        price = order.filled_price or order.reference_price
        if not price:
            return
        await self.bus.publish(
            OrderFilledEvent(
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                price=float(price),
                strategy=order.strategy,
                stop_price=order.stop_price,
                take_profit_price=order.take_profit_price,
                operator=operator,
                reference_price=order.reference_price,
                earnings_at_entry=order.earnings_date,
                exit_reason=(
                    self._exit_reasons.pop(order.symbol, "signal") if order.side == "sell" else None
                ),
                # THE SEVENTH WALL-CLOCK DEPENDENCY, and it disabled three rails
                # in every replay ever run (W2). Omitted, `ts` takes `Event`'s
                # default of `datetime.now(UTC)` - correct in live, where the
                # fill genuinely just happened, and wrong in a replay by however
                # far the simulated clock is from today.
                #
                # `SignalToOrderBridge._on_fill` stamps `entry.opened_at` from
                # this event, and `_trading_days_between(opened_at, now)`
                # returns zero when `now` precedes it. So THE TIME STOP, THE
                # MINIMUM HOLDING PERIOD AND THE WEEKLY CHURN CAP could never
                # fire: the first ASX run opened seven positions in September
                # 2025, held them across two hundred and fifty sessions, and
                # closed nothing at all.
                #
                # `_now` is the wall clock unless a clock was injected, so live
                # behaviour is unchanged. The absorb path below has always
                # passed its own `ts` for the same reason (M50).
                ts=self._now(),
            )
        )

    async def _costing_price(self, order: Order) -> float | None:
        """Best available price for costing an order, or None if there is none.

        Preference order, most to least current: the order's own price, a live
        broker quote, then the price the order was sized against at submission.
        The last of these is what makes this workable for an execution-only
        adapter (Alpaca) that never serves quotes - it is slightly stale, but a
        slightly stale price is a real constraint, whereas no price at all is
        not a constraint of any kind.
        """
        if order.limit_price:
            return float(order.limit_price)
        if order.filled_price:
            return float(order.filled_price)

        try:
            quote = await self.broker.get_market_data(order.symbol)
        except Exception:  # noqa: BLE001 - an adapter without quotes is expected
            logger.debug("Broker cannot quote %s; using the submission price", order.symbol)
        else:
            live = float(quote.get("ask") or quote.get("last") or 0.0)
            if live > 0:
                return live

        if order.reference_price and order.reference_price > 0:
            return float(order.reference_price)
        return None

    async def reject_order(self, order_id: str, operator: str, reason: str) -> Order:
        order = self._orders[order_id]
        if order.status not in ("new", "pending_signoff"):
            raise ValueError(f"Order {order_id} cannot be rejected from status={order.status}")
        order.status = "rejected"
        logger.info("Order rejected: order=%s operator=%s reason=%s", order_id, operator, reason)
        self._record(order, "rejected_by_operator", reason, operator)
        return order

    async def cancel_order(self, order_id: str) -> Order:
        order = self._orders[order_id]
        if order.status == "transmitted":
            cancelled = await self.broker.cancel_order(order_id)
            self._orders[order_id] = cancelled
            return cancelled
        if order.status in ("filled", "cancelled", "rejected"):
            return order
        order.status = "cancelled"
        return order

    def get_order(self, order_id: str) -> Order:
        return self._orders[order_id]

    def orders(self) -> list[Order]:
        """Every order ONCE, whatever it happens to be keyed under.

        ⚠️ `_orders` deliberately ALIASES a transmitted order under the
        broker's permId as well as its own id (item 56, and the three tests in
        `test_order_id_survives_rekeying.py` forbid removing that). So
        `.values()` yields the SAME OBJECT TWICE.

        **Lookup wants the alias; enumeration must not see it.** Measured live
        on 10 September 2026: the Order Blotter showed one COH.AX entry as two
        rows reading `2 of 2 orders`, identical in every column - because both
        rows render `order.order_id`, which is the permId on both, so the
        duplicate does not look like one.

        ⚠️ Not only cosmetic. `position_closer.preview_protective_orders`
        filters this list to transmitted stops for the close-position
        confirmation dialog, and its docstring states the invariant the alias
        breaks: *"this normally returns zero or one order, not two"*. The
        aliasing is in `_sign_off_locked` and sign_off is the sole path to the
        broker, so protective stops are aliased exactly as entries are.

        Deduplicated on the order's OWN id, not on object identity: the id is
        what every caller means by "the same order". Insertion order is kept,
        because the blotter's rows are ordered by it.
        """
        seen: set[str] = set()
        unique: list[Order] = []
        for order in self._orders.values():
            key = str(order.order_id)
            if key in seen:
                continue
            seen.add(key)
            unique.append(order)
        return unique

    def register_broker_order_id(self, order_id: str) -> None:
        """Record a broker identifier learned AFTER transmit (item 56).

        `place_order` waits briefly for the permId, and a slow acknowledgement
        can outlast that wait. The adapter learns it either way - it needs it
        for modify and cancel to resolve - so this is how that knowledge
        reaches the one check that decides whether a fill is our own.
        """
        if order_id:
            self._broker_order_ids.add(str(order_id))

    async def _on_broker_order_id_resolved(self, event: BrokerOrderIdResolvedEvent) -> None:
        self.register_broker_order_id(event.order_id)

    async def _on_order_rejected(self, event: OrderRejectedEvent) -> None:
        """Gives back an optimistic sign-off booking once a rejection proves
        the order is dead (3 September 2026) - see `OrderRejectedEvent`.

        ⚠️ Reverses BOOKED minus EXECUTED, never the full booked size. A
        partial fill that is then rejected or cancelled leaves a real
        position behind; reversing all of it would invent a phantom SHORT -
        the same defect this exists to fix, in the other direction, and the
        one the reverted Task 3 produced.

        Two guards fail closed rather than guess:
        - `executed_quantity is None` means the adapter did not report it -
          a different claim from zero. Reversing on a guess could
          manufacture a short; leaving the booking in place is what let
          reconciliation catch 3 September in four minutes, and it still can
          here.
        - A symbol this OMS never booked is left alone. There is nothing to
          give back, and writing one in would book a phantom position rather
          than correct one.
        """
        if event.executed_quantity is None:
            logger.warning(
                "OrderRejectedEvent for %s (order=%s) carries no executed quantity - "
                "leaving the booking of %.2f in place for reconciliation to settle: %s",
                event.symbol,
                event.order_id,
                event.booked_quantity,
                event.reason,
            )
            return
        if event.symbol not in self._filled_quantities:
            logger.warning(
                "OrderRejectedEvent for %s (order=%s) but this OMS has nothing booked "
                "for that symbol - nothing to reverse: %s",
                event.symbol,
                event.order_id,
                event.reason,
            )
            return
        remaining = event.booked_quantity - event.executed_quantity
        # ⚠️ Signed exactly as `signed_qty` signs the booking above: a sell
        # books NEGATIVE, so an unsigned `-= remaining` would drive a rejected
        # sell further short and double the phantom rather than remove it.
        # A2M's exit on 4 September was refused five times; under an unsigned
        # reversal each refusal would have deepened the error it was correcting.
        signed_remaining = remaining if event.side == "buy" else -remaining
        self._filled_quantities[event.symbol] -= signed_remaining
        logger.info(
            "Reversed %.2f of the booking for %s (order=%s) after rejection: %s. "
            "%.2f executed and stays booked.",
            remaining,
            event.symbol,
            event.order_id,
            event.reason,
            event.executed_quantity,
        )

    async def adopt_broker_positions(self) -> dict[str, float]:
        """Seeds the position baseline from whatever the account already holds.

        Without this, reconciliation compares an OMS that has filled nothing
        against an account that already holds positions - from an earlier
        session, another application, or a manual trade - and reads a perfectly
        healthy account as a discrepancy. That would trip the kill-switch on
        startup every time, which trains an operator to ignore the one signal
        that means "my view of the account cannot be trusted".

        Adoption is deliberately explicit and logged rather than implicit in
        the first reconciliation call: silently absorbing an unexpected
        position is exactly the event reconciliation exists to catch, so it
        must happen once, at a known point, on the record.

        **Stops are learned from the broker here, not assumed away (M31d).**
        `_position_stops` is in-memory and starts empty, so before this every
        restart re-adopted its own positions as unprotected and the governor
        counted each at full value: six holdings worth $27.8k read as ~28%
        risk-at-stop against a 5% cap, which rejects every new buy before
        sizing runs. The account is the only thing that actually knows what is
        resting, and it was already being asked - `resting_stops` existed and
        was used solely to verify.

        It also un-blinds `verify_position_stops`, which iterates
        `_position_stops` and therefore had nothing to check after a restart -
        precisely when a bracket expired overnight is most likely to have gone
        missing.

        A position with no resting stop is still absent from the record, so
        the conservative rule is unchanged. The difference is that it is now
        reached by evidence rather than by assumption.
        """
        adopted = {pos.symbol: pos.quantity for pos in await self.broker.positions()}
        self._report_anomalies_that_moved_again(adopted)
        self._filled_quantities = dict(adopted)
        self._adopted_baseline = dict(adopted)
        if not adopted:
            logger.info("No pre-existing broker positions to adopt")
            return adopted

        resting = await self._resting_stops()
        self._position_stops = {
            symbol: stop for symbol, stop in resting.items() if symbol in adopted
        }
        naked = sorted(set(adopted) - set(self._position_stops))

        # WARNING, not INFO, and the consequence is stated. Adoption is
        # routine; adoption silently consuming the entire risk-at-stop budget
        # is not, and the INFO line said only that it had happened.
        logger.warning(
            # "%d carries a stop" read as "11 carries a stop" on 10 August, and
            # left the reader to subtract for the number that actually matters -
            # how many are NAKED, which is what consumes the risk budget at full
            # value. Both figures are stated now (M82).
            "Adopted %d pre-existing broker position(s) as the reconciliation baseline: %s. "
            "%d of %d carry a stop resting at the broker, which is what their risk is measured "
            "to; %d carry none and count their full value against the aggregate cap.",
            len(adopted),
            ", ".join(f"{sym} {qty:g}" for sym, qty in sorted(adopted.items())),
            len(self._position_stops),
            len(adopted),
            len(naked),
        )
        quarantined = [a.symbol for a in self.anomalies.active() if a.symbol in adopted]
        if quarantined:
            logger.warning(
                "%d adopted position(s) are QUARANTINED: %s. New entries, de-lever trims and "
                "protection re-arming are refused for these, and their records are still "
                "uncorrected - a declaration explains a difference, it does not repair it.",
                len(quarantined),
                ", ".join(sorted(quarantined)),
            )
        if naked:
            # Its own line, at ERROR, and worded as the position being exposed
            # rather than as bookkeeping. This is the state that both loses
            # real money on a gap and silently exhausts the risk budget.
            logger.error(
                "POSITION UNPROTECTED: %s held with no stop resting at the broker. Each counts "
                "its full value against the aggregate risk-at-stop cap, so new entries may be "
                "refused until they are stopped or closed.",
                ", ".join(naked),
            )
        return adopted

    def _report_anomalies_that_moved_again(self, adopted: dict[str, float]) -> None:
        """A quarantined position whose quantity has changed AGAIN since it was
        declared (M39).

        Checked here, before `_filled_quantities` is overwritten, because
        adoption is precisely what destroys the evidence: it reseeds tracked
        quantities wholesale from the broker, so a second change would
        otherwise be absorbed into the new baseline and never seen. The
        declaration no longer explains what is held, so reconciliation will
        halt on it - which is correct, and the operator should know why before
        it happens rather than afterwards.
        """
        moved_again = [
            anomaly
            for anomaly in self.anomalies.active()
            if abs(adopted.get(anomaly.symbol, 0.0) - anomaly.broker_quantity) > 1e-6
        ]
        if not moved_again:
            return
        logger.error(
            "QUARANTINED POSITION MOVED AGAIN since it was declared: %s. The declaration no "
            "longer explains what the broker holds, so reconciliation will halt on these "
            "until they are re-declared or cleared.",
            ", ".join(
                f"{anomaly.symbol} declared={anomaly.broker_quantity:g} "
                f"now={adopted.get(anomaly.symbol, 0.0):g}"
                for anomaly in sorted(moved_again, key=lambda a: a.symbol)
            ),
        )

    async def _resting_stops(self) -> dict[str, float]:
        """What the broker says is actually working, or nothing it can vouch for.

        An adapter without the capability must not be read as "no stops rest
        anywhere" - that is indistinguishable from a genuinely naked book and
        would be acted on as if it were one.
        """
        source = getattr(self.broker, "resting_stops", None)
        if source is None:
            return {}
        try:
            resting: dict[str, float] = await source()
        except Exception:
            # A failed query is not evidence of an unprotected book. Startup
            # continues; the positions keep the conservative full-value
            # treatment they would have had anyway.
            logger.exception("Could not read resting stops from the broker during adoption")
            return {}
        return resting

    @property
    def adopted_baseline(self) -> dict[str, float]:
        """Positions that were already held when this session started. Not
        opened by this application, so nothing here carries a stop it placed."""
        return dict(self._adopted_baseline)

    def filled_quantities(self) -> dict[str, float]:
        """What this app believes is held, per symbol.

        A copy, and public, so a screen can show the app's own view alongside
        the broker's without reaching into `_filled_quantities` - the number a
        reconciliation difference is one half of.
        """
        return dict(self._filled_quantities)

    def position_stops(self) -> dict[str, float]:
        """Protective stops this session attached to its own entries.

        Adopted positions are absent by construction: this app did not open
        them and has no idea what, if anything, protects them. PortfolioGovernor
        treats a missing stop as full-value-at-risk rather than assuming a
        stop exists, which is the conservative reading.
        """
        return dict(self._position_stops)

    async def verify_position_stops(self) -> list[str]:
        """Checks that the stops this app believes in are actually resting (M31b).

        `_position_stops` is a belief, and the portfolio governor sizes new
        positions against it: a position with a known stop risks only the
        distance to that stop, one without risks its entire value. So a stop
        that has quietly stopped existing makes the whole book look safer than
        it is.

        On 31 July that happened to six positions at once. The brackets were
        submitted DAY, their take-profit legs expired at the close, and Alpaca
        cancelled the paired stops with them. Reconciliation saw nothing,
        because it compares FILLED QUANTITIES and an expired protective leg
        changes none of them.

        Unprotected positions are dropped from the record rather than kept,
        so the governor falls back to treating them as fully at risk - the
        existing "unknown protection is no protection" rule, now reached by
        evidence instead of assumption. A position whose stop MOVED is a
        different case: it is still protected, so the recorded level is
        replaced by what the broker actually says rather than dropped.

        Both are returned. The caller's question is "which symbols is my
        protection record no longer trustworthy for", and both answer yes.

        The level check exists because the presence check was not one. Until
        M39 this compared `symbol not in resting`, so a stop resting at a
        DIFFERENT price passed - and `_position_stops` is the denominator of
        every risk-at-stop figure the governor gates new entries on, so a
        belief wrong by a factor mis-states the aggregate for the whole book.

        A broker that cannot answer returns nothing, and nothing is changed:
        an adapter without the capability must not be read as "no stops rest
        anywhere", which would drop every stop the app holds.
        """
        resting_source = getattr(self.broker, "resting_stops", None)
        if resting_source is None:
            return []
        resting = await resting_source()
        if not resting and not self._position_stops:
            return []

        held = {pos.symbol for pos in await self.broker.positions() if abs(pos.quantity) > 0}
        lost: list[str] = []
        drifted: list[tuple[str, float, float]] = []
        for symbol, believed in list(self._position_stops.items()):
            if symbol not in held:
                continue
            actual = resting.get(symbol)
            if actual is None:
                lost.append(symbol)
                continue
            # Protection is resting again, so the grace is spent and available
            # afresh. Without this a symbol reprieved once could never be
            # reprieved again, and the second re-protection of its life would
            # drop the belief on the very first check.
            self._protection_grace_used.discard(symbol)
            if abs(actual - believed) > _STOP_LEVEL_TOLERANCE * abs(believed):
                drifted.append((symbol, believed, actual))

        # ⚠️ "REPLACEMENT IN FLIGHT" IS NOT "UNPROTECTED", and until 9 September
        # they were the same state. `submit_protective_stop` only ever proposes
        # - nothing reaches the broker without sign-off - so every re-protection
        # has a window where the old leg is cancelled and nothing rests yet.
        # Dropping the belief there reprices the position at FULL VALUE in
        # `PortfolioGovernor._per_share_risk`, which inflates aggregate
        # risk-at-stop by roughly an order of magnitude and drives the de-lever
        # sweep to trim again - during a breach, which is the only time it runs.
        #
        # ⚠️ THE GRACE LASTS ONE CHECK. `verify_position_stops` exists because a
        # stop that quietly stopped existing makes the book look safer than it
        # is - six positions at once on 31 July. A belief held open forever
        # because something is "pending" would be that defect with an excuse
        # attached, so a sign-off that has not happened by the next check loses
        # the position its belief anyway.
        reprieved: list[str] = []
        for symbol in lost:
            pending = any(
                order.symbol == symbol and order.is_protective_stop
                for order in self.awaiting_signoff()
            )
            if pending and symbol not in self._protection_grace_used:
                self._protection_grace_used.add(symbol)
                reprieved.append(symbol)
                continue
            self._protection_grace_used.discard(symbol)
            self._position_stops.pop(symbol, None)
        lost = [symbol for symbol in lost if symbol not in reprieved]
        for symbol, _believed, actual in drifted:
            # Replaced, not dropped. The position IS protected - just not where
            # this app thought - and the broker is the authority on what rests.
            # Dropping it would count a protected position at full value and
            # overstate the aggregate the governor gates new entries on.
            self._position_stops[symbol] = actual

        if reprieved:
            # WARNING, not ERROR: this is the expected transient of a
            # re-protection, and it is bounded to one check. It is logged at all
            # because a symbol appearing here twice in a row means the sign-off
            # is not happening, and the line after it will be the ERROR.
            logger.warning(
                "PROTECTION PENDING on %s: nothing rests at the broker, but a protective "
                "order is awaiting sign-off, so the recorded stop is KEPT for one check "
                "rather than repricing the position at full value. If sign-off does not "
                "happen before the next check the belief is dropped.",
                ", ".join(sorted(reprieved)),
            )
        if lost:
            logger.error(
                "POSITION UNPROTECTED: %s held with no stop resting at the broker. The stop "
                "this app recorded is gone, so these now count their full value as at risk",
                ", ".join(sorted(lost)),
            )
        if drifted:
            # ERROR, and named with both levels. A protective level moving
            # without this app moving it is exactly as significant as one
            # disappearing, and until M39 nothing looked for it at all.
            logger.error(
                "PROTECTION LEVEL CHANGED at the broker: %s. This app did not move these, so "
                "risk-at-stop was being measured against the wrong distance",
                ", ".join(
                    f"{symbol} believed={believed:g} resting={actual:g}"
                    for symbol, believed, actual in sorted(drifted)
                ),
            )
        return sorted(lost + [symbol for symbol, _, _ in drifted])

    def has_live_buy(self, symbol: str) -> bool:
        """Whether a buy for this symbol is already awaiting sign-off or in
        flight at the broker (M46).

        The anti-pyramiding guard asked the broker for POSITIONS, and a
        transmitted order that has not filled yet is not a position. On
        4 August two seconds separated MS being transmitted and a fresh signal
        arriving; the second signal saw no holding and opened the same trade
        again, for 82 shares against an intended 41.

        The same reasoning the governor already applies to exposure: an order
        that has been committed is committed, whether or not it has filled.
        """
        return any(
            order.symbol == symbol
            and order.side == "buy"
            and order.status in {"pending_signoff", "transmitted"}
            for order in self._orders.values()
        )

    async def naked_positions(self) -> list[tuple[str, float]]:
        """Held positions with no stop resting at the broker (M31d).

        Asked of the account rather than of `_position_stops`, so the answer
        does not depend on what this process happens to remember - which after
        a restart is nothing.
        """
        resting = await self._resting_stops()
        return [
            (pos.symbol, pos.quantity)
            for pos in await self.broker.positions()
            if abs(pos.quantity) > 0 and pos.symbol not in resting
        ]

    async def _broker_quantity(self, symbol: str) -> float | None:
        """What the broker says is held, or None if it cannot be asked.

        None and zero are different answers and must not collapse: zero means
        the position is gone, None means this app does not know - and sizing an
        exit on a guess is what the quarantine exists to prevent.
        """
        try:
            positions = await self.broker.positions()
        except Exception:
            logger.exception("Could not read the broker to size an exit on %s", symbol)
            return None
        return next(
            (abs(pos.quantity) for pos in positions if pos.symbol == symbol),
            0.0,
        )

    async def submit_protective_stop(
        self,
        symbol: str,
        quantity: float,
        stop_price: float,
        take_profit_price: float | None = None,
    ) -> Order:
        """Proposes a resting protective stop on a position already held (M31d).

        Every stop before this rode in as a bracket leg on an entry, so a
        position whose legs died had no way to get another one - the state all
        six holdings were in on 1 August, after the take-profit legs expired at
        Friday's close and Alpaca cancelled the paired stops with them.

        Pending sign-off like everything else. This creates protection rather
        than exposure, which is an argument for letting it through unattended
        and not an argument for bypassing the gate: it still sells shares if
        the price reaches it, and the one rule with no exceptions is that
        nothing reaches the broker without sign-off.
        """
        if quantity <= 0:
            return self._new_rejected_order_for(symbol, "sell", 0.0)
        if stop_price <= 0:
            return self._new_rejected_order_for(symbol, "sell", 0.0)

        # Never two protective orders for one symbol (M33d).
        #
        # Belt and braces against the detection query being wrong, which it
        # was: an OCO's stop leg rests at status `held` and nested under its
        # parent, so a CRWD position carrying a good OCO read as unprotected
        # and a second one was proposed. Signed, that is 32 shares of resting
        # sell orders against a 16-share position.
        #
        # The deeper lesson is that "the broker says nothing is resting" was
        # never safe to act on unilaterally, so the count is enforced here as
        # well as measured there.
        already_pending = next(
            (
                existing
                # NOT `pending_orders` - see `awaiting_signoff`. A transmitted
                # protective stop is resting, and treating it as pending would
                # stop this position ever re-arming.
                for existing in self.awaiting_signoff()
                if existing.symbol == symbol and existing.is_protective_stop
            ),
            None,
        )
        if already_pending is not None:
            logger.warning(
                "Protective order for %s already pending (%s) - not proposing another",
                symbol,
                already_pending.order_id,
            )
            return already_pending

        order = Order(
            symbol=symbol,
            side="sell",
            quantity=quantity,
            order_id=new_order_id(),
            status="pending_signoff",
            stop_price=stop_price,
            # Sent as one OCO when a target is known, so the two levels cancel
            # each other at the broker instead of both being able to fill.
            take_profit_price=take_profit_price,
            order_type="stop",
        )
        self._orders[order.order_id] = order
        logger.warning(
            "Protective %s proposed for unprotected position %s x%g at %.2f%s - awaiting sign-off",
            "OCO" if take_profit_price else "stop",
            symbol,
            quantity,
            stop_price,
            f", target {take_profit_price:.2f}" if take_profit_price else "",
        )
        self._record(order, "pending_signoff", "protective stop for an unprotected position", None)
        await self._announce_pending(order)
        return order

    def _now(self) -> datetime:
        """The clock the fill watermark defaults to. See `__init__`.

        Injectable because "now" is the wrong answer in a replay: a harness
        replaying 2026 asks for fills since the wall clock, and every simulated
        fill is older than that.
        """
        return self._clock() if self._clock is not None else datetime.now(UTC)

    def _load_fill_state(self) -> datetime:
        """The watermark the previous run reached, and what it had recorded.

        No file, no settings, or an unreadable file all mean "start from the
        clock", which is exactly the pre-M50 behaviour: nothing is replayed, and
        nothing can be double-recorded either. Degrading to the old behaviour is
        the right failure here, because the old behaviour was merely incomplete
        rather than wrong.

        The clock is `_now`, not `datetime.now(UTC)` - see `_now`. Both fallback
        paths use it, because a corrupt state file in a replay would otherwise
        reintroduce the same silent zero by a slower route.
        """
        if self._fill_state_path is None:
            return self._now()
        try:
            raw = json.loads(self._fill_state_path.read_text(encoding="utf-8"))
            watermark = datetime.fromisoformat(raw["watermark"])
            absorbed = {
                str(order_id): _absorbed_from_json(entry)
                for order_id, entry in (raw.get("absorbed") or {}).items()
            }
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return self._now()
        self._absorbed_fills = absorbed
        logger.info(
            "Broker-fill watermark restored to %s - executions since then are replayed for "
            "the record, with %d already-recorded fill(s) remembered",
            watermark.isoformat(timespec="seconds"),
            len(absorbed),
        )
        # A WIDE window is legitimate and a SILENT wide window is not.
        #
        # On 24 August this restored a watermark from 10:38 into a process that
        # started at 15:18, so the first absorb pass replayed four and a half
        # hours - the duplicate buys from the M139 incident, the operator's
        # manual remediation sells, and the app's own fills. Every one read as
        # foreign, because `_is_foreign_unrecorded` tests in-memory sets that do
        # not survive a restart.
        #
        # The replay itself is what M50 exists for: a stop that fired while this
        # was down arrives no other way. What was missing is anyone being TOLD
        # the window was that wide, so a four-hour replay looked identical to a
        # four-minute one. `_close_against_lots` now refuses an exit that
        # precedes its lot, which is the arithmetic backstop; this is the line
        # that makes the condition visible before it gets that far.
        age = self._now() - watermark
        if age > _WIDE_REPLAY_WARNING:
            logger.warning(
                "The broker-fill watermark is %.1f hours old, so this run will replay every "
                "execution since %s. That is correct after a clean shutdown and SUSPECT after "
                "a crash: order identity does not survive a restart, so fills from orders this "
                "app itself sent will read as foreign. Check closed_trades.csv afterwards.",
                age.total_seconds() / 3600.0,
                watermark.isoformat(timespec="seconds"),
            )
        return watermark

    def _save_fill_state(self) -> None:
        """Written after each absorb pass, not at shutdown: the restart this
        exists for is the one nobody planned."""
        if self._fill_state_path is None:
            return
        # `_now` for the third time (W2 step 6). Against the wall clock a replay
        # prunes every simulated fill older than 30 REAL days - which is all of
        # them - and a forgotten id is one `_is_foreign_unrecorded` will absorb
        # a second time. That direction DOUBLE-records a closed trade, where the
        # watermark bug merely lost one, and a duplicate is what trips the
        # kill-switch.
        cutoff = self._now() - _ABSORBED_ID_RETENTION
        self._absorbed_fills = {
            order_id: seen
            for order_id, seen in self._absorbed_fills.items()
            if seen.filled_at >= cutoff
        }
        payload = {
            "watermark": self._last_fill_scan.isoformat(),
            "absorbed": {
                order_id: {
                    "filled_at": seen.filled_at.isoformat(),
                    "quantity": seen.quantity,
                    "price": seen.price,
                    # Written, or a migrated record round-trips back to
                    # "0 absorbed, quantity known" and the whole order becomes
                    # eligible again on the NEXT restart - the same hazard
                    # _absorbed_from_json exists to close, reintroduced through
                    # the save path because only the load path was fixed.
                    "quantity_known": seen.quantity_known,
                }
                for order_id, seen in self._absorbed_fills.items()
            },
        }
        try:
            self._fill_state_path.parent.mkdir(parents=True, exist_ok=True)
            self._fill_state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            logger.exception("Could not persist the broker-fill watermark")

    async def missed_fills(self) -> list[BrokerFill]:
        """Executions since the watermark that this app has not recorded (M50).

        Read-only on purpose. The caller needs to see what is about to be
        absorbed BEFORE it is, because a position that closed while the app was
        down is gone from the broker - so nothing at startup would otherwise
        rebuild the entry lot its exit has to close against, and the replayed
        trade would record nothing. See SignalToOrderBridge.replay_missed_exits.
        """
        source = getattr(self.broker, "recent_fills", None)
        if source is None:
            return []
        try:
            fills = await source(self._last_fill_scan, self._symbols_to_watch_for_fills())
        except Exception:
            logger.exception("Could not read broker fills missed while the app was not running")
            return []
        return [fill for fill in fills if self._is_foreign_unrecorded(fill)]

    def _is_foreign_unrecorded(self, fill: BrokerFill) -> bool:
        """Whether this fill is one this app neither sent nor has fully
        recorded."""
        if fill.order_id in self._broker_order_ids or fill.order_id in self._orders:
            # This app sent it and sign_off already counted it. Both sets are
            # checked because an order carries the app's id until it is
            # transmitted and the broker's afterwards.
            return False
        prior = self._absorbed_fills.get(fill.order_id)
        if prior is not None:
            if not prior.quantity_known:
                # Written before M53, so how much was counted is unrecoverable.
                # Treated as finished - see _absorbed_from_json.
                return False
            # Seen before - but seen is not the same as finished. An order that
            # is still filling reports the SAME id with a larger filled_qty, so
            # the question is whether anything NEW has executed, not whether the
            # id is familiar. `_unabsorbed_part` answers that.
            return fill.quantity > prior.quantity + 1e-9
        # ⚠️ `>=`, not `>`. This is the second exclusive comparison on the same
        # coarse clock: measured on Windows 4 September, `datetime.now(UTC)`
        # advances about every 2ms and 199,967 of 200,000 consecutive calls
        # returned an IDENTICAL stamp. A protective fill landing in the same
        # tick as the sweep that set `_last_fill_scan` read as "not new" and was
        # never absorbed - `tracked=100 broker=0`, and the kill switch halting
        # on a stop doing its job.
        #
        # ⚠️ THIS TRADES ONE NARROW RACE FOR ANOTHER, DELIBERATELY. A fill in
        # the tick just BEFORE the baseline is already inside the adopted
        # positions, and admitting it subtracts the same shares twice. Both
        # errors trip the kill switch loudly rather than corrupting silently,
        # and only the missed fill has actually been observed - on the only exit
        # path this system has. An id seen before never reaches this line at
        # all: the `prior is not None` branch above answers it.
        return fill.filled_at >= self._last_fill_scan

    def _fill_query_floor(self) -> datetime:
        """How far back to ask, which is NOT simply the watermark (M53).

        An order still filling keeps the `filled_at` of its first execution, and
        that stamp is already behind the watermark by the time the rest of it
        completes. Asking from the watermark therefore excludes the very order
        whose remainder is outstanding - the adapter drops it before the OMS
        ever sees it, so the delta arithmetic below never gets the chance to
        run. That is what let 17 CVS shares vanish on 5 August.

        So the floor reaches back past every fill still remembered. Re-reading a
        completed one costs nothing: its cumulative quantity is unchanged, the
        delta is zero, and it is skipped. `_absorbed_fills` is pruned to 30
        days, and the query is bounded by symbol, so the window cannot grow
        without limit.

        **The app's OWN partials need the same reach, and were not getting it
        (M70).** `_absorbed_fills` holds foreign executions only - an order this
        app sent is never absorbed - so an entry still filling was covered by
        neither term. Its price would be corrected to the average of the first
        piece and then never again, because the row carrying the final average
        still has the first piece's stamp and falls outside the window. The
        stamp is dropped as soon as the order is complete, so this reaches back
        only while something genuinely is outstanding.
        """
        # ⚠️ A second before HERE TOO, not only when there are stamps below.
        # The brokers' filters are EXCLUSIVE (`filled_at > since`) and
        # `datetime.now(UTC)` is coarse: measured on Windows 4 September, it
        # advances about every 2ms and 199,967 of 200,000 consecutive calls
        # returned an IDENTICAL timestamp. A fill executing in the same tick as
        # a sweep was therefore excluded from that sweep - and then sat
        # permanently below the floor, because `_last_fill_scan` had advanced
        # past it. The loss lands on protective stops, the only exits this
        # system has: nothing absorbs the fill, `tracked=100 broker=0`, and the
        # kill switch halts on a stop doing its job.
        #
        # Re-reading is free by the paragraph above - the delta is zero and it
        # is skipped. Skipping one never was.
        floor = self._last_fill_scan - timedelta(seconds=1)
        stamps = [seen.filled_at for seen in self._absorbed_fills.values()]
        stamps.extend(self._own_partial_fill_stamps.values())
        if stamps:
            # A second before, because the brokers' filters are exclusive and an
            # order's remainder carries the same stamp as its first piece.
            floor = min(floor, min(stamps) - timedelta(seconds=1))
        return floor

    def _unabsorbed_part(self, fill: BrokerFill) -> BrokerFill | None:
        """The part of this execution not already counted, or None (M53).

        A protective order does not always fill in one go. On 5 August a CVS
        stop gapped through at the open and filled 47 shares in pieces; this
        method's absence meant the app read it mid-fill, absorbed 30, recorded
        the id as done, and never counted the remaining 17. Tracked 17 against a
        broker holding 0 is a discrepancy, and reconciliation answered it with
        the kill-switch - eight minutes into the first session that had ever
        recorded a closed trade.

        `BrokerFill.quantity` is CUMULATIVE (`filled_qty`), and so is `price`
        (`filled_avg_price`). The increment's own price therefore has to be
        recovered from the two running averages rather than assumed to be the
        latest one - otherwise a second piece filled at a different price would
        be recorded at the blended average, and the realised P&L would be wrong
        by the difference.
        """
        prior = self._absorbed_fills.get(fill.order_id)
        if prior is None:
            return fill
        if not prior.quantity_known:
            return None
        delta = fill.quantity - prior.quantity
        if delta <= 1e-9:
            return None
        # value_new = total_value - value_already_counted
        increment_value = (fill.price * fill.quantity) - (prior.price * prior.quantity)
        price = increment_value / delta if delta > 0 else fill.price
        return replace(fill, quantity=delta, price=price)

    def watch_symbols_for_fills(self, symbols: Iterable[str]) -> None:
        """Symbols to ask about even though nothing here tracks a position in
        them (M50).

        A stop that fired while the app was down leaves NOTHING behind on this
        side: the broker no longer lists the position, and a fresh process
        adopts a book that never mentions it. Both of the obvious symbol sets
        are therefore empty for precisely the symbol whose exit needs recording.

        The caller that does know is the one holding the entry records - it
        believed it held these positions when it last ran. Registered once at
        startup and bounded by the number of positions ever open at a time.
        """
        self._fill_watch_hint.update(str(symbol) for symbol in symbols)

    def _symbols_to_watch_for_fills(self) -> list[str]:
        """Symbols a broker-side execution could plausibly arrive for (M48).

        The app's TRACKED quantities, not the broker's positions. A stop firing
        is precisely the event that removes a position from the broker's list,
        so asking about what the broker still holds would exclude the one
        symbol we most need to hear about - the same shape of mistake as
        bounding the protection query by `status=open`.

        Adopted positions are included by construction: `_filled_quantities`
        holds them from startup, and their protection was placed in an earlier
        session. Those are the holdings whose fills the old `after=submitted_at`
        window could never have returned.
        """
        symbols = {
            symbol for symbol, quantity in self._filled_quantities.items() if abs(quantity) > 1e-6
        }
        # Anything with an order in flight too, so a fill cannot arrive for a
        # symbol that has no tracked quantity yet.
        symbols.update(order.symbol for order in self._orders.values())
        # And anything a caller believes it held but this process has no record
        # of - see watch_symbols_for_fills.
        symbols.update(self._fill_watch_hint)
        return sorted(symbols)

    async def absorb_broker_fills(self, record_only: bool = False) -> list[BrokerFill]:
        """Records executions the broker performed that this app did not send.

        Only fills for orders this process did not originate are applied - an
        order the app transmitted has already been counted through sign_off,
        and counting it twice would create the very discrepancy this exists to
        prevent.

        Publishing OrderFilledEvent is the point as much as the arithmetic is:
        it is what the trade ledger listens to, so a stop-out or a target
        finally becomes a CLOSED TRADE on the Performance tab instead of a
        position that silently vanished.

        A broker that cannot answer changes nothing, and neither does a failed
        query - the previous behaviour is exactly preserved.
        """
        source = getattr(self.broker, "recent_fills", None)
        if source is None:
            return []
        # Taken BEFORE the query, and it is the value the watermark becomes
        # (M88). A stamp taken after the pass excludes everything that executed
        # during it: the query has already been answered, and the next floor
        # starts above the execution. Protective fills are the only exits this
        # system has, so one lost that way is a closed trade that never exists.
        #
        # `_now`, not `datetime.now(UTC)` (W2 step 6). Injecting the clock into
        # `_load_fill_state` alone was not enough: the FIRST sweep re-stamped
        # the watermark with the wall clock, so a replay's watermark jumped from
        # its simulated start to the real present, and every simulated fill was
        # then behind it forever. Measured - 99 sweeps, every one returning
        # nothing, against a stop that had demonstrably fired.
        scan_started = self._now()
        try:
            fills = await source(self._fill_query_floor(), self._symbols_to_watch_for_fills())
        except Exception:
            logger.exception("Could not read recent broker fills")
            return []

        # IBKR returns one Fill per EXECUTION; Alpaca returns one order object
        # per order. Both now carry the order's CUMULATIVE quantity, so the
        # highest one per order is the whole story and the rest are earlier
        # snapshots of the same order.
        #
        # Collapsing here rather than in the adapter is deliberate: the delta
        # arithmetic below is per ORDER, and feeding it 183 snapshots of one
        # order emits 183 fill events - which the trade ledger turns into 183
        # closed trades for a single exit. The promotion gate counts closed
        # trades toward 20 and 30, so that is not a cosmetic problem.
        #
        # Alpaca is unaffected: one entry per order id means the max is that
        # entry.
        highest: dict[str, BrokerFill] = {}
        for raw in fills:
            seen = highest.get(raw.order_id)
            if seen is None or raw.quantity > seen.quantity:
                highest[raw.order_id] = raw
        fills = sorted(highest.values(), key=lambda f: f.filled_at)

        absorbed: list[BrokerFill] = []
        for raw in fills:
            if not self._is_foreign_unrecorded(raw):
                # Ours, and already counted - but not therefore worthless. This
                # is the only place the price we actually PAID arrives for an
                # order this app sent, and it used to be dropped here (M70).
                #
                # It is also the only place the app learns its own order is
                # DONE. Called before the price correction rather than inside
                # it, because that method returns early on a missing or
                # unchanged price - and whether an order completed has nothing
                # to do with whether its price needed correcting.
                self._close_out_own_order(raw)
                await self._correct_announced_price(raw)
                continue
            fill = self._unabsorbed_part(raw)
            if fill is None:
                continue
            # Read BEFORE the block below, which pops `_position_stops` the
            # moment the fill flattens the position. `_protective_exit_reason`
            # separates a stop from a target by comparing the fill price against
            # the stop level, and it read that dict AFTER the pop - so the level
            # was gone and the comparison could never match.
            #
            # SCOPE, measured against the live record rather than assumed: this
            # fires only for an exit absorbed during a RUNNING session. The pop
            # sits inside `if not record_only`, so the startup replay path -
            # which is how a stop that fired while the app was down arrives -
            # skips it and records correctly. Both closed trades in the live
            # record read `stop`, which is what narrowed the claim: an earlier
            # version of this comment said EVERY stop-out was affected, and
            # closed_trades.csv falsified it.
            #
            # A partial fill never reaches the pop either, so the only case that
            # corrupts is a full exit during a live session - which is precisely
            # the case that produces a closed trade from a stop doing its job.
            stop_at_fill = self._position_stops.get(fill.symbol)
            # The M50 trap, and the reason this is not simply "persist the
            # watermark". A fill from before the baseline was taken is ALREADY
            # in `_filled_quantities`, because adoption read it from the
            # broker's own position list. Applying it again subtracts the same
            # shares twice and trips the kill-switch on arithmetic - M46 by a
            # different route. It still has to be RECORDED: adoption re-baselines
            # what is held and says nothing about what closed.
            if not record_only:
                signed = fill.quantity if fill.side == "buy" else -fill.quantity
                self._filled_quantities[fill.symbol] = (
                    self._filled_quantities.get(fill.symbol, 0.0) + signed
                )
                if abs(self._filled_quantities.get(fill.symbol, 0.0)) < 1e-6:
                    # Flat: whatever was protecting it went with it at the broker.
                    self._position_stops.pop(fill.symbol, None)
            prior = self._absorbed_fills.get(raw.order_id)
            self._absorbed_fills[raw.order_id] = _AbsorbedFill(
                filled_at=raw.filled_at,
                quantity=(prior.quantity if prior else 0.0) + fill.quantity,
                price=raw.price,
            )
            absorbed.append(fill)
            logger.warning(
                "BROKER-SIDE FILL absorbed: %s %g %s at %.2f (order %s) - %s%s",
                fill.side,
                fill.quantity,
                fill.symbol,
                fill.price,
                fill.order_id,
                # Branched on side (M81). This was hard-coded for the sell case
                # M34 was written for, so a position opened AT THE BROKER while
                # the app was down - which arrives through the same path -
                # was announced as "a resting protective order executed, and
                # this is now a closed trade". Both clauses were false, and the
                # second was falsifiable against closed_trades.csv.
                (
                    "a resting protective order executed, and this is now a closed trade"
                    if fill.side == "sell"
                    else (
                        "a position was OPENED at the broker that this application did not "
                        "send. It opens a lot carrying the price paid, but no stop and no "
                        "strategy are known for it, so a trade closed from it will have no "
                        "R-multiple and will count towards no strategy's promotion evidence"
                    )
                ),
                (
                    ". It executed while this application was not running, so it is recorded "
                    "but not re-counted"
                    if record_only
                    else ""
                ),
            )
            if self.bus is not None:
                await self.bus.publish(
                    OrderFilledEvent(
                        order_id=fill.order_id,
                        symbol=fill.symbol,
                        side=fill.side,
                        quantity=fill.quantity,
                        price=fill.price,
                        strategy=None,
                        operator="broker (protective order)",
                        exit_reason=self._protective_exit_reason(fill, stop_at_fill),
                        # When it FILLED, not when we noticed (M50). The ledger
                        # stamps closed_at from this, and a replayed exit can be
                        # days older than the pass that finds it - which would
                        # put a holding period nobody held into the evidence.
                        ts=fill.filled_at,
                    )
                )

        if record_only and absorbed:
            # The M50 trap, and why this is not simply "persist the watermark".
            # These executions happened before this process read the account, so
            # `_filled_quantities` ALREADY reflects them - applying them again
            # would subtract the same shares twice and trip the kill-switch on
            # arithmetic, which is M46 arriving by a different route.
            #
            # Rather than deciding from timestamps whether a fill is inside the
            # baseline - two clocks microseconds apart cannot answer that, and
            # guessing either way trips the kill-switch from one side or the
            # other - the quantities are simply re-read from the broker, which
            # is the only thing that actually knows.
            await self._resync_tracked_quantities()

        # Advanced and persisted only after the pass, so a crash mid-loop
        # replays rather than skips - and `_absorbed_fills` is what makes a
        # replay safe to repeat. The VALUE is the instant the pass began rather
        # than the instant it ended (M88): an end stamp replays nothing and
        # skips whatever executed while the pass ran. A begin stamp replays
        # strictly more, which is the same property the crash argument relies
        # on, so this strengthens that reasoning rather than weakening it.
        self._last_fill_scan = scan_started
        self._save_fill_state()
        return absorbed

    def _order_the_broker_calls(self, broker_order_id: str) -> Order | None:
        """The app's record of an order, found by the id the BROKER uses.

        `_orders` is keyed by the app's own id and the adapter overwrites
        `order.order_id` with the broker's on transmit, so the key and the
        attribute disagree for every transmitted order - which is exactly the
        M46 mismatch. Both are checked, in that order: the attribute is the one
        a fill can be matched on, and the key is what an adapter that preserves
        the id leaves behind.
        """
        for order in self._orders.values():
            if str(order.order_id) == broker_order_id:
                return order
        return self._orders.get(broker_order_id)

    def _close_out_own_order(self, raw: BrokerFill) -> None:
        """Marks an order this app sent as filled once the broker completes it.

        ⚠️ NOBODY DID THIS FOR A REAL BROKER. `MockBroker` and
        `SimulatedBroker` fill synchronously and write `status = "filled"`
        themselves, so every test in this suite passed against a broker that
        closed its own orders out. `IBAdapter` writes "transmitted",
        "cancelled" and "rejected" and never "filled": `from_ib_trade` can map
        it, but it is only ever called at placement, when the trade is still
        PreSubmitted.

        Measured live on 4 September: TWE.AX and TAH.AX were filled by IBKR and
        still read `transmitted` forty-five minutes later, with the autonomy
        loop re-asking about each once a minute and the resting-order rail
        quarantining both symbols.

        ⚠️ Quantity, not merely arrival. A partial fill leaves the order
        transmitted, because it genuinely is still working and every rail that
        asks what is in flight needs that to stay true.

        ⚠️ Only from "transmitted". A late fill notice must not rewrite the
        outcome of an order this app cancelled or the broker rejected - the
        same reasoning `_TERMINAL_ORDER_STATUSES` applies to a late 202 against
        an order that already filled.
        """
        order = self._order_the_broker_calls(raw.order_id)
        if order is None or order.side != raw.side:
            return
        if order.status != "transmitted":
            return
        if raw.quantity + 1e-9 < order.quantity:
            return
        order.status = "filled"
        logger.info(
            "Order %s (%s %s %g) is filled at the broker - it had been reading "
            "'transmitted' since sign-off.",
            order.order_id,
            order.side,
            order.symbol,
            order.quantity,
        )

    async def _correct_announced_price(self, raw: BrokerFill) -> None:
        """Announces what an order this app sent actually filled at (M70/M71).

        `_announce_fill` publishes at "transmitted" as well as at "filled", and
        at transmit there is no fill price - so what went out was the price the
        order was SIZED against. Alpaca acknowledges asynchronously, so that is
        the normal case rather than the exceptional one: 8 of the 10 positions
        held on 8 August recorded a price the account never paid, AMD by 141
        bps.

        One derivation of "what the broker really did versus what we
        announced", applied to both sides. A buy correction rebases an OPEN
        LOT, still in memory - `reconcile_entry_prices` also heals that at the
        next startup, so a position opened and closed inside one session is the
        only gap this closes for a buy. A sell CLOSES the position: there is no
        open lot left and no next-startup healing path, because the
        `ClosedTrade` is already written to `closed_trades.csv` by the time the
        true fill arrives. `TradeLedger._on_exit_price_corrected` amends that
        row in place.

        Nothing here touches a quantity. The fill was counted at sign-off, and
        counting it again is the M46 discrepancy that halted 4 August.
        """
        if self.bus is None or raw.price <= 0:
            return
        order = self._order_the_broker_calls(raw.order_id)
        if order is None or order.side != raw.side:
            return
        # Remembered only while the order is genuinely still filling, so
        # `_fill_query_floor` reaches back far enough to see the row carrying
        # the final average - which keeps the FIRST execution's stamp. Side-
        # independent: a partial fill is a partial fill either way.
        if raw.quantity + 1e-9 < order.quantity:
            self._own_partial_fill_stamps[raw.order_id] = raw.filled_at
        else:
            self._own_partial_fill_stamps.pop(raw.order_id, None)
        announced = order.filled_price or order.reference_price
        if not announced or announced <= 0:
            # Nothing was published to correct - `_announce_fill` returns early
            # without a price, so no record was ever built from one.
            return
        if abs(raw.price - announced) <= _ANNOUNCED_PRICE_TOLERANCE * abs(announced):
            return
        if self.anomalies.is_quarantined(raw.symbol):
            # The rule `reconcile_entry_prices` already applies. A corporate
            # action changes what the broker reports legitimately, and a
            # position in that state is one M60 exists to stop anything writing
            # to - including this.
            return
        # Recorded on the order too, so the next poll compares against the
        # corrected figure and stays quiet. A partial that later completes
        # reports a larger cumulative average and corrects again, which is what
        # keeping the guard on DIFFERENCE rather than on having-run-once buys.
        order.filled_price = raw.price
        bps = 10_000.0 * (raw.price - announced) / announced
        if order.side == "buy":
            logger.warning(
                "ENTRY PRICE CORRECTED: %s filled at %.4f, announced at %.4f (%+.1f bps). The "
                "announcement went out at transmit, where the only price available is the one "
                "the order was SIZED against - so the entry record, the open lot's cost basis "
                "and every R-multiple measured from it were wrong by that difference.",
                raw.symbol,
                raw.price,
                announced,
                bps,
            )
            await self.bus.publish(
                EntryPriceCorrectedEvent(
                    order_id=raw.order_id,
                    symbol=raw.symbol,
                    price=raw.price,
                    announced_price=float(announced),
                )
            )
        else:
            logger.warning(
                "EXIT PRICE CORRECTED: %s filled at %.4f, announced at %.4f (%+.1f bps). The "
                "announcement went out at transmit, where the only price available is the one "
                "the order was SIZED against - so the ClosedTrade's exit price, the realised "
                "P&L, the exit cost and the R-multiple were all wrong by that difference.",
                raw.symbol,
                raw.price,
                announced,
                bps,
            )
            await self.bus.publish(
                ExitPriceCorrectedEvent(
                    order_id=raw.order_id,
                    symbol=raw.symbol,
                    price=raw.price,
                    announced_price=float(announced),
                    # The order's own quantity - what the original write
                    # costed the exit against - not `raw.quantity`, which is
                    # this particular fill report's quantity and can be a
                    # partial (M71 review, minor 6).
                    quantity=order.quantity,
                )
            )

    async def _resync_tracked_quantities(self) -> None:
        """Re-reads the position baseline from the broker after a replay.

        Deliberately quiet, unlike `adopt_broker_positions`: adoption is the
        event worth announcing, and this is the same read repeated moments later
        for a known reason.
        """
        try:
            positions = await self.broker.positions()
        except Exception:
            logger.exception("Could not re-read positions after replaying missed executions")
            return
        self._filled_quantities = {pos.symbol: pos.quantity for pos in positions}
        held = set(self._filled_quantities)
        for symbol in [s for s in self._position_stops if s not in held]:
            # Flat: whatever was protecting it went with it at the broker.
            self._position_stops.pop(symbol, None)

    def _protective_exit_reason(self, fill: BrokerFill, stop: float | None) -> str:
        """Which leg of the OCO fired, decided by the level it landed on.

        A stop fills at or below its trigger and a target at or above its
        limit, so the two are separable by price - and this is the only
        distinction available, because neither order was sent from here.

        The stop level is PASSED IN rather than read here, because the caller
        pops it from `_position_stops` as soon as the fill flattens the
        position. Reading it here returned None for every completed exit, so
        this method answered `target` for every stop-out ever recorded. A
        parameter makes the ordering impossible to get wrong again; a lookup
        made it impossible to get right.
        """
        if stop is not None and fill.price <= stop * 1.02:
            return "stop"
        return "target"

    async def _in_flight_buy_remainders(self) -> dict[str, float]:
        """How much of each working BUY order the broker has NOT yet filled.

        `sign_off` books `filled.quantity` - the ORDER'S SIZE, not what executed
        - so between acceptance and completion this app's holdings view runs
        ahead of the broker's by exactly this amount. Measured live on
        31 August: the poll landed nine seconds into a forty-five-second fill
        and halted trading on `tracked=1097 broker=378`, while the resting scan
        in the very same second already held `JHX.AX BUY resting=719`.

        ⚠️ **BUYS ONLY, and this is load-bearing.** The resting protective legs
        are working SELL orders whose remaining is the full position - BOQ's is
        13,586 - but a protective stop returns early at sign-off and never
        touches `_filled_quantities`; the `return filled` sits two lines above
        `signed_qty`. Subtracting their remainders would invent a tolerance of
        the whole position on a symbol with no divergence at all, and turn a
        clean book into a halt. Buys always inflate tracked; protective sells
        never do.

        ⚠️ **No evidence means NO tolerance.** An adapter without
        `open_orders()`, or one whose call fails, yields an empty map and the
        rail behaves exactly as it did before. A rail that loses its evidence
        must get stricter, not laxer.
        """
        source = getattr(self.broker, "open_orders", None)
        if source is None:
            return {}
        try:
            orders = await source()
        except Exception:
            logger.exception(
                "Could not read open orders for the reconciliation tolerance - "
                "judging on the raw difference, which is the strict direction"
            )
            return {}

        remainders: dict[str, float] = {}
        for order in orders:
            if order.side != "buy" or order.status not in WORKING_STATUSES:
                continue
            remainders[order.symbol] = remainders.get(order.symbol, 0.0) + float(order.quantity)
        return remainders

    async def check_reconciliation(self) -> bool:
        """Compares OMS-tracked filled quantities against broker-reported
        positions; a mismatch trips the kill-switch (spec §I). Returns True
        if a mismatch was found.

        Call adopt_broker_positions() once at startup first, or an account with
        any pre-existing holding reads as a mismatch immediately.

        A divergence the anomaly store EXPLAINS is not a mismatch (M39). The
        return value keeps its meaning - "a halting mismatch was found" - so
        ReconciliationMonitor, which publishes KillSwitchEvent on True, needs
        no change. An explained symbol is still quarantined; explanation and
        quarantine are separate questions.
        """
        # Broker-side executions are absorbed BEFORE anything is judged (M34).
        #
        # A resting stop or target filling closes a position with no order
        # leaving this process, so nothing publishes OrderFilledEvent. Without
        # this step the comparison below sees tracked=58 against broker=0 and
        # trips the kill-switch on a stop doing exactly its job - and the trade
        # ledger never records the closed trade, so the promotion gate
        # accumulates nothing from the only exits this system actually has.
        await self.absorb_broker_fills()

        # Protection is checked alongside quantity, because they fail in
        # different ways and only one of them was ever being watched.
        await self.verify_position_stops()
        broker_positions = {pos.symbol: pos.quantity for pos in await self.broker.positions()}
        # Defect B, 31 August. An order still filling is not a divergence: this
        # app books the whole order at sign-off while the broker reports only
        # what has executed, so the two legitimately differ by the unfilled
        # remainder until the order completes. Subtracting it EXPLAINS that gap
        # without blinding the rail - anything beyond the remainder still halts,
        # and with no working buy the tolerance is zero.
        in_flight = await self._in_flight_buy_remainders()
        symbols = set(self._filled_quantities) | set(broker_positions)
        divergent = {
            # ⚠️ The pair stays RAW - what each side actually holds. The
            # tolerance explains the difference; it must not rewrite the numbers
            # the log line reports, or the record would describe a book nobody
            # has.
            symbol: (self._filled_quantities.get(symbol, 0.0), broker_positions.get(symbol, 0.0))
            for symbol in symbols
            if abs(
                self._filled_quantities.get(symbol, 0.0)
                - broker_positions.get(symbol, 0.0)
                - in_flight.get(symbol, 0.0)
            )
            > 1e-6
        }
        explained = {
            symbol: pair
            for symbol, pair in divergent.items()
            if self.anomalies.explains(symbol, pair[1])
        }
        unexplained = {
            symbol: pair for symbol, pair in divergent.items() if symbol not in explained
        }

        for symbol, (tracked, actual) in sorted(explained.items()):
            if symbol in self._explained_logged:
                continue
            self._explained_logged.add(symbol)
            anomaly = self.anomalies.get(symbol)
            logger.warning(
                "%s tracked=%g broker=%g is explained by a declared position anomaly (%s) - "
                "not halting. The symbol stays quarantined and its records are still "
                "uncorrected.",
                symbol,
                tracked,
                actual,
                anomaly.reason if anomaly is not None else "reason unavailable",
            )

        if unexplained:
            logger.error(
                "Broker reconciliation mismatch: %s",
                ", ".join(
                    f"{sym} tracked={tracked:g} broker={actual:g}"
                    for sym, (tracked, actual) in sorted(unexplained.items())
                ),
            )
            self.kill_switch.check_reconciliation()
        return bool(unexplained)

    async def check_resting_orders(self) -> list[SymbolOrderDivergence]:
        """Orders resting at the broker that the book cannot justify (M141).

        The counterpart to `check_reconciliation`, and the question nothing was
        asking. That one unions tracked positions with broker positions, so a
        holding this app knows nothing about is still compared. Orders had no
        equivalent: every order-side check asked "is what I believe still
        there" and none asked "what is there that I do not believe in". On
        24 August sixteen orphaned GTC bracket legs rested against a flat
        TNE.AX - up to 12,304 shares of automatic short risk that buying power
        would not have refused.

        Does NOT trip the kill-switch. The risk is symbol-local, the switch
        halts new flow without cancelling anything (24 August's second lesson:
        stopping the process did not stop the fills), and spending a rail that
        needs a human reset on a detector with no field history is how the
        staleness rail ended up suppressed with a 69-hour value.

        A broker that cannot answer judges NOTHING - and says so LOUDLY (I2,
        final review). Before that fix, a scan that ran and found nothing, an
        adapter stub returning `[]`, an adapter with no `open_orders` at all,
        and the scan disabled by settings were four causes producing
        byte-identical silence: no log line distinguished any of them, so
        `session_check.ps1` could not tell "checked, clean" from "never
        checked" - the exact gap `verify_position_stops`'s own defensive shape
        does not have, because that one at least never claims to have looked.
        """
        source = getattr(self.broker, "open_orders", None)
        if source is None:
            logger.error(
                "RESTING ORDER SCAN: %s has no open_orders() - resting orders "
                "cannot be checked on this adapter. This is NOT a clean scan; "
                "it is a capability this adapter does not have, and must not "
                "be read as 'nothing rests anywhere'.",
                type(self.broker).__name__,
            )
            return []

        orders = await source()
        positions = await self.broker.positions()
        working = [order for order in orders if order.status in WORKING_STATUSES]
        divergences = unjustified_resting_risk(orders, positions)

        # The heartbeat. Unconditional and always the same prefix - unlike the
        # per-divergence ERROR below, which is throttled once landed (I5) -
        # because this is the line that proves the scan ran at all, on every
        # poll, clean or not. `session_check.ps1` greps `RESTING ORDER SCAN:`
        # for exactly that reason; do not change the prefix without updating it.
        logger.info(
            "RESTING ORDER SCAN: %d working leg(s) across %d symbol(s), %s",
            len(working),
            len({order.symbol for order in working}),
            (
                "nothing unjustified"
                if not divergences
                else f"{len(divergences)} symbol/side divergence(s) unjustified"
            ),
        )

        # Item 59. The rail that DECLARES a quarantine is the only thing
        # entitled to lift it, and until this existed it never did: the loop
        # below runs only over divergences, so a clean scan cleared nothing and
        # `clear()` had one caller in the codebase - an operator button. Two
        # quarantines outlived their cause by 26 hours and a restart on
        # 27 August.
        #
        # ⚠️ Scoped to what this scan could actually SEE. A symbol the broker
        # did not report is not evidence of anything, and counting it as clean
        # would lift a quarantine on absence of evidence.
        diverged_now = {d.symbol for d in divergences}
        scanned = {order.symbol for order in orders} | {p.symbol for p in positions}
        self.resting_order_anomalies.saw_clean_scan(scanned - diverged_now)

        for divergence in divergences:
            # Logged once per session per (symbol, side), and again only if
            # the excess actually changed (I5) - see `_resting_order_logged`.
            # `declare()` below still runs every scan regardless, because the
            # anomaly store must stay current even when the log stays quiet.
            key = (divergence.symbol, divergence.side)
            last_excess = self._resting_order_logged.get(key)
            if last_excess is None or abs(last_excess - divergence.excess) > 1e-6:
                logger.error("RESTING ORDER ORPHAN: %s", divergence.describe())
                self._resting_order_logged[key] = divergence.excess
            self.resting_order_anomalies.declare(
                symbol=divergence.symbol,
                reason=(
                    f"{divergence.excess:g} shares of resting {divergence.side} the book does "
                    f"not justify ("
                    f"{'flat' if divergence.flat else f'holds {divergence.justified:g}'})"
                ),
                declared_by="order-reconciler",
                excess=divergence.excess,
            )

            if not divergence.flat:
                # Reported and quarantined, never trimmed. Choosing which OCA
                # group dies on a HELD symbol is a judgement this application
                # should not make unattended, and getting it wrong strips the
                # stop from a real long - the failure `verify_position_stops`
                # exists to shout about.
                continue
            if self.settings is None or not self.settings.resting_order_cancel_enabled:
                # Off by default (M141, item 23). This is the ONLY code path
                # that acts on the broker rather than just reporting on it, so
                # it stays inert until an operator has explicitly turned it on
                # - the 24 August orphans were discovered by a human reading
                # logs, and cancelling automatically before this flag existed
                # would have been a different kind of unattended surprise.
                continue

            # TOCTOU guard (Task 7b, final review). `divergence.flat` was
            # decided from the `positions()` snapshot taken above, before any
            # cancel. This account carries live brackets - a stop AND a target,
            # one-cancels-all - so a fill between that snapshot and any one of
            # the `cancel_order` awaits below is not hypothetical: leg 1's
            # stop-sell filling mid-loop opens a real short, and cancelling
            # legs 2-8 (one of them that fill's own OCA sibling) leaves it with
            # no protection at all. Re-read immediately before committing to
            # the loop, and refuse on either of two INDEPENDENT signals - the
            # broker's fresh answer, and this app's own tracked fill count -
            # because the whole feature exists on the premise that one source
            # alone was not enough to trust.
            fresh_positions = {pos.symbol: pos.quantity for pos in await self.broker.positions()}
            broker_flat_now = abs(fresh_positions.get(divergence.symbol, 0.0)) <= 1e-6
            tracked = self._filled_quantities.get(divergence.symbol, 0.0)
            if not broker_flat_now or abs(tracked) > 1e-6:
                logger.error(
                    "Cancel ABANDONED for %s: no longer flat by the time the cancel loop "
                    "was reached (broker now reports %g held, this app tracks %g filled). "
                    "Cancelling orphan legs on a symbol that just acquired a real position "
                    "would leave it with no protection at all. STILL RESTING.",
                    divergence.symbol,
                    fresh_positions.get(divergence.symbol, 0.0),
                    tracked,
                )
                continue

            for leg in divergence.legs:
                try:
                    await self.broker.cancel_order(leg.order_id)
                except Exception as exc:  # noqa: BLE001 - one refusal must not stop the rest
                    # IBKR error 10147's shape exactly: an order visible via
                    # reqAllOpenOrders can still be UNCANCELLABLE from this
                    # client connection (e.g. it belongs to another client id
                    # or TWS session). A raise here must not silently leave
                    # every leg after this one resting - so it is logged,
                    # attributed to the owning client, and the loop moves on.
                    logger.error(
                        "Orphaned leg %s on %s could not be cancelled (%s). It is visible via "
                        "reqAllOpenOrders but owned by client %s, which is error 10147's shape: "
                        "visible is not cancellable. STILL RESTING.",
                        leg.order_id,
                        divergence.symbol,
                        exc,
                        leg.owner_client_id,
                    )
                    continue
                logger.warning(
                    "Cancelled orphaned leg %s on %s (%s %s %g) - the book holds none of it",
                    leg.order_id,
                    divergence.symbol,
                    leg.side,
                    leg.order_type,
                    leg.quantity,
                )
        return divergences

    def record_unsized_signal(
        self, symbol: str, side: Literal["buy", "sell"], strategy: str | None, reason: str
    ) -> Order:
        """A signal that could not even be SIZED, recorded as a refusal (M54).

        Everything upstream of the risk engine used to fail silently: if the
        account could not be read there was no candidate to reject, so no
        rejected order was created and nothing reached the journal. The signal
        left no trace but a stack trace.

        This produces the same rejected order any other refusal does, so the
        audit trail answers "why did nothing happen" with a reason rather than
        with a gap. It is deliberately a REJECTION and not a retry: the next
        tick will re-emit the signal if the condition still holds, and inventing
        a retry loop here would hide a broker outage rather than record it.
        """
        return self._new_rejected_order_for(symbol, side, 0.0, reason, strategy=strategy)

    def _pending_action(self, symbol: str) -> str | None:
        """A one-line description of a pending corporate action, or None (M39).

        Returns the DESCRIPTION rather than the record, so this module needs no
        import from the corporate-actions package and the refusal reason reads
        the same wherever it is shown.
        """
        monitor = self.corporate_actions
        if monitor is None:
            return None
        action = monitor.pending_action(symbol)  # type: ignore[attr-defined]
        if action is None:
            return None
        describe = getattr(action, "describe", None)
        return describe() if callable(describe) else str(action)

    def _new_rejected_order(
        self, candidate: OrderCandidate, quantity: float, reason: str = "rejected"
    ) -> Order:
        return self._new_rejected_order_for(
            candidate.symbol, candidate.side, quantity, reason, strategy=candidate.strategy
        )

    def _new_rejected_order_for(
        self,
        symbol: str,
        side: Literal["buy", "sell"],
        quantity: float,
        reason: str = "rejected",
        strategy: str | None = None,
    ) -> Order:
        order = Order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_id=new_order_id(),
            status="rejected",
            strategy=strategy,
        )
        self._orders[order.order_id] = order
        self._record(order, "rejected", reason)
        return order

    def _record(self, order: Order, outcome: str, reason: str, operator: str | None = None) -> None:
        """One line in the decision journal. Never raises: a journal write
        failure must not abort an order path that has already decided."""
        if self.journal is None:
            return
        try:
            self.journal.record(
                JournalEntry(
                    order_id=order.order_id,
                    symbol=order.symbol,
                    side=order.side,
                    outcome=outcome,
                    reason=reason,
                    quantity=order.quantity,
                    price=order.reference_price or order.filled_price,
                    strategy=order.strategy,
                    entity_name=operator or "",
                    execution_mode=self.risk_engine.settings.execution_mode,
                )
            )
        except Exception:  # noqa: BLE001 - journalling is never load-bearing
            logger.warning("Could not journal the %s decision for %s", outcome, order.order_id)
