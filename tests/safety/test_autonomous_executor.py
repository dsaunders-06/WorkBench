"""AutonomousExecutor (spec M13) - the acting half of unattended execution.

The gate tests cover what may be decided; these cover what actually reaches
the broker, and what gets written down about it either way.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import AccountSummary, Order, Position
from qat.domain.autonomy.executor import AUTONOMOUS_OPERATOR, AutonomousExecutor
from qat.domain.autonomy.gate import AutonomyGate
from qat.domain.bus import EventBus
from qat.domain.decision_journal import DecisionJournal
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

_NY = ZoneInfo("America/New_York")
OPEN_US = datetime(2026, 7, 23, 10, 30, tzinfo=_NY)
CLOSED_US = datetime(2026, 7, 23, 18, 0, tzinfo=_NY)


class _Broker:
    def __init__(self, cash: float = 100_000.0, equity: float = 100_000.0) -> None:
        self.cash = cash
        self.equity = equity
        self.placed: list[Order] = []
        self.account_calls = 0
        self.quote: float | None = 100.0

    async def get_market_data(self, symbol: str) -> dict[str, float]:
        if self.quote is None:
            raise NotImplementedError("execution only")
        return {"last": self.quote, "ask": self.quote}

    async def get_historical(self, symbol: str, bars: int) -> list[dict[str, float]]:
        raise NotImplementedError

    async def place_order(self, order: Order) -> Order:
        self.placed.append(order)
        order.status = "filled"
        order.filled_price = order.reference_price or 100.0
        return order

    async def modify_order(self, order_id: str, **changes: object) -> Order:
        raise NotImplementedError

    async def cancel_order(self, order_id: str) -> Order:
        raise NotImplementedError

    async def positions(self) -> list[Position]:
        return []

    async def account(self) -> AccountSummary:
        self.account_calls += 1
        return AccountSummary(net_liquidation=self.equity, cash=self.cash, buying_power=self.cash)


def _settings(**overrides) -> Settings:
    base = {
        "_env_file": None,
        "execution_mode": "auto",
        "autonomous_strategies": "swing",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _candidate(symbol: str = "AAPL", strategy: str | None = "swing") -> OrderCandidate:
    dates = pd.date_range("2024-01-01", periods=30)
    return OrderCandidate(
        symbol=symbol,
        side="buy",
        price=100.0,
        atr=2.0,
        win_rate=0.6,
        win_loss_ratio=2.0,
        candidate_returns=pd.Series([0.001] * 30, index=dates),
        strategy=strategy,
    )


def _build(tmp_path, settings: Settings, broker: _Broker | None = None, now=OPEN_US):
    broker = broker or _Broker()
    bus = EventBus()
    switch = KillSwitch()
    risk_engine = RiskEngine(bus, switch, settings=settings)
    oms = OMS(broker, risk_engine, switch, max_order_pct_of_cash=1.0, bus=bus)
    gate = AutonomyGate(settings, switch, clock=lambda: now)
    journal = DecisionJournal(tmp_path)
    executor = AutonomousExecutor(bus, oms, gate, journal, settings=settings)
    return broker, bus, oms, switch, journal, executor


# --- Recommend mode -----------------------------------------------------------


@pytest.mark.asyncio
async def test_recommend_mode_leaves_the_order_pending_and_never_reaches_the_broker(tmp_path):
    settings = _settings(execution_mode="recommend")
    broker, _, oms, _, journal, executor = _build(tmp_path, settings)
    await executor.start()

    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})

    assert order.status == "pending_signoff"
    assert broker.placed == []
    assert journal.entries() == [], "recommend mode should not even journal - it never engaged"


@pytest.mark.asyncio
async def test_the_shipped_default_does_not_auto_execute(tmp_path):
    """Built from defaults, with nothing configured: nothing self-approves."""
    settings = Settings(_env_file=None)
    broker, _, oms, _, _, executor = _build(tmp_path, settings)
    await executor.start()

    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})

    assert order.status == "pending_signoff"
    assert broker.placed == []


# --- Auto mode ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_mode_signs_off_a_qualifying_order(tmp_path):
    broker, _, oms, _, journal, executor = _build(tmp_path, _settings())
    await executor.start()

    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})

    assert oms.get_order(order.order_id).status == "filled"
    assert len(broker.placed) == 1
    rows = journal.entries()
    assert len(rows) == 1
    assert rows[0]["outcome"] == "auto_signed"
    assert rows[0]["strategy"] == "swing"


@pytest.mark.asyncio
async def test_an_auto_signed_order_is_attributed_to_the_executor_not_a_person(tmp_path, caplog):
    broker, _, oms, _, _, executor = _build(tmp_path, _settings())
    await executor.start()

    with caplog.at_level("INFO"):
        await oms.submit_order(_candidate(), 100_000.0, {}, {})

    assert AUTONOMOUS_OPERATOR in caplog.text


@pytest.mark.asyncio
async def test_a_closed_market_leaves_the_order_for_a_human(tmp_path):
    broker, _, oms, _, journal, executor = _build(tmp_path, _settings(), now=CLOSED_US)
    await executor.start()

    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})

    assert oms.get_order(order.order_id).status == "pending_signoff"
    assert broker.placed == []
    rows = journal.entries()
    assert rows[0]["outcome"] == "blocked"
    assert "closed" in rows[0]["reason"]


@pytest.mark.asyncio
async def test_an_unpromoted_strategy_leaves_the_order_for_a_human(tmp_path):
    broker, _, oms, _, journal, executor = _build(tmp_path, _settings())
    await executor.start()

    order = await oms.submit_order(_candidate(strategy="momentum"), 100_000.0, {}, {})

    assert oms.get_order(order.order_id).status == "pending_signoff"
    assert broker.placed == []
    assert journal.entries()[0]["outcome"] == "blocked"


# --- The per-order freshness requirement --------------------------------------


@pytest.mark.asyncio
async def test_account_state_is_fetched_for_every_order_not_once_per_batch(tmp_path):
    """The documented cause of a real margin loan: several orders in one cycle
    all costed against the same stale balance."""
    broker, _, oms, _, _, executor = _build(tmp_path, _settings())
    await executor.start()

    for symbol in ("AAPL", "MSFT", "NVDA"):
        await oms.submit_order(_candidate(symbol=symbol), 100_000.0, {}, {})

    assert len(broker.placed) == 3
    # Each order: one fetch by the executor for the gate, one by OMS at
    # sign-off, one by submit_order's own cash check. The number that matters
    # is that it scales with orders rather than staying flat.
    assert broker.account_calls >= 3 * 3


@pytest.mark.asyncio
async def test_cash_exhausted_partway_through_stops_the_later_orders(tmp_path):
    """The rail has to hold under a cluster of signals, not just one at a time.

    Note where the second order dies: the RiskEngine's own cash check rejects
    it at submission, so it never becomes pending and the autonomy gate never
    sees it. That is the correct layering - but it does mean this rejection
    lands in the RiskEngine AuditLog rather than the decision journal, so a
    "why did nothing trade today" review needs both.
    """
    broker = _Broker(cash=100_000.0)
    _, _, oms, _, journal, executor = _build(tmp_path, _settings(), broker=broker)
    await executor.start()

    first = await oms.submit_order(_candidate(symbol="AAPL"), 100_000.0, {}, {})
    broker.cash = 5.0  # a fill elsewhere drained the account
    second = await oms.submit_order(_candidate(symbol="MSFT"), 100_000.0, {}, {})

    assert first.status == "filled"
    assert second.status == "rejected", "the no-leverage check must stop it at submission"
    assert [order.symbol for order in broker.placed] == ["AAPL"]
    assert [row["outcome"] for row in journal.entries()] == ["auto_signed"]


@pytest.mark.asyncio
async def test_cash_drained_after_submission_is_caught_at_sign_off(tmp_path):
    """The other half of the same rail: an order that was affordable when
    sized but is not when approved. This one does reach the autonomy gate, so
    the block is journalled."""
    broker = _Broker(cash=100_000.0)
    _, _, oms, _, journal, executor = _build(
        tmp_path, _settings(execution_mode="recommend"), broker=broker
    )
    await executor.start()
    order = await oms.submit_order(_candidate(symbol="AAPL"), 100_000.0, {}, {})
    assert order.status == "pending_signoff"

    broker.cash = 5.0
    signed = await oms.sign_off(order.order_id, operator="human")

    assert signed.status == "rejected"
    assert broker.placed == []


# --- Failure behaviour --------------------------------------------------------


@pytest.mark.asyncio
async def test_an_evaluation_failure_leaves_the_order_pending(tmp_path):
    """Fail closed: a broken gate must not become an open one."""
    broker, _, oms, _, journal, executor = _build(tmp_path, _settings())
    await executor.start()

    def _explode(*args, **kwargs):
        raise RuntimeError("gate is broken")

    executor.gate.evaluate = _explode  # type: ignore[method-assign]

    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})

    assert oms.get_order(order.order_id).status == "pending_signoff"
    assert broker.placed == []
    rows = journal.entries()
    assert rows[0]["outcome"] == "blocked"
    assert "left pending" in rows[0]["reason"]


@pytest.mark.asyncio
async def test_a_kill_switch_tripped_mid_flight_blocks_at_oms_and_is_journalled(tmp_path):
    """The gate and OMS both check the switch; this covers it flipping between
    the two, which is the only reason the OMS check is not redundant."""
    broker, _, oms, switch, journal, executor = _build(tmp_path, _settings())
    await executor.start()

    original = executor.gate.evaluate

    def _trip_then_evaluate(*args, **kwargs):
        decision = original(*args, **kwargs)
        switch.trip("tripped between the gate and sign-off")
        return decision

    executor.gate.evaluate = _trip_then_evaluate  # type: ignore[method-assign]

    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})

    assert oms.get_order(order.order_id).status == "rejected"
    assert broker.placed == []
    assert journal.entries()[0]["outcome"] == "blocked_by_oms"


# --- Journalling --------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_journal_records_the_entity_name_and_context(tmp_path):
    broker, _, oms, _, journal, executor = _build(tmp_path, _settings())
    await executor.start()

    await oms.submit_order(_candidate(symbol="AAPL"), 100_000.0, {}, {})

    row = journal.entries()[0]
    assert row["entity_name"] == "Apple Inc."
    assert row["market"] == "US"
    assert row["session_phase"] == "Morning Trend"
    assert row["execution_mode"] == "auto"
    assert float(row["equity"]) == 100_000.0


@pytest.mark.asyncio
async def test_blocked_and_executed_decisions_share_one_journal(tmp_path):
    """A journal of only what fired cannot tell a quiet day from a halted one."""
    broker, _, oms, _, journal, executor = _build(tmp_path, _settings())
    await executor.start()

    await oms.submit_order(_candidate(symbol="AAPL"), 100_000.0, {}, {})
    await oms.submit_order(_candidate(symbol="MSFT", strategy="momentum"), 100_000.0, {}, {})

    rows = journal.entries()
    assert [row["outcome"] for row in rows] == ["auto_signed", "blocked"]
    assert [row["symbol"] for row in rows] == ["AAPL", "MSFT"]


def test_the_journal_survives_a_missing_file(tmp_path):
    assert DecisionJournal(tmp_path / "does-not-exist").entries() == []
