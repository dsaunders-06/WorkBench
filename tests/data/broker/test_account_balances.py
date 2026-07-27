"""Account balances and the shared poller (spec M21).

The figures here are read from a live Alpaca paper account, not invented, so
the translation is tested against the shapes the API really returns - including
the three fields it declines to answer.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.data.broker.account_poller import STALE_AFTER_SECONDS, AccountPoller
from qat.data.broker.adapter import (
    AccountBalances,
    AccountSummary,
    Position,
    balances_from_summary,
)
from qat.data.broker.alpaca_adapter import AlpacaAdapter
from qat.data.broker.mock_broker import MockBroker


class FakeAlpacaAccount:
    """The live shape: numbers as strings, three fields genuinely absent."""

    equity = "100481.55"
    last_equity = "100415.94"
    cash = "69845.06"
    buying_power = "365162.41"
    regt_buying_power = "170326.61"
    daytrading_buying_power = None
    non_marginable_buying_power = "85163.3"
    long_market_value = "30636.49"
    short_market_value = "0"
    initial_margin = "15318.25"
    maintenance_margin = "9190.95"
    sma = "100283.95"
    accrued_fees = "0"
    multiplier = "4"
    currency = "USD"
    daytrade_count = None
    pattern_day_trader = None
    trading_blocked = False
    account_blocked = False
    shorting_enabled = True

    class _Status:
        value = "ACTIVE"

    status = _Status()


class FakeAlpacaClient:
    def __init__(self, account=None) -> None:
        self._account = account if account is not None else FakeAlpacaAccount()
        self.account_calls = 0

    def get_account(self):
        self.account_calls += 1
        return self._account

    def get_all_positions(self):
        return []


def _adapter(client: FakeAlpacaClient | None = None) -> AlpacaAdapter:
    return AlpacaAdapter(
        client=client or FakeAlpacaClient(),
        settings=Settings(_env_file=None, broker="alpaca", trading_mode="paper"),
    )


# --- translation -------------------------------------------------------------


async def test_the_balance_sheet_is_translated_from_the_broker():
    balances = await _adapter().balances()

    assert balances.equity == pytest.approx(100_481.55)
    assert balances.cash == pytest.approx(69_845.06)
    assert balances.buying_power == pytest.approx(365_162.41)
    assert balances.long_market_value == pytest.approx(30_636.49)
    assert balances.maintenance_margin == pytest.approx(9_190.95)
    assert balances.multiplier == pytest.approx(4.0)
    assert balances.status == "ACTIVE"


async def test_unreported_fields_stay_none_rather_than_becoming_zero():
    """A day-trade count Alpaca did not report is not a count of zero, and
    showing 0 would be a quiet claim about pattern-day-trader status."""
    balances = await _adapter().balances()

    assert balances.daytrade_count is None
    assert balances.pattern_day_trader is None
    assert balances.daytrading_buying_power is None


async def test_the_cash_rule_still_sees_a_concrete_number():
    """account() must keep coercing to float: a buy must not proceed on an
    unknown balance, so 0.0 is the right answer there and None is not."""
    summary = await _adapter().account()

    assert isinstance(summary.cash, float)
    assert summary.cash == pytest.approx(69_845.06)


# --- derived figures ---------------------------------------------------------


def test_the_day_pnl_uses_the_brokers_own_previous_close():
    balances = AccountBalances(equity=100_481.55, last_equity=100_415.94)

    assert balances.day_pnl == pytest.approx(65.61)
    assert balances.day_pnl_pct == pytest.approx(65.61 / 100_415.94)


def test_the_day_pnl_is_unavailable_without_a_previous_close():
    assert AccountBalances(equity=100_000.0).day_pnl is None
    assert AccountBalances(equity=100_000.0).day_pnl_pct is None


def test_spendable_cash_is_the_app_rule_not_the_brokers():
    """Alpaca offers four times cash as buying power; this application refuses
    anything above cash less the reserve. The gap is the point."""
    balances = AccountBalances(cash=69_845.06, buying_power=365_162.41)

    assert balances.spendable_cash(1.0) == pytest.approx(69_844.06)
    assert balances.spendable_cash(1.0) < balances.buying_power / 4


def test_spendable_cash_never_goes_negative():
    assert AccountBalances(cash=0.5).spendable_cash(1.0) == 0.0


def test_spendable_cash_is_unavailable_when_cash_is():
    assert AccountBalances().spendable_cash(1.0) is None


def test_a_summary_only_broker_reports_what_it_knows_and_no_more():
    balances = balances_from_summary(
        AccountSummary(net_liquidation=100.0, cash=40.0, buying_power=40.0)
    )

    assert balances.equity == 100.0
    assert balances.maintenance_margin is None  # not fabricated


async def test_the_mock_broker_does_not_invent_margin_figures():
    """Otherwise the panel would look identical whether or not a real broker
    was connected."""
    balances = await MockBroker(seed=1).balances()

    assert balances.equity is not None
    assert balances.initial_margin is None
    assert balances.status == "SIMULATED"


# --- the shared poller -------------------------------------------------------


class CountingBroker:
    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    async def account(self) -> AccountSummary:
        self.calls += 1
        if self.fail:
            raise RuntimeError("rate limited")
        return AccountSummary(net_liquidation=100.0, cash=40.0, buying_power=160.0)

    async def balances(self) -> AccountBalances:
        return AccountBalances(equity=100.0, cash=40.0, buying_power=160.0)

    async def positions(self) -> list[Position]:
        return [Position(symbol="AAPL", quantity=1.0, avg_price=100.0)]


async def test_repeated_reads_inside_the_interval_hit_the_broker_once():
    """The whole reason this exists: the Dashboard's 2s timer was spending 60
    requests a minute of a 200-per-minute budget on repainting."""
    broker = CountingBroker()
    poller = AccountPoller(broker, interval_seconds=60.0)  # type: ignore[arg-type]

    for _ in range(10):
        await poller.snapshot()

    assert broker.calls == 1


async def test_a_forced_read_bypasses_the_cache():
    broker = CountingBroker()
    poller = AccountPoller(broker, interval_seconds=60.0)  # type: ignore[arg-type]

    await poller.snapshot()
    await poller.snapshot(force=True)

    assert broker.calls == 2


async def test_an_expired_interval_refetches():
    broker = CountingBroker()
    poller = AccountPoller(broker, interval_seconds=0.0)  # type: ignore[arg-type]

    await poller.snapshot()
    await poller.snapshot()

    assert broker.calls == 2


async def test_a_broker_failure_serves_the_last_good_reading_with_its_real_age():
    """Blanking the panel would be its own lie - the money did not disappear.
    What must not happen is a stale number presented as current."""
    broker = CountingBroker()
    poller = AccountPoller(broker, interval_seconds=0.0)  # type: ignore[arg-type]
    good = await poller.snapshot()

    broker.fail = True
    degraded = await poller.snapshot()

    assert degraded.balances.equity == good.balances.equity
    assert degraded.error is not None
    assert degraded.taken_at == good.taken_at  # not refreshed to now
    assert "rate limited" in degraded.age_line()


async def test_a_first_read_that_fails_reports_nothing_rather_than_zeros():
    poller = AccountPoller(CountingBroker(fail=True), interval_seconds=0.0)  # type: ignore[arg-type]

    snapshot = await poller.snapshot()

    assert snapshot.balances.equity is None
    assert snapshot.summary is None
    assert snapshot.error is not None


async def test_a_fresh_snapshot_is_not_flagged_stale():
    poller = AccountPoller(CountingBroker(), interval_seconds=60.0)  # type: ignore[arg-type]

    snapshot = await poller.snapshot()

    assert snapshot.is_stale is False
    assert snapshot.age_line().startswith("as of")


def test_the_stale_threshold_is_above_the_poll_interval():
    """Otherwise an ordinary slow response would be reported as a fault."""
    assert STALE_AFTER_SECONDS > Settings(_env_file=None).account_poll_seconds
