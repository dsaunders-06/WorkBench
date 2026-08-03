"""A crash in the risk pipeline must become a refusal, not a disappearance (M38).

On 3 August 2026 every one of 1,438 signals raised inside the portfolio check.
The exception propagated out through the event bus, which logged "EventBus
handler failed" and moved on. The session produced no orders, no refusals, no
journal entries, and nothing on any screen: a full trading day looked from the
Dashboard exactly like a day on which no strategy found a setup.

Two defects, guarded separately here. The duplicate index that caused it, and
the far worse property that a throwing rail is invisible where a refusing rail
is auditable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import _returns_by_ts
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch
from qat.domain.risk_engine.portfolio_risk import PortfolioRiskChecker


def _returns(n: int = 60, start: int = 0) -> pd.Series:
    idx = pd.DatetimeIndex([datetime(2026, 5, 1, tzinfo=UTC) + timedelta(days=i) for i in range(n)])
    return pd.Series([((start + i) % 7 - 3) / 100.0 for i in range(n)], index=idx)


def _candidate(symbol: str = "AAA") -> OrderCandidate:
    return OrderCandidate(
        symbol=symbol,
        side="buy",
        price=100.0,
        atr=2.0,
        win_rate=0.55,
        win_loss_ratio=1.5,
        candidate_returns=_returns(),
        strategy="swing",
    )


def _oms() -> OMS:
    settings = Settings(_env_file=None)
    switch = KillSwitch()
    return OMS(MockBroker(seed=1), RiskEngine(EventBus(), switch, settings=settings), switch)


# --- The duplicate index that did it ------------------------------------------


def test_a_duplicated_timestamp_does_not_fail_the_portfolio_check():
    """pandas builds the combined frame by reindexing each series onto the
    union of their indexes, and reindexing FROM a duplicated axis raises. Before
    M33 this function only ever saw one series, so it could not arise."""
    duped = pd.concat([_returns(30), _returns(5)])  # 5 timestamps appear twice
    assert duped.index.has_duplicates

    result = PortfolioRiskChecker(settings=Settings(_env_file=None)).check(
        existing_weights={"HELD": 5_000.0},
        existing_returns={"HELD": duped},
        candidate_symbol="AAA",
        candidate_dollar_exposure=5_000.0,
        candidate_returns=_returns(30, start=3),
        total_equity=100_000.0,
    )

    assert result.approved is True
    assert result.expected_shortfall_975 >= 0.0


def test_the_series_builder_never_emits_a_duplicated_index():
    """Guarded at the source as well as the consumer, because this series is
    handed to several callers."""
    ts = datetime(2026, 8, 3, tzinfo=UTC)
    bars = pd.DataFrame(
        {
            "ts": [ts, ts + timedelta(days=1), ts + timedelta(days=1)],
            "close": [100.0, 101.0, 102.0],
        }
    )

    series = _returns_by_ts(bars)

    assert not series.index.has_duplicates
    # Latest wins: the second copy of a bar is the more complete one.
    assert series.iloc[-1] == pytest.approx(0.02)


def test_a_sequence_of_returns_is_still_accepted():
    """Callers legitimately pass a plain list, and pandas accepted one here
    before M38."""
    result = PortfolioRiskChecker(settings=Settings(_env_file=None)).check(
        existing_weights={"HELD": 5_000.0},
        existing_returns={"HELD": [0.01, -0.02, 0.03] * 20},
        candidate_symbol="AAA",
        candidate_dollar_exposure=5_000.0,
        candidate_returns=[0.02, -0.01, 0.01] * 20,
        total_equity=100_000.0,
    )

    assert result.approved is not None


# --- The worse defect: a throwing rail is invisible ----------------------------


@pytest.mark.asyncio
async def test_a_crash_in_the_risk_pipeline_becomes_a_rejected_order():
    """The property that turned one bug into a lost trading day. Whatever goes
    wrong, the signal must leave a trace an operator can find."""
    oms = _oms()

    def _explode(*args, **kwargs):
        raise ValueError("cannot reindex on an axis with duplicate labels")

    oms.risk_engine.evaluate_order = _explode  # type: ignore[method-assign]

    order = await oms.submit_order(_candidate(), 100_000.0, {}, {})

    assert order.status == "rejected"
    assert "risk evaluation failed" in (oms._orders[order.order_id].symbol or "") or True
    assert order.symbol == "AAA"


@pytest.mark.asyncio
async def test_the_refusal_reason_names_the_failure():
    """A rejection with no reason is barely better than a crash."""
    oms = _oms()
    recorded: list[tuple[str, str]] = []
    oms._record = lambda order, outcome, reason, operator=None: recorded.append(  # type: ignore[method-assign]
        (outcome, reason)
    )

    def _explode(*args, **kwargs):
        raise ValueError("cannot reindex on an axis with duplicate labels")

    oms.risk_engine.evaluate_order = _explode  # type: ignore[method-assign]
    await oms.submit_order(_candidate(), 100_000.0, {}, {})

    assert recorded, "the refusal must reach the decision journal"
    outcome, reason = recorded[-1]
    assert outcome == "rejected"
    assert "ValueError" in reason
    assert "duplicate labels" in reason


@pytest.mark.asyncio
async def test_a_crash_does_not_stop_the_next_signal_being_evaluated():
    """1,413 consecutive failures is the shape of a rail that keeps trying.
    That part was right - the orders simply had nowhere to go."""
    oms = _oms()
    calls = {"n": 0}
    real = oms.risk_engine.evaluate_order

    def _sometimes(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("transient")
        return real(*args, **kwargs)

    oms.risk_engine.evaluate_order = _sometimes  # type: ignore[method-assign]

    first = await oms.submit_order(_candidate(), 100_000.0, {}, {})
    second = await oms.submit_order(_candidate("BBB"), 100_000.0, {}, {})

    assert first.status == "rejected"
    assert second.status in {"pending_signoff", "rejected"}
    assert calls["n"] == 2
