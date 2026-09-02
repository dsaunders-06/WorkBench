"""The ACCOUNT facts both advisory screens are entitled to (item 61).

`advisory_inputs.build_advisory_context` gathers the per-SYMBOL material - news,
next earnings - and takes everything else from its caller. That was the gap:
what a caller does not pass defaults to an empty dict and nothing errors, so on
27 August the Workbench's AI note opened *"Given no current positions and
lacking portfolio risk metrics"* while the account held 3,192 SUN.AX. The
Advisor passed `positions`, `risk_metrics`, `verdict` and `position`; the
Workbench passed none of them.

**One gatherer, called by both screens**, for the reason `advisory_inputs`'
own docstring already gives about the material it fetches: *two copies of this
would drift; one copy cannot*. A screen can no longer assemble a SUBSET of the
account facts, because it does not assemble them at all.

Not folded into `advisory_inputs` deliberately. That module states it stays
"free of a dependency it does not otherwise need" and reaches `SymbolVerdict`
through a Protocol rather than importing it; the verdict builder needs
`AutonomyGate`, `build_position_views` and the governor, and dragging those in
would trade one design rule for another. This module is where the heavy reads
are allowed to live.

⚠️ **Every read here is READ-ONLY, and that line may not be crossed.**
`governor.snapshot`, `position_stops`, `entry_permitted`, `is_quarantined` and
`gate.evaluate` are pure or read-only; `RiskEngine.evaluate_*` - the sizer,
which WRITES `risk_decisions.csv` - is never called. See `symbol_verdict.py`'s
module docstring for why.

Every path degrades to "nothing known". An advisory screen is the last place
that should raise.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from qat.data.broker.account_poller import AccountSnapshot
from qat.data.broker.adapter import Position
from qat.domain.autonomy.gate import AccountState, AutonomyGate
from qat.domain.oms.position_view import PositionView, build_position_views
from qat.presentation.symbol_verdict import SymbolVerdict, build_verdict

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccountFacts:
    """What both screens pass to `build_advisory_context`, gathered once.

    A dataclass rather than a tuple so a new fact can be added in ONE place and
    reach both screens - which is the property whose absence is item 61.
    """

    positions: dict[str, float] = field(default_factory=dict)
    risk_metrics: dict[str, float] = field(default_factory=dict)
    verdict: SymbolVerdict | None = None
    position: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    # Kept because the Advisor renders its verdict block from the SAME values
    # the model was given. Re-deriving them for the display is the divergence
    # M126 was about, reproduced inside one screen.
    view: PositionView | None = None


async def gather(runtime: Any, symbol: str) -> AccountFacts:
    """Every account fact an advisory answer about `symbol` is entitled to.

    Wrapped whole: a failure here costs the account context and never the
    answer. An empty `AccountFacts` renders exactly as it did before this
    module existed, so the degraded path is the old behaviour rather than a
    new one.
    """
    # ⚠️ PER-FACT, not one try around everything. The first version wrapped the
    # whole gather, so a failure in ANY optional read - `risk_metrics` reaching
    # `runtime.risk_engine`, `corporate_action_notes` reaching `settings` -
    # discarded the positions that had already been read SUCCESSFULLY, and the
    # answer went out as "the account is flat". One optional fact must not cost
    # every fact.
    positions: dict[str, float] = {}
    verdict: SymbolVerdict | None = None
    view: PositionView | None = None
    try:
        # One shared, throttled read (M21) - the same snapshot the Dashboard's
        # own `_refresh` reads, rather than a second broker round trip.
        snapshot = await runtime.account_poller.snapshot()
        raw_positions = list(snapshot.positions)
        positions = {p.symbol: p.quantity for p in raw_positions}
        verdict, view = build_symbol_verdict(runtime, symbol, raw_positions, snapshot)
    except Exception:
        # ⚠️ WARNING, not debug. This logged at DEBUG - below the root level,
        # and no DEBUG line has ever been emitted by this application - so a
        # failure degraded the answer to an empty account and said so NOWHERE.
        # That is item 61's own failure mode reproduced inside item 61's fix.
        # The broad except stays: an advisory screen must never raise.
        logger.warning(
            "Could not read the account for %s - the answer will be given WITHOUT "
            "positions or a verdict, and must NOT be read as 'the account is flat'",
            symbol,
            exc_info=True,
        )

    empty_metrics: dict[str, float] = {}
    empty_notes: list[str] = []
    metrics = _guarded(lambda: risk_metrics(runtime), empty_metrics, "risk metrics", symbol)
    notes = _guarded(
        lambda: corporate_action_notes(runtime), empty_notes, "corporate actions", symbol
    )

    facts = AccountFacts(
        positions=positions,
        risk_metrics=metrics,
        verdict=verdict,
        position=position_dict(view),
        notes=notes,
        view=view,
    )
    # ⚠️ The line that makes a read-back ANSWERABLE. Nothing else in
    # `domain/ai_advisory/` logs at all, so on 28 August "the Workbench note did
    # not mention the holding" could not be told apart from "the holding never
    # reached the model" - and the answer decided whether item 61 had worked.
    logger.info(
        "Advisory context for %s: %d position(s), %s held, risk metrics %s, "
        "verdict %s, %d corporate-action note(s)",
        symbol,
        len(facts.positions),
        "IS" if symbol in facts.positions else "NOT",
        "present" if facts.risk_metrics else "ABSENT",
        "built" if facts.verdict is not None else "unavailable",
        len(facts.notes),
    )
    return facts


def _guarded[T](read: Callable[[], T], fallback: T, what: str, symbol: str) -> T:
    """One optional fact, or its fallback - never the whole context."""
    try:
        return read()
    except Exception:
        logger.warning(
            "Could not read %s for %s - that part of the advisory context is ABSENT, "
            "which is not the same as empty",
            what,
            symbol,
            exc_info=True,
        )
        return fallback


def resolve_day_pnl_pct(*, broker_pct: float | None, monitor_pct: float | None) -> float | None:
    """The day's P&L for the verdict, from whichever source can answer (item 47).

    The verdict's guard - suppress rather than assume - is right and stays:
    a substituted 0.0 could never trip the always-negative pause threshold, so
    an unreported -6% day would read as "no rail here would refuse it".

    What was wrong was the input. `balances.day_pnl_pct` derives from
    `last_equity`, an Alpaca-era "previous close" that IBKR never supplies, so
    on this broker it is ALWAYS None and the verdict had never rendered in
    production. `EquityMonitor.day_pnl_pct()` measures against a persisted
    `day_start_equity`, works on any broker, and is what `AutonomyGate`
    actually gates on - so the verdict now agrees with the rail it reports.

    A monitor figure of exactly 0.0 is a MEASURED zero and must survive; only
    None means unknown. `is not None`, never truthiness.
    """
    if broker_pct is not None:
        return broker_pct
    return monitor_pct


def position_dict(view: PositionView | None) -> dict[str, Any]:
    """The held position's own facts, read from `position_view.py` (M136) -
    never re-derived, for the reason `AdvisoryContext.position`'s own comment
    gives: a model asked whether to sell a symbol with only its share count
    has no entry price, no P&L, no R multiple and no stop to reason from.

    Empty when the symbol is not held or the view could not be built - the
    same "show nothing rather than guess" rule `position_view.py` states for
    itself, not a substitute zero.
    """
    if view is None:
        return {}
    return {
        "quantity": view.quantity,
        "entry_price": view.entry_price,
        "last_price": view.last_price,
        "pnl_pct": view.pnl_pct,
        "pnl_r": view.pnl_r,
        "exit_distance": view.exit_distance,
        "stop_distance": view.stop_distance,
        "risk_share": view.risk_share,
        "notes": list(view.notes),
    }


def risk_metrics(runtime: Any) -> dict[str, float]:
    """The portfolio risk figures that actually exist (M73).

    This read `portfolio_check.get("var_95", 0.0)`, so a metric the last check
    did not record reached the model as a MEASURED ZERO - "no tail risk" - and
    a language model has no way to ask which it was.

    `to_prompt_text` applies exactly this discipline to fundamentals, and says
    so in the prompt: "fields the vendor could not answer are omitted rather
    than zeroed". Absent is omitted here for the same reason.

    ⚠️ The tuple was ("var_95", "es_975"). Measured across all 63 audit rows
    that carry a portfolio_check: var_99 and single_name_pct are non-null in
    63 of 63 and were being discarded, while sector_pct is non-null in only 3
    and is omitted by the `is not None` filter on the other 60 - which is the
    same "absent is omitted rather than zeroed" discipline, working correctly.
    """
    entries = runtime.risk_engine.audit_log.entries()
    if not entries:
        return {}
    portfolio_check = entries[-1].inputs.get("portfolio_check")
    if not portfolio_check:
        return {}
    return {
        name: float(value)
        for name in ("var_95", "var_99", "es_975", "single_name_pct", "sector_pct")
        if (value := portfolio_check.get(name)) is not None
    }


def corporate_action_notes(runtime: Any) -> list[str]:
    """Pending corporate actions, into the context the model reasons from
    (M39, R2).

    The reason this is not optional: the model is asked about positions, and a
    pending split means a share count and a per-share price are both about to
    change. Advice about a position whose shape is about to move, given without
    knowing that, is confidently wrong - and `is_synthetic` is the precedent for
    a fact reaching the model late rather than never.
    """
    monitor = getattr(runtime, "corporate_action_monitor", None)
    pending = monitor.pending_actions() if monitor is not None else []
    if not pending:
        return []
    mode = runtime.settings.corporate_action_mode
    return [
        f"CORPORATE ACTION PENDING: {a.describe()}. The resting stop is "
        + (
            f"adjusted to {a.adjusted_stop:.2f}."
            if a.state == "applied" and a.adjusted_stop is not None
            else f"NOT adjusted (mode={mode})."
        )
        + " New entries in this symbol are refused."
        for a in pending
    ]


def bars_for(runtime: Any, symbol: str) -> pd.DataFrame | None:
    """The bars `PositionView.exit_distance` is computed from.

    The identical read `dashboard.py`'s own `_bars_for` performs, for the
    identical reason given there: read-only, so building a verdict cannot
    mutate `SignalToOrderBridge` state, and never the aggregator the exit
    condition is actually judged against.
    """
    bridge = runtime.signal_bridge
    if bridge is None:
        return None
    # Narrowed rather than returned straight through: `runtime` is `Any` here,
    # so mypy cannot see the frame's type and a bare return would smuggle `Any`
    # past a declared `DataFrame | None`.
    frame = bridge.bars.frame_if_present(symbol)
    return frame if isinstance(frame, pd.DataFrame) else None


def build_symbol_verdict(
    runtime: Any,
    symbol: str,
    positions: list[Position],
    account_snapshot: AccountSnapshot,
) -> tuple[SymbolVerdict | None, PositionView | None]:
    """What this application's own rails say about `symbol`, right now (M136) -
    or `(None, None)` when it cannot be said without guessing.

    Wrapped so a failure anywhere in here costs the verdict block and never the
    answer.
    """
    try:
        equity = account_snapshot.balances.equity
        cash = account_snapshot.balances.cash
        # Item 47. This read `balances.day_pnl_pct` alone, which derives from
        # `last_equity` - a field IBKR never supplies - so the value was ALWAYS
        # None on this broker and the verdict below never rendered in
        # production. The guard is right and stays; the input was wrong.
        monitor = getattr(runtime, "equity_monitor", None)
        state = getattr(monitor, "state", None)
        # ONLY when the monitor genuinely has a basis. `day_pnl_pct()` returns
        # 0.0 rather than None when it does not - deliberately, so a
        # just-started app does not read as a loss and pause buys. That is right
        # for the GATE and fatal here: a fabricated 0.0 can never trip the
        # always-negative pause threshold, so the verdict would state "no rail
        # here would refuse it" on nothing.
        monitor_pct: float | None = None
        if monitor is not None and state is not None:
            if getattr(state, "day_start_equity", 0.0) > 0:
                monitor_pct = monitor.day_pnl_pct(equity)
        day_pnl_pct = resolve_day_pnl_pct(
            broker_pct=account_snapshot.balances.day_pnl_pct,
            monitor_pct=monitor_pct,
        )
        if equity is None or cash is None or day_pnl_pct is None:
            # The Dashboard's own `_refresh` bails identically when equity is
            # unknown - a verdict computed from an assumed figure would guess,
            # which `position_view.py` forbids of itself: "a value this module
            # cannot support is `None`, never `0` or `0.0`".
            return None, None
        account = AccountState(equity=equity, cash=cash, day_pnl_pct=day_pnl_pct)

        resting_stops = runtime.oms.position_stops()
        entries = (
            runtime.signal_bridge.position_entries() if runtime.signal_bridge is not None else {}
        )
        views = build_position_views(
            positions=positions,
            entries=entries,
            resting_stops=resting_stops,
            # The SAME derivation the aggregate cap is gated on - never
            # recomputed here.
            snapshot=runtime.risk_engine.governor.snapshot(positions, resting_stops, equity),
            settings=runtime.settings,
            bars_for=lambda s: bars_for(runtime, s),
            strategies=runtime.available_strategies,
            clock=lambda: datetime.now(UTC),
        )
        view = next((v for v in views if v.symbol == symbol), None)

        # The DEPLOYED set, not the available one (M136) - what the verdict
        # reports is whether the rails would refuse a real order, and only a
        # deployed strategy could ever place one.
        by_name = {s.name: s for s in runtime.available_strategies}
        deployed = [
            by_name[name] for name in runtime.settings.deployed_strategies_tuple if name in by_name
        ]

        gate = getattr(runtime, "autonomy_gate", None)
        if gate is None:
            gate = AutonomyGate(runtime.settings, runtime.kill_switch)

        verdict = build_verdict(
            symbol=symbol,
            positions=positions,
            position_views=views,
            strategies=deployed,
            strategy_engine=runtime.strategy_engine,
            gate=gate,
            account=account,
            entry_refusal=runtime.oms.entry_permitted,
            is_quarantined=runtime.oms.anomalies.is_quarantined,
            settings=runtime.settings,
            last_price=view.last_price if view is not None else None,
            now=datetime.now(UTC),
        )
        return verdict, view
    except Exception:
        # WARNING for the same reason `gather` uses it: a verdict block that is
        # silently absent reads as "no rail would refuse this".
        logger.warning(
            "Could not build the symbol verdict for %s - the verdict block will be "
            "absent, which is NOT the same as no rail refusing",
            symbol,
            exc_info=True,
        )
        return None, None
