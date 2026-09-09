"""AutonomyGate (spec M13) - the decision half of unattended execution.

Structured around the safety checklist rather than around the code: each test
names the property it protects, so a future change that breaks one gets a
failure that says what was lost, not just which line moved.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Order
from qat.domain.autonomy.gate import AccountState, AutonomyGate, market_for_symbol
from qat.domain.risk_engine.kill_switch import KillSwitch

_NY = ZoneInfo("America/New_York")
_SYD = ZoneInfo("Australia/Sydney")

# A Thursday, mid-morning: US market open, "Morning Trend" - an eligible phase.
OPEN_US = datetime(2026, 7, 23, 10, 30, tzinfo=_NY)
# Same day, just after the bell: open but in "Opening Volatility".
OPENING_BELL_US = datetime(2026, 7, 23, 9, 35, tzinfo=_NY)
MIDDAY_LULL_US = datetime(2026, 7, 23, 12, 30, tzinfo=_NY)
CLOSED_US = datetime(2026, 7, 23, 18, 0, tzinfo=_NY)
CHRISTMAS_US = datetime(2026, 12, 25, 11, 0, tzinfo=_NY)
OPEN_ASX = datetime(2026, 7, 23, 11, 0, tzinfo=_SYD)


def _settings(**overrides) -> Settings:
    base = {
        "_env_file": None,
        "execution_mode": "auto",
        "autonomous_strategies": "swing",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _order(
    side: str = "buy",
    symbol: str = "AAPL",
    quantity: float = 10.0,
    strategy: str | None = "swing",
    reference_price: float | None = 100.0,
    status: str = "pending_signoff",
    order_type: str = "market",
) -> Order:
    return Order(
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        quantity=quantity,
        order_id="test-order",
        status=status,  # type: ignore[arg-type]
        reference_price=reference_price,
        strategy=strategy,
        order_type=order_type,  # type: ignore[arg-type]
    )


def _account(day_pnl_pct: float = 0.0, cash: float = 50_000.0) -> AccountState:
    return AccountState(equity=100_000.0, cash=cash, day_pnl_pct=day_pnl_pct)


def _gate(settings: Settings | None = None, switch: KillSwitch | None = None) -> AutonomyGate:
    return AutonomyGate(settings or _settings(), switch or KillSwitch())


# --- The default must never trade unattended ----------------------------------


def test_recommend_mode_never_allows_an_order():
    """The single most important property in this file. Doing nothing must not
    get you unattended execution."""
    gate = _gate(_settings(execution_mode="recommend"))
    decision = gate.evaluate(_order(), _account(), now=OPEN_US)
    assert decision.allowed is False
    assert "recommend" in decision.reason


def test_recommend_is_the_shipped_default():
    assert Settings(_env_file=None).execution_mode == "recommend"
    assert Settings(_env_file=None).autonomy_enabled is False


def test_recommend_mode_blocks_sells_too():
    """Recommend mode means nothing self-approves - not even a protective exit."""
    gate = _gate(_settings(execution_mode="recommend"))
    decision = gate.evaluate(_order(side="sell", strategy=None), _account(), now=OPEN_US)
    assert decision.allowed is False


# --- Live accounts ------------------------------------------------------------


def test_a_live_account_blocks_autonomy_without_the_second_flag():
    gate = _gate(_settings(trading_mode="live"))
    decision = gate.evaluate(_order(), _account(), now=OPEN_US)
    assert decision.allowed is False
    assert "live account" in decision.reason


def test_autonomy_enabled_is_false_for_live_without_the_flag():
    assert _settings(trading_mode="live").autonomy_enabled is False
    assert _settings(trading_mode="live", allow_autonomous_live_trading=True).autonomy_enabled


# --- Kill switch --------------------------------------------------------------


def test_a_tripped_kill_switch_blocks_buys():
    switch = KillSwitch()
    switch.trip("daily loss limit")
    decision = _gate(switch=switch).evaluate(_order(), _account(), now=OPEN_US)
    assert decision.allowed is False
    assert "kill-switch" in decision.reason


def test_a_tripped_kill_switch_blocks_sells_as_well():
    """The kill-switch is a full halt, unlike the appetite rails - it trips on
    conditions (stale data, a reconciliation mismatch) where the system's view
    of the account cannot be trusted enough to act on at all."""
    switch = KillSwitch()
    switch.trip("broker reconciliation mismatch")
    decision = _gate(switch=switch).evaluate(_order(side="sell"), _account(), now=OPEN_US)
    assert decision.allowed is False


# --- Market hours -------------------------------------------------------------


def test_a_closed_market_blocks():
    decision = _gate().evaluate(_order(), _account(), now=CLOSED_US)
    assert decision.allowed is False
    assert "closed" in decision.reason


def test_a_public_holiday_blocks():
    """The gap the original app had: a weekday holiday read as open."""
    decision = _gate().evaluate(_order(), _account(), now=CHRISTMAS_US)
    assert decision.allowed is False
    assert "public holiday" in decision.reason


def test_opening_volatility_blocks_a_buy():
    decision = _gate().evaluate(_order(), _account(), now=OPENING_BELL_US)
    assert decision.allowed is False
    assert "not eligible" in decision.reason


def test_midday_lull_blocks_a_buy():
    decision = _gate().evaluate(_order(), _account(), now=MIDDAY_LULL_US)
    assert decision.allowed is False


def test_an_eligible_phase_allows_a_qualifying_buy():
    decision = _gate().evaluate(_order(), _account(), now=OPEN_US)
    assert decision.allowed is True
    assert decision.quantity == 10.0
    assert decision.session_phase == "Morning Trend"


def test_the_symbol_suffix_routes_to_the_right_market_calendar():
    assert market_for_symbol("BHP.AX") == "ASX"
    assert market_for_symbol("AAPL") == "US"

    gate = _gate(_settings(autonomous_strategies="swing"))
    # ASX hours: open in Sydney, and the US market is shut at that instant.
    asx_decision = gate.evaluate(_order(symbol="BHP.AX"), _account(), now=OPEN_ASX)
    us_decision = gate.evaluate(_order(symbol="AAPL"), _account(), now=OPEN_ASX)
    assert asx_decision.allowed is True
    assert us_decision.allowed is False


# --- Strategy promotion -------------------------------------------------------


def test_an_unpromoted_strategy_blocks_a_buy():
    gate = _gate(_settings(autonomous_strategies="swing"))
    decision = gate.evaluate(_order(strategy="momentum"), _account(), now=OPEN_US)
    assert decision.allowed is False
    assert "not on the autonomous list" in decision.reason


def test_no_strategy_promoted_means_nothing_trades():
    gate = _gate(_settings(autonomous_strategies=""))
    decision = gate.evaluate(_order(), _account(), now=OPEN_US)
    assert decision.allowed is False


def test_an_order_with_no_strategy_attribution_blocks():
    decision = _gate().evaluate(_order(strategy=None), _account(), now=OPEN_US)
    assert decision.allowed is False
    assert "no strategy attribution" in decision.reason


def test_promotion_is_per_strategy_not_all_or_nothing():
    gate = _gate(_settings(autonomous_strategies="swing,breakout"))
    assert gate.evaluate(_order(strategy="swing"), _account(), now=OPEN_US).allowed
    assert gate.evaluate(_order(strategy="breakout"), _account(), now=OPEN_US).allowed
    assert not gate.evaluate(_order(strategy="momentum"), _account(), now=OPEN_US).allowed


# --- Day P&L rails ------------------------------------------------------------


def test_a_bad_day_pauses_new_buys():
    decision = _gate().evaluate(_order(), _account(day_pnl_pct=-0.05), now=OPEN_US)
    assert decision.allowed is False
    assert "pause threshold" in decision.reason


def test_a_moderately_bad_day_halves_the_size():
    decision = _gate().evaluate(_order(quantity=10.0), _account(day_pnl_pct=-0.025), now=OPEN_US)
    assert decision.allowed is True
    assert decision.resized is True
    assert decision.quantity == 5.0


def test_a_normal_day_does_not_resize():
    decision = _gate().evaluate(_order(quantity=10.0), _account(day_pnl_pct=0.01), now=OPEN_US)
    assert decision.allowed is True
    assert decision.resized is False
    assert decision.quantity == 10.0


# --- Sells are not gated on appetite ------------------------------------------


def test_a_bad_day_does_not_block_a_protective_sell():
    """A rail whose effect is 'the account may not de-risk' is a broken rail."""
    decision = _gate().evaluate(
        _order(side="sell", strategy=None), _account(day_pnl_pct=-0.20), now=OPEN_US
    )
    assert decision.allowed is True


def test_an_unpromoted_strategy_does_not_block_a_sell():
    gate = _gate(_settings(autonomous_strategies=""))
    decision = gate.evaluate(_order(side="sell", strategy="momentum"), _account(), now=OPEN_US)
    assert decision.allowed is True


def test_an_ineligible_phase_does_not_block_a_sell():
    """Waiting for a prettier phase to exit a losing position is the wrong
    trade-off: the phase rule exists to protect entry quality."""
    decision = _gate().evaluate(_order(side="sell", strategy=None), _account(), now=MIDDAY_LULL_US)
    assert decision.allowed is True


def test_price_drift_does_not_block_a_sell():
    decision = _gate().evaluate(
        _order(side="sell", strategy=None), _account(), current_price=1.0, now=OPEN_US
    )
    assert decision.allowed is True


def test_a_closed_market_still_blocks_a_sell():
    """Not an appetite rail - there is simply no session to send it to."""
    decision = _gate().evaluate(_order(side="sell", strategy=None), _account(), now=CLOSED_US)
    assert decision.allowed is False


# --- Price drift --------------------------------------------------------------


def test_a_large_price_drift_blocks_a_buy():
    decision = _gate().evaluate(
        _order(reference_price=100.0), _account(), current_price=110.0, now=OPEN_US
    )
    assert decision.allowed is False
    assert "drifted" in decision.reason


def test_a_small_price_drift_is_tolerated():
    decision = _gate().evaluate(
        _order(reference_price=100.0), _account(), current_price=101.0, now=OPEN_US
    )
    assert decision.allowed is True


def test_drift_is_measured_in_both_directions():
    down = _gate().evaluate(
        _order(reference_price=100.0), _account(), current_price=85.0, now=OPEN_US
    )
    assert down.allowed is False


def test_no_quote_skips_the_drift_check_rather_than_failing_it():
    """An execution-only broker never quoting is a known configuration, not a
    fault - the order still faces every other gate."""
    decision = _gate().evaluate(_order(), _account(), current_price=None, now=OPEN_US)
    assert decision.allowed is True


# --- Order state --------------------------------------------------------------


def test_an_order_that_is_not_pending_blocks():
    decision = _gate().evaluate(_order(status="filled"), _account(), now=OPEN_US)
    assert decision.allowed is False
    assert "not pending sign-off" in decision.reason


@pytest.mark.parametrize("quantity", [0.0, -5.0])
def test_a_non_positive_quantity_blocks(quantity):
    decision = _gate().evaluate(_order(quantity=quantity), _account(), now=OPEN_US)
    assert decision.allowed is False


# --- Deny by default ----------------------------------------------------------


def test_every_block_carries_a_reason():
    """A blocked order with no explanation is unreviewable."""
    blocked = [
        _gate(_settings(execution_mode="recommend")).evaluate(_order(), _account(), now=OPEN_US),
        _gate().evaluate(_order(), _account(), now=CLOSED_US),
        _gate().evaluate(_order(strategy="nope"), _account(), now=OPEN_US),
        _gate().evaluate(_order(), _account(day_pnl_pct=-0.5), now=OPEN_US),
    ]
    for decision in blocked:
        assert decision.allowed is False
        assert decision.reason.strip()
        assert decision.quantity == 0.0


# --- A resting protective order outranks the session check (M33c) -------------


def _protective(symbol: str = "AAPL", stop: float = 95.0, target: float | None = None) -> Order:
    return Order(
        symbol=symbol,
        side="sell",
        quantity=16.0,
        order_id="protective-1",
        status="pending_signoff",
        stop_price=stop,
        take_profit_price=target,
        order_type="stop",
    )


def test_a_closed_market_does_not_block_a_resting_protective_order():
    """Found by running it. On 1 August the app detected an unprotected
    position, proposed the repair, then blocked ITSELF from applying it because
    the market was shut - while a manual sign-off of the same order was
    accepted by Alpaca without complaint, because GTC orders rest fine outside
    hours. The rail was dormant in exactly the window it exists for: brackets
    die AT the close."""
    decision = _gate().evaluate(_protective(), _account(), now=CLOSED_US)

    assert decision.allowed is True
    assert decision.quantity == 16.0


def test_a_holiday_does_not_block_a_resting_protective_order():
    decision = _gate().evaluate(_protective(target=130.0), _account(), now=CHRISTMAS_US)

    assert decision.allowed is True


def test_a_plain_sell_into_a_closed_market_is_still_blocked():
    """Deliberately narrower than "any sell". A market sell transmitted into a
    closed market is an unpriced fill at the open; a stop resting GTC executes
    nothing until its level trades."""
    decision = _gate().evaluate(_order(side="sell", strategy=None), _account(), now=CLOSED_US)

    assert decision.allowed is False
    assert "closed" in decision.reason


def test_the_kill_switch_still_outranks_a_protective_order():
    """The exemption is about the session, not about the hard stop. A tripped
    kill-switch means this app's view of the account cannot be trusted, and
    that is not a state to be placing orders from."""
    switch = KillSwitch()
    switch.trip("reconciliation mismatch")

    decision = _gate(switch=switch).evaluate(_protective(), _account(), now=CLOSED_US)

    assert decision.allowed is False
    assert "kill-switch" in decision.reason


def test_recommend_mode_still_outranks_a_protective_order():
    decision = _gate(_settings(execution_mode="recommend")).evaluate(
        _protective(), _account(), now=CLOSED_US
    )

    assert decision.allowed is False


# --- The opening auction (Stage 3) -------------------------------------------
#
# 10 September 2026 is a Thursday, and the 9 September probe reports it as a
# normal session: "20260910:0959-20260910:1611". The ASX opening auction runs
# to roughly 10:10 - a JUDGEMENT, not a measurement, because IBKR reports no
# opening auction at all.

ASX_OPENING_AUCTION = datetime(2026, 9, 10, 10, 5, tzinfo=_SYD)
ASX_CONTINUOUS = datetime(2026, 9, 10, 10, 15, tzinfo=_SYD)
ASX_CLOSING_AUCTION = datetime(2026, 9, 10, 16, 5, tzinfo=_SYD)


def test_a_market_sell_into_the_opening_auction_is_refused():
    """Sells return allowed BEFORE the session-phase check, which is correct -
    risk-reducing orders are not gated on appetite. But a market order into a
    single-price auction fills at the auction price, not a quoted one, which is
    the same unpriced fill this gate already refuses into a closed market.

    ⚠️ WHICH CALLER ACTUALLY REACHES THIS, because it is not the obvious one
    and a later reader measuring "has this rule ever fired?" will look in the
    wrong place. The yfinance feed is blind for roughly its first twenty
    minutes every session - measured live at 10:08 on 9 September, "yfinance
    returned 0 of 100 requested symbol(s)" - and a price signal is computed on
    tick arrival. So no signal-driven exit can fire inside 10:00-10:10 at all.
    The exit that gets here is the CLOCK-driven one: the time stop, or the
    escaped-hold rule that exited A2M.AX on 4 September. `Order` carries no
    exit reason, so the gate cannot tell them apart and this test cannot
    either - hence the note.
    """
    decision = _gate().evaluate(
        _order(side="sell", symbol="BHP.AX", strategy=None),
        _account(),
        now=ASX_OPENING_AUCTION,
    )
    assert decision.allowed is False
    assert "opening auction" in decision.reason


def test_the_same_sell_is_allowed_once_continuous_trading_starts():
    decision = _gate().evaluate(
        _order(side="sell", symbol="BHP.AX", strategy=None),
        _account(),
        now=ASX_CONTINUOUS,
    )
    assert decision.allowed is True


def test_a_resting_protective_order_is_still_allowed_in_the_auction():
    """This is what makes the refusal cheap. A GTC stop already rests at the
    broker and participates in the auction whether or not the app will transmit
    anything, so refusing a discretionary exit removes no protection. If this
    test fails, the block was inserted ABOVE the is_protective_stop early
    return and the repair path is dead in the window it exists for - which is
    exactly the M33c defect, one boundary further in."""
    decision = _gate().evaluate(
        _order(side="sell", symbol="BHP.AX", strategy=None, order_type="stop"),
        _account(),
        now=ASX_OPENING_AUCTION,
    )
    assert decision.allowed is True


def test_the_us_open_is_unaffected():
    """US is 0 minutes on the opening-auction table, so a US sell just after
    the bell is still allowed and this work did not narrow the US record."""
    decision = _gate().evaluate(_order(side="sell", strategy=None), _account(), now=OPENING_BELL_US)
    assert decision.allowed is True


def test_a_BUY_in_the_auction_is_refused_naming_the_auction_not_the_phase():
    """⚠️ A DELIBERATE MESSAGE CHANGE, pinned because it is easy to undo.

    A buy at 10:05 was already refused - the window sits inside Opening
    Volatility, which is excluded from unattended execution - so this changes
    no behaviour. It changes what the operator is TOLD: the exchange running a
    single-price auction is a fact about the exchange, and outranks this app's
    own risk-appetite phase as an explanation. The consequence is that
    "Opening Volatility" no longer appears as a refusal reason during the
    first ten minutes of an ASX session, which is a visible change in the
    blotter and is meant.
    """
    decision = _gate().evaluate(
        _order(side="buy", symbol="BHP.AX"), _account(), now=ASX_OPENING_AUCTION
    )
    assert decision.allowed is False
    assert "opening auction" in decision.reason


def test_the_CLOSING_auction_is_handled_by_the_closed_market_rule_and_names_itself():
    """No new rule was needed at the close: `is_open` is already False from
    16:00, so the existing closed-market refusal fires. Task 2 is what makes it
    say WHICH kind of closed - an operator reading a refusal at 16:05 is told
    the exchange is mid-auction rather than simply shut."""
    decision = _gate().evaluate(
        _order(side="sell", symbol="BHP.AX", strategy=None),
        _account(),
        now=ASX_CLOSING_AUCTION,
    )
    assert decision.allowed is False
    assert "closing auction" in decision.reason
