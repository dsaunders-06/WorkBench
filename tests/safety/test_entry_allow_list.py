"""Restricting which symbols may be ENTERED, without touching exits.

Built for deliberate machinery testing: to observe a corporate action the app
has to hold the affected name, and with the caps widened to admit it the
strategy would otherwise be free to open anything else in the same session.

**Entry-only, and that is the whole point.** `symbol_allow_list` already exists
on the OMS and gates `submit_order` AND `submit_exit_order`, so pointing it at
one symbol would refuse exits on every other position in the book - a gate that
silently suppresses the only route to selling, which is exactly the shape M56c
was a defect for. This list gates entries and nothing else.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import AccountSummary, Position
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _Broker:
    def __init__(self, positions: dict[str, float]) -> None:
        self._positions = dict(positions)

    async def positions(self) -> list[Position]:
        return [
            Position(symbol=symbol, quantity=quantity, avg_price=100.0)
            for symbol, quantity in self._positions.items()
        ]

    async def resting_stops(self) -> dict[str, float]:
        return {}

    async def recent_fills(self, since):
        return []

    async def account(self) -> AccountSummary:
        # Reached only on the ADMITTED path, which is the point of the control
        # test: an entry that is allowed must carry on into ordinary sizing.
        return AccountSummary(net_liquidation=100_000.0, cash=100_000.0, buying_power=100_000.0)


def _build(tmp_path, allow: str, positions: dict[str, float] | None = None):
    settings = Settings(_env_file=None, data_dir=str(tmp_path), entry_allow_list=allow)
    bus = EventBus()
    switch = KillSwitch()
    oms = OMS(
        _Broker(positions or {}),
        RiskEngine(bus, switch, settings=settings),
        switch,
        settings=settings,
        entry_allow_list=settings.entry_allow_list_set(),
    )
    return oms


def _candidate(symbol: str) -> OrderCandidate:
    return OrderCandidate(
        symbol=symbol,
        side="buy",
        price=100.0,
        atr=5.0,
        win_rate=0.55,
        win_loss_ratio=1.8,
        candidate_returns=pd.Series([0.01, -0.005, 0.02]),
        stop_price=94.0,
    )


async def _submit(oms: OMS, symbol: str):
    return await oms.submit_order(
        _candidate(symbol), equity=100_000.0, existing_weights={}, existing_returns={}
    )


def test_the_parser_takes_a_comma_separated_string() -> None:
    settings = Settings(_env_file=None, entry_allow_list=" mnst , aapl ")

    assert settings.entry_allow_list_set() == {"MNST", "AAPL"}


def test_an_empty_list_means_no_restriction() -> None:
    """The default, and it must stay the default. An allow-list that defaults
    to restricting would silently stop the book trading."""
    assert Settings(_env_file=None).entry_allow_list_set() is None


@pytest.mark.asyncio
async def test_an_entry_off_the_list_is_refused(tmp_path):
    oms = _build(tmp_path, allow="MNST")

    order = await _submit(oms, "AAPL")

    assert order.status == "rejected"


@pytest.mark.asyncio
async def test_an_entry_on_the_list_is_admitted(tmp_path):
    """The control. Without this the test above passes for any reason at all."""
    oms = _build(tmp_path, allow="MNST")

    order = await _submit(oms, "MNST")

    assert order.status != "rejected"


@pytest.mark.asyncio
async def test_an_exit_on_a_symbol_off_the_list_is_still_allowed(tmp_path):
    """The one that matters.

    Ten positions are held while the list names one symbol. If this list gated
    exits, every one of them would become unsellable through the app - the
    failure M56c was, arriving through a feature meant only to keep a test
    tidy.
    """
    oms = _build(tmp_path, allow="MNST", positions={"AAPL": 50.0})

    order = await oms.submit_exit_order("AAPL", quantity=50.0, price=100.0, reason="signal")

    assert order.status == "pending_signoff"
    assert order.quantity == 50.0


@pytest.mark.asyncio
async def test_a_delever_trim_off_the_list_is_still_allowed(tmp_path):
    """A trim reduces risk. An ENTRY restriction has no business blocking it."""
    oms = _build(tmp_path, allow="MNST", positions={"AAPL": 50.0})

    order = await oms.submit_exit_order("AAPL", quantity=10.0, price=100.0, reason="delever")

    assert order.status == "pending_signoff"


@pytest.mark.asyncio
async def test_no_list_leaves_entries_untouched(tmp_path):
    """Default behaviour, asserted so the feature cannot quietly become
    load-bearing for the ordinary book."""
    oms = _build(tmp_path, allow="")

    order = await _submit(oms, "AAPL")

    assert order.status != "rejected"


def test_the_runtime_actually_reads_the_setting(tmp_path):
    """The question this project has had to ask three times now - of the
    minimum hold, the expertise level and the whole M37 diagnostic set: when
    something is added, what reads it?

    A setting that persists, displays and changes nothing is the failure mode
    here, and it does not show up as a failing test unless one asks directly.
    """
    from qat.presentation.runtime import Runtime

    runtime = Runtime.build_demo(
        settings=Settings(_env_file=None, data_dir=str(tmp_path), entry_allow_list="MNST")
    )

    assert runtime.oms.entry_allow_list == {"MNST"}


def test_the_runtime_leaves_it_unset_by_default(tmp_path):
    from qat.presentation.runtime import Runtime

    runtime = Runtime.build_demo(settings=Settings(_env_file=None, data_dir=str(tmp_path)))

    assert runtime.oms.entry_allow_list is None
