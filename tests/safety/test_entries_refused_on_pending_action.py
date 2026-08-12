"""A pending split expires the size basis, so entries wait (M39, R2).

Both the share count and the per-share price are about to change, so a size
computed now is computed against numbers with a known expiry.

Refusing strictly MORE than before is what keeps this inside the validation
freeze - the same argument M60 was accepted under. Which means the exit path
must be untouched: a rail whose effect is "the account may not de-risk" is a
broken rail, and M56c is the milestone that exists because one was.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.domain.bus import EventBus
from qat.domain.corporate_actions.announcements import Announcement
from qat.domain.corporate_actions.detector import PendingAction
from qat.domain.decision_journal import DecisionJournal
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _StubMonitor:
    def __init__(self, symbols: set[str]) -> None:
        self._symbols = symbols

    def pending_action(self, symbol: str) -> PendingAction | None:
        if symbol not in self._symbols:
            return None
        return PendingAction(
            announcement=Announcement(
                symbol=symbol,
                ex_date=date(2026, 8, 11),
                ratio=2.0,
                action_id="ca-1",
                payable_date=None,
                fetched_at=datetime(2026, 8, 12, tzinfo=UTC),
            ),
            position_opened_at=datetime(2026, 8, 10, tzinfo=UTC),
            current_stop=72.68,
        )


class _Broker:
    async def positions(self) -> list[Position]:
        return [Position(symbol="MNST", quantity=8.0, avg_price=91.18)]

    async def resting_stops(self) -> dict[str, float]:
        return {"MNST": 72.68}

    async def account(self):
        from qat.data.broker.adapter import AccountSummary

        return AccountSummary(net_liquidation=100_000.0, cash=80_000.0, buying_power=80_000.0)

    async def recent_fills(self, since, symbols=None):
        return []

    async def get_market_data(self, symbol):
        return {"last": 46.30}


def _oms(tmp_path, pending: set[str]):
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    return OMS(
        _Broker(),
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
        journal=DecisionJournal(tmp_path),
        corporate_actions=_StubMonitor(pending),
    )


def _candidate(symbol: str) -> OrderCandidate:
    return OrderCandidate(
        symbol=symbol,
        side="buy",
        price=46.30,
        atr=1.5,
        win_rate=0.55,
        win_loss_ratio=1.5,
        candidate_returns=pd.Series(dtype=float),
        strategy="swing",
    )


@pytest.mark.asyncio
async def test_an_entry_is_refused_while_a_split_is_pending(tmp_path):
    oms = _oms(tmp_path, {"MNST"})

    order = await oms.submit_order(_candidate("MNST"), 100_000.0, {}, {})

    assert order.status == "rejected"


@pytest.mark.asyncio
async def test_the_refusal_reaches_the_journal_naming_the_action(tmp_path):
    """R2 in full: the reason has to be in the record, not only in a log line.

    "Refused" with no cause is what M77 existed to fix on the Blotter, and the
    journal is where a rail's reason becomes evidence rather than a message.
    """
    oms = _oms(tmp_path, {"MNST"})

    await oms.submit_order(_candidate("MNST"), 100_000.0, {}, {})

    rows = (tmp_path / "decision_journal.csv").read_text(encoding="utf-8")
    assert "MNST" in rows
    assert "2-for-1" in rows
    assert "ex-date 2026-08-11" in rows


@pytest.mark.asyncio
async def test_an_exit_is_still_allowed(tmp_path):
    """The rail must not be able to stop the account de-risking."""
    oms = _oms(tmp_path, {"MNST"})

    order = await oms.submit_exit_order("MNST", quantity=8.0, price=46.30)

    assert order.status != "rejected"


@pytest.mark.asyncio
async def test_another_symbol_is_unaffected(tmp_path):
    oms = _oms(tmp_path, {"MNST"})

    order = await oms.submit_order(_candidate("AMD"), 100_000.0, {}, {})

    assert order.status != "rejected"


@pytest.mark.asyncio
async def test_an_oms_with_no_monitor_refuses_exactly_what_it_did_before(tmp_path):
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    oms = OMS(
        _Broker(),
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
    )

    order = await oms.submit_order(_candidate("MNST"), 100_000.0, {}, {})

    assert order.status != "rejected"
