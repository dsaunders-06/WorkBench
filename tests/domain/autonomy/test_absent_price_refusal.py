"""An entry needs a price from THIS session, and absence is not staleness.

Item 33. `MarketDataFeed._check_staleness_once` skips a symbol it has never seen
- `if last is None: continue` - so a symbol that has never printed is never
marked stale, never publishes `DataStaleEvent`, and never reaches
`StrategyEngine._stale_symbols`. Nothing refused it.

⚠️ And a PRE-SESSION print is worse than the item recorded. The staleness
arithmetic would catch it - yesterday's close is ~18 hours old against a 2,100s
line - but exclusion is computed by a PERIODIC PASS while the signal that
produced the order was computed ON TICK ARRIVAL. Between the tick landing and
the next pass, an entry can be sized against data that is not today's. That is a
RACE, and a wider margin cannot close it. An assertion at the point of decision
can, which is what this file pins.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.domain.autonomy.gate import AccountState, AutonomyGate
from qat.domain.risk_engine.kill_switch import KillSwitch

_SYD = ZoneInfo("Australia/Sydney")

# ⚠️ SYDNEY, and inside the ASX continuous session. The existing gate fixture in
# tests/safety/test_autonomous_executor.py pins OPEN_US, a New York time - this
# item is about the ASX, `market_for_symbol` derives the market from the symbol,
# and a US-pinned clock asserting Sydney trading dates would pass or fail by time
# of day. That is the M120 trap in a new place.
OPEN_TODAY = datetime(2026, 8, 31, 10, 35, tzinfo=_SYD)
OPEN_NEXT = datetime(2026, 9, 1, 10, 35, tzinfo=_SYD)

PRINTED_TODAY = datetime(2026, 8, 31, 10, 1, tzinfo=_SYD)
PRINTED_YESTERDAY = datetime(2026, 8, 30, 15, 59, tzinfo=_SYD)

_ACCOUNT = AccountState(equity=1_000_000.0, cash=400_000.0, day_pnl_pct=0.0)

# ⚠️ execution_mode="auto" and the strategy PROMOTED, or an earlier gate blocks
# every order with "execution mode is 'recommend'" - including the sell, which
# would make the planted sell test pass for entirely the wrong reason.
_SETTINGS = Settings(
    _env_file=None,
    deployed_strategies="swing",
    execution_mode="auto",
    autonomous_strategies="swing",
)


def _gate(last_print, *, now=OPEN_TODAY) -> AutonomyGate:
    return AutonomyGate(
        _SETTINGS,
        KillSwitch(),
        clock=lambda: now,
        last_print_source=lambda _symbol: last_print,
    )


def _buy(symbol: str = "BHP.AX") -> Order:
    return Order(
        symbol=symbol,
        side="buy",
        quantity=100.0,
        order_id="o-1",
        strategy="swing",
        # The gate refuses anything not awaiting sign-off before it reaches any
        # other rail, so every order here must be pending_signoff or the tests
        # below pass or fail for a reason that has nothing to do with prices.
        status="pending_signoff",
    )


def _sell(symbol: str = "BHP.AX") -> Order:
    return Order(
        symbol=symbol,
        side="sell",
        quantity=100.0,
        order_id="o-2",
        status="pending_signoff",
    )


def _protective_stop(symbol: str = "BHP.AX") -> Order:
    return Order(
        symbol=symbol,
        side="sell",
        quantity=100.0,
        order_id="o-3",
        order_type="stop",
        stop_price=50.0,
        status="pending_signoff",
    )


def test_a_buy_with_no_price_at_all_this_session_is_refused() -> None:
    """The symbol has never printed. ABSENT, not stale - the staleness rail
    skips it entirely, so nothing else refuses it."""
    decision = _gate(None).evaluate(_buy(), _ACCOUNT, now=OPEN_TODAY)

    assert decision.allowed is False
    assert "no price at all this session" in decision.reason

    # ⚠️ Asserted on the CLASSIFICATION, not on the absence of the word "stale":
    # this refusal's own text says "ABSENT, not stale", so a substring check
    # would fail on the very wording that makes the distinction. What must hold
    # is that the Blotter files it separately from staleness.
    from qat.domain.evaluation.refusals import rail_of

    assert rail_of(decision.reason) == "No price this session"
    assert rail_of(decision.reason) != "Stale market data"


def test_a_buy_priced_only_before_this_session_is_refused() -> None:
    """Yesterday's close served as if current. The staleness rail would catch
    this on its NEXT periodic pass; the order was sized on tick arrival."""
    decision = _gate(PRINTED_YESTERDAY).evaluate(_buy(), _ACCOUNT, now=OPEN_TODAY)

    assert decision.allowed is False
    assert "previous session" in decision.reason


def test_a_buy_priced_this_session_is_not_refused_for_an_absent_price() -> None:
    """⚠️ THE CONTROL. Without it, a gate that refuses EVERYTHING passes both
    tests above. It asserts only that NEITHER new reason fired - other rails may
    still block this order, and that is not this file's question."""
    decision = _gate(PRINTED_TODAY).evaluate(_buy(), _ACCOUNT, now=OPEN_TODAY)

    assert "no price at all this session" not in decision.reason
    assert "previous session" not in decision.reason


def test_a_sell_is_never_refused_for_an_absent_price() -> None:
    """⚠️ PLANTED. Refusing an EXIT because the feed is quiet would strand a
    position in exactly the conditions where getting out matters - strictly
    worse than the hazard being prevented. The check sits BELOW the sell
    exemption so it cannot reach one."""
    decision = _gate(None).evaluate(_sell(), _ACCOUNT, now=OPEN_TODAY)

    assert decision.allowed is True


def test_a_protective_stop_is_never_refused_for_an_absent_price() -> None:
    """Rests GTC and executes nothing until its level trades, so it returns
    allowed above even the market-closed check. It must keep doing so."""
    decision = _gate(None).evaluate(_protective_stop(), _ACCOUNT, now=OPEN_TODAY)

    assert decision.allowed is True


def test_the_boundary_is_the_exchange_session_not_a_utc_date() -> None:
    """⚠️ BOTH SIDES. 23:59 Sydney on the 31st refuses against the 1st; 00:01
    Sydney on the 1st does not. A UTC-date implementation gets this wrong,
    which is exactly the bug M120 fixed in the unattended fixture."""
    before = datetime(2026, 8, 31, 23, 59, tzinfo=_SYD)
    after = datetime(2026, 9, 1, 0, 1, tzinfo=_SYD)

    refused = _gate(before, now=OPEN_NEXT).evaluate(_buy(), _ACCOUNT, now=OPEN_NEXT)
    allowed = _gate(after, now=OPEN_NEXT).evaluate(_buy(), _ACCOUNT, now=OPEN_NEXT)

    assert refused.allowed is False
    assert "previous session" in refused.reason
    assert "previous session" not in allowed.reason


def test_an_unwired_gate_behaves_exactly_as_before() -> None:
    """`None` disables the check, which keeps every existing call site and the
    backtester unchanged - and is precisely why the wiring test exists."""
    gate = AutonomyGate(_SETTINGS, KillSwitch(), clock=lambda: OPEN_TODAY)

    decision = gate.evaluate(_buy(), _ACCOUNT, now=OPEN_TODAY)

    assert "no price at all this session" not in decision.reason
    assert "previous session" not in decision.reason


def test_runtime_wires_the_gate_to_the_feed() -> None:
    """⚠️ A GUARD THAT IS NEVER WIRED IS INERT.

    That is items 59 and 67, and it is M156 exactly: reference_price was carried
    onto the record, persisted, read back - and never reached the lot, because
    one signature was not changed. Every test above passes with the gate
    unwired, because `last_print_source=None` disables the check by design.

    Read from source rather than by building a runtime: constructing one needs a
    broker, a feed and a Gateway. What is pinned is that the ASSIGNMENT exists.
    """
    from pathlib import Path

    import qat

    source = (Path(qat.__file__).parent / "presentation" / "runtime.py").read_text(encoding="utf-8")

    assert "autonomy_gate.last_print_source = market_data_feed.last_print_at" in source, (
        "the gate is constructed BEFORE the feed exists, so the source must be ASSIGNED "
        "after the feed is built - without that line the refusal never fires and every "
        "other test in this file still passes"
    )
