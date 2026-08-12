"""Re-arming must not fight the adjustment (M39).

`rearm_protective_stops` proposes a stop from the ENTRY record, which is by
definition the pre-split level. On a symbol with a split pending, that is
precisely the number that liquidated MNST: a sell-stop at $72.68 against a $46
market. So the re-arm defers and the corporate-action monitor adjusts the
resting stop instead.

The guard has to be narrow. A symbol with no pending action must re-arm exactly
as it did before, or this trades one unprotected-position bug for another.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.domain.bus import EventBus
from qat.domain.corporate_actions.announcements import Announcement
from qat.domain.corporate_actions.detector import PendingAction
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge, _Entry
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _StubMonitor:
    """Only the slice the bridge uses - `pending_action`."""

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


class _NakedBroker:
    """Holds positions with NO protection resting, which is the state the
    re-arm exists for."""

    def __init__(self, symbols: list[str]) -> None:
        self._symbols = symbols

    async def positions(self) -> list[Position]:
        return [Position(symbol=s, quantity=8.0, avg_price=91.18) for s in self._symbols]

    async def resting_stops(self) -> dict[str, float]:
        return {}

    async def recent_fills(self, since, symbols=None):
        return []


def _bridge(tmp_path, held: list[str], pending: set[str]):
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    oms = OMS(
        _NakedBroker(held),
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
    )
    bridge = SignalToOrderBridge(
        bus=bus,
        oms=oms,
        settings=settings,
        corporate_actions=_StubMonitor(pending),
    )
    for symbol in held:
        bridge._entries[symbol] = _Entry(
            opened_at=datetime(2026, 8, 10, tzinfo=UTC),
            price=91.18,
            stop_price=72.68,
            target_price=None,
            strategy="swing",
        )
    return bridge


@pytest.mark.asyncio
async def test_rearm_skips_a_symbol_with_a_pending_action(tmp_path):
    bridge = _bridge(tmp_path, held=["MNST"], pending={"MNST"})

    rearmed = await bridge.rearm_protective_stops()

    assert "MNST" not in rearmed


@pytest.mark.asyncio
async def test_rearm_says_why_it_skipped(tmp_path, caplog):
    """Silence here would look identical to "nothing needed doing"."""
    bridge = _bridge(tmp_path, held=["MNST"], pending={"MNST"})

    with caplog.at_level("WARNING"):
        await bridge.rearm_protective_stops()

    assert "MNST" in caplog.text
    assert "split" in caplog.text.lower()


@pytest.mark.asyncio
async def test_rearm_is_unchanged_for_everything_else(tmp_path):
    """The guard must be narrow. A symbol with no pending action re-arms exactly
    as it did before."""
    bridge = _bridge(tmp_path, held=["MNST", "AMD"], pending={"MNST"})

    rearmed = await bridge.rearm_protective_stops()

    assert "AMD" in rearmed


@pytest.mark.asyncio
async def test_a_bridge_with_no_monitor_behaves_exactly_as_before(tmp_path):
    """Every existing test and any mock run constructs the bridge without one."""
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    oms = OMS(
        _NakedBroker(["AMD"]),
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
    )
    bridge = SignalToOrderBridge(bus=bus, oms=oms, settings=settings)
    bridge._entries["AMD"] = _Entry(
        opened_at=datetime(2026, 8, 10, tzinfo=UTC),
        price=91.18,
        stop_price=72.68,
        target_price=None,
        strategy="swing",
    )

    assert "AMD" in await bridge.rearm_protective_stops()


def test_the_bridge_hands_over_open_dates_for_the_crwd_gate(tmp_path):
    """The monitor needs these and must not reach into `_entries` for them."""
    bridge = _bridge(tmp_path, held=["MNST"], pending=set())

    assert bridge.entry_open_dates() == {"MNST": datetime(2026, 8, 10, tzinfo=UTC)}
