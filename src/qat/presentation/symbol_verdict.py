"""What this application's own rails say about one symbol, right now.

The AI Advisor answers "what should I do about BHP.AX" with a model's opinion.
This is the other half: what the SYSTEM would do, computed rather than asked,
so the operator reads the opinion beside the fact instead of inferring the fact
from the opinion. The same division `data/news.py` already draws - the
corroboration rule runs in code at the edge, never by asking the model whether
its sources agree.

**Every rail is asked of its owner.** The rails live in four subsystems and
there is no single place that answers "would this trade be allowed", so the
temptation is to reimplement the short ones here. That is precisely how two
derivations of one decision drift apart, which this codebase has met more than
once - `trading_date` with one caller out of four (M120), and
`minimum_hold_status` before it was extracted for exactly this reason.

**THE RISK ENGINE IS NEVER CALLED.** `RiskEngine.evaluate_*` writes
`risk_decisions.csv`. Asking it a hypothetical would file risk decisions for
trades nobody proposed, into the audit trail `session_check` reports on and
whose row count is a reviewed figure. So this says what the GATES say and never
what the sizer would do - and `render_caveats` prints that limit on screen
rather than leaving the operator to assume coverage.

Pure and injectable: no Qt, no I/O, no globals, no wall clock. Functions rather
than a mixin so the rules can be tested without constructing a screen - the
same reasoning `advisory_inputs` gives for living beside it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from qat.config import Settings
from qat.data.broker.adapter import Order, Position
from qat.domain import market_calendar as mc
from qat.domain.autonomy.gate import AccountState, AutonomyGate, market_for_symbol


class EligibilitySource(Protocol):
    """StrategyEngine's two public eligibility accessors, and nothing else.

    A Protocol rather than the class so this module does not import the engine
    - and so a test can supply the two answers without building one.
    """

    def is_eligible(self, strategy: Any) -> bool: ...
    def eligible_mass(self, strategy: Any) -> float | None: ...


@dataclass(frozen=True, slots=True)
class RuleCheck:
    name: str
    # None means NOT KNOWABLE NOW - never rendered as a pass or a fail. The
    # discipline `preflight` states as "a check that could not be performed is
    # not a check that passed".
    passed: bool | None
    detail: str


@dataclass(frozen=True, slots=True)
class StrategyRules:
    """The rails that depend on WHICH strategy is asking."""

    strategy: str
    checks: tuple[RuleCheck, ...]
    # The first rail that would refuse, or "" when none would. The autonomy
    # gate short-circuits, so this is honestly "the first", never "the only".
    first_refusal: str


@dataclass(frozen=True, slots=True)
class SymbolVerdict:
    symbol: str
    held: bool
    # Strategy-independent: session, allow lists, quarantine, and - on the held
    # branch - the position's own facts.
    checks: tuple[RuleCheck, ...]
    per_strategy: tuple[StrategyRules, ...]
    headline: str

    def as_dicts(self) -> list[dict[str, object]]:
        """Plain data for `AdvisoryContext`, which imports nothing from the
        rest of the domain - that is what lets the safety tests build a context
        in isolation, and it is why this crosses as dicts rather than as these
        dataclasses."""
        rows: list[dict[str, object]] = [
            {"name": c.name, "passed": c.passed, "detail": c.detail} for c in self.checks
        ]
        for rules in self.per_strategy:
            rows.extend(
                {
                    "name": f"{rules.strategy}: {c.name}",
                    "passed": c.passed,
                    "detail": c.detail,
                }
                for c in rules.checks
            )
        return rows


def build_verdict(
    *,
    symbol: str,
    positions: Sequence[Position],
    position_views: Sequence[Any],
    strategies: Sequence[Any],
    strategy_engine: EligibilitySource,
    gate: AutonomyGate,
    account: AccountState,
    entry_refusal: Callable[[str], str | None],
    is_quarantined: Callable[[str], bool],
    settings: Settings,
    last_price: float | None,
    now: datetime,
) -> SymbolVerdict:
    """The rails' own answer about `symbol`, branching on whether it is held.

    Held and unheld share almost no rails. The autonomy gate does not gate
    sells on session phase - risk-reducing orders are not held to appetite
    limits - so what binds a SELL is the minimum hold, the time stop,
    quarantine and whether protection is resting, none of which say anything
    about an entry. Reporting entry rails for a held symbol would answer the
    wrong question confidently.
    """
    held = any(p.symbol == symbol and p.quantity for p in positions)
    view = next((v for v in position_views if v.symbol == symbol), None)

    checks: list[RuleCheck] = [_session_check(symbol, now, held)]
    if held:
        checks.append(_position_check(view))
    else:
        checks.append(_allow_list_check(symbol, entry_refusal))
    checks.append(_quarantine_check(symbol, is_quarantined))

    per_strategy = tuple(
        _strategy_rules(
            strategy=strategy,
            symbol=symbol,
            held=held,
            strategy_engine=strategy_engine,
            gate=gate,
            account=account,
            last_price=last_price,
            now=now,
            symbol_checks=checks,
        )
        for strategy in strategies
    )
    return SymbolVerdict(
        symbol=symbol,
        held=held,
        checks=tuple(checks),
        per_strategy=per_strategy,
        headline=_headline(symbol, held, checks, per_strategy),
    )


def _session_check(symbol: str, now: datetime, held: bool) -> RuleCheck:
    """Mirrors `AutonomyGate.evaluate`'s own buy/sell asymmetry (gate.py
    ~146-158): a sell is risk-reducing and gated only on `is_open`, while
    session PHASE only binds buys. Reporting `is_autonomous_eligible` for a
    held symbol during Midday Lull would disagree with `_gate_check`'s
    faithful probe of the same order and would win the headline, since this
    check runs first - see the M135 finding this fixes.
    """
    session = mc.session_for(market_for_symbol(symbol), now)
    if not session.is_open:
        return RuleCheck("session", False, f"{session.market} is closed ({session.closed_reason})")
    if held:
        return RuleCheck(
            "session",
            True,
            f"{session.market} is open, phase '{session.phase}' - a sell is risk-reducing "
            "and is not gated on session phase",
        )
    return RuleCheck(
        "session",
        session.is_autonomous_eligible,
        f"{session.market} is open, phase '{session.phase}'"
        + ("" if session.is_autonomous_eligible else " - not eligible for unattended execution"),
    )


def _allow_list_check(symbol: str, entry_refusal: Callable[[str], str | None]) -> RuleCheck:
    refusal = entry_refusal(symbol)
    if refusal is None:
        return RuleCheck("allow list", True, "the allow lists permit an entry in this symbol")
    return RuleCheck("allow list", False, refusal)


def _quarantine_check(symbol: str, is_quarantined: Callable[[str], bool]) -> RuleCheck:
    if is_quarantined(symbol):
        return RuleCheck(
            "corporate action",
            False,
            "quarantined by a declared position anomaly - its recorded basis no longer "
            "explains what is held",
        )
    return RuleCheck("corporate action", True, "no declared anomaly")


def _position_check(view: Any) -> RuleCheck:
    """The held position's own facts, read from `PositionView`.

    Computes nothing: `position_view.py` already produced all of it, and its
    own docstring records why - "show nothing rather than guess", None and zero
    being different facts. That discipline is preserved by rendering an absent
    figure as "unknown" rather than as a number.
    """
    if view is None:
        return RuleCheck(
            "position",
            None,
            "held, but no position view was available - entry basis, P&L and hold state "
            "are unknown for this answer",
        )
    parts = [f"held {view.quantity:g}"]
    parts.append(
        f"entry {view.entry_price:.2f}" if view.entry_price is not None else "entry unknown"
    )
    parts.append(f"{view.pnl_r:+.2f}R" if view.pnl_r is not None else "R unknown")
    parts.append(
        f"stop {view.stop_distance:.1%} away"
        if view.stop_distance is not None
        else "NO STOP RESTING"
    )
    if view.notes:
        parts.append("; ".join(view.notes))
    # `passed` is None deliberately: a position's state is not a pass or a
    # fail. Whether it SHOULD be sold is the question being asked, not one this
    # rail answers.
    return RuleCheck("position", None, ", ".join(parts))


def _strategy_rules(
    *,
    strategy: Any,
    symbol: str,
    held: bool,
    strategy_engine: EligibilitySource,
    gate: AutonomyGate,
    account: AccountState,
    last_price: float | None,
    now: datetime,
    symbol_checks: Sequence[RuleCheck],
) -> StrategyRules:
    """The rails that depend on which strategy is asking, plus the FIRST
    refusal a hypothetical order for this strategy would meet.

    `symbol_checks` (session, allow list/position, quarantine) are not
    strategy-specific and are never added to `checks` here - repeating them
    per strategy would print the same refusal twice on a multi-strategy
    account (see `test_symbol_level_rails_are_not_repeated_per_strategy`).
    But a strategy's own hypothetical order would still be refused by a
    failing symbol-level rail before either of THIS strategy's own checks are
    reached, so they are considered - in the order they were evaluated - when
    naming the first refusal.
    """
    checks = [_regime_check(strategy, strategy_engine)]
    checks.append(_gate_check(strategy, symbol, held, gate, account, last_price, now))
    ordered = [*symbol_checks, *checks]
    refusal = next((c.detail for c in ordered if c.passed is False), "")
    return StrategyRules(strategy=strategy.name, checks=tuple(checks), first_refusal=refusal)


def _regime_check(strategy: Any, strategy_engine: EligibilitySource) -> RuleCheck:
    mass = strategy_engine.eligible_mass(strategy)
    if mass is None:
        # Before any RegimeEvent there is no distribution to read.
        # `eligible_mass`'s own docstring requires callers to present this as
        # "not yet known" rather than as a measurement.
        return RuleCheck(
            "regime",
            None,
            "not yet known - no regime has been classified in this session",
        )
    eligible = strategy_engine.is_eligible(strategy)
    return RuleCheck(
        "regime",
        eligible,
        f"{mass:.0%} of the probability mass sits in this strategy's regimes"
        + ("" if eligible else " - below the eligibility bar"),
    )


def _gate_check(
    strategy: Any,
    symbol: str,
    held: bool,
    gate: AutonomyGate,
    account: AccountState,
    last_price: float | None,
    now: datetime,
) -> RuleCheck:
    """The autonomy gate, asked with a PROBE order.

    `quantity=1` is a probe, not a size, and the distinction is load-bearing.
    The gate's own rails - execution mode, kill switch, session phase,
    promotion evidence, day P&L, price drift - do not depend on quantity beyond
    requiring it positive. The rails that DO depend on size are the OMS's
    notional cap and the sizer, and neither is asked here. So this answers the
    gate's question faithfully and answers nothing whatever about size.

    `AutonomyGate.evaluate` is documented as a pure decision function: no
    logging, no writes. That is what makes asking it a hypothetical safe.
    """
    probe = Order(
        symbol=symbol,
        side="sell" if held else "buy",
        quantity=1.0,
        order_id="verdict-probe",
        status="pending_signoff",
        reference_price=last_price,
        strategy=strategy.name,
        # Without this, Order.created_at defaults to datetime.now(UTC) - a
        # wall-clock read this module's own docstring forbids. `now` is
        # already the injected clock for everything else this function does.
        created_at=now,
    )
    decision = gate.evaluate(probe, account, current_price=last_price, now=now)
    verb = "sell" if held else "entry"
    if decision.allowed:
        return RuleCheck("autonomy gate", True, f"an unattended {verb} would be permitted now")
    return RuleCheck("autonomy gate", False, decision.reason)


def _headline(
    symbol: str,
    held: bool,
    checks: Sequence[RuleCheck],
    per_strategy: Sequence[StrategyRules],
) -> str:
    """A conditional about what WOULD happen, never a suggestion.

    M73's framing says these recommendations reach no part of the trading
    system, and a verdict is the opposite kind of statement - it IS that
    system's state. Left ambiguous, "the rails would permit a buy" printed
    under "[BUY, confidence 80%]" reads as the application endorsing a trade,
    which is the inference M73 exists to prevent. So the sentence is always
    about a hypothetical order, and never about what the operator should do.
    """
    verb = "sell" if held else "entry"
    blocking = [c.detail for c in checks if c.passed is False]
    blocking.extend(rules.first_refusal for rules in per_strategy if rules.first_refusal)
    if blocking:
        return (
            f"If a {verb} in {symbol} were proposed now, the first rail to refuse "
            f"would be: {blocking[0]}"
        )
    return (
        f"If a {verb} in {symbol} were proposed now, no rail checked here would refuse it. "
        "Sizing is not checked."
    )


def render_caveats() -> str:
    """What the verdict did NOT check, printed rather than assumed.

    A panel listing rails invites the reading that it listed all of them. Three
    are deliberately absent and one is not a permission rule at all, and an
    operator cannot infer any of that from rows that are simply missing.
    """
    return (
        "Not checked: position SIZE, because the sizer writes to the risk audit trail and "
        "this screen must not; price staleness, decided at order time against a live tick; "
        "and the per-order notional cap. The earnings blackout is not a permission rule - "
        "it scales SIZE near a results date."
    )
