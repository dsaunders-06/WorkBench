"""Two messages that asserted something checkable and false (M82).

Found by taking every distinct message the live run emitted and testing its
claims against the record it describes, rather than by reading code.

**"this will only unwind as positions close"** was the most repeated line of
the night - 112 times - and it is false. The figure is risk / EQUITY, so it
moves whenever either does. Overnight on 10 August it changed ten times across
5.11-5.14% while all eleven positions stayed open and `closed_trades.csv` was
untouched. It moved the wrong way too: 5.12% to 5.14% as equity fell from
$102,161 to $101,798. The wording implied a figure that sits still until you
act, when it drifts against you as the book loses value.

**"11 carries a stop"** was ungrammatical, and worse, gave the operator the
protected count while the number that consumes the risk budget is the naked
one - left as an exercise in subtraction.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


class _Held(MockBroker):
    def __init__(self, protected: bool) -> None:
        super().__init__(seed=1)
        self._positions["AMD"] = Position(symbol="AMD", quantity=7.0, avg_price=510.0)
        self._positions["MNST"] = Position(symbol="MNST", quantity=8.0, avg_price=91.18)
        self._resting_stops["AMD"] = 405.55
        if protected:
            self._resting_stops["MNST"] = 72.68


def _oms(broker, tmp_path) -> OMS:
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    switch = KillSwitch()
    bus = EventBus()
    return OMS(
        broker, RiskEngine(bus, switch, settings=settings), switch, bus=bus, settings=settings
    )


@pytest.mark.asyncio
async def test_adoption_states_the_naked_count_not_just_the_protected_one(tmp_path, caplog):
    """The naked count is what consumes the cap at full value, and it was the
    one the operator had to work out."""
    with caplog.at_level("WARNING"):
        await _oms(_Held(protected=False), tmp_path).adopt_broker_positions()

    line = next(r.getMessage() for r in caplog.records if "Adopted" in r.getMessage())
    assert "1 of 2 carry a stop" in line
    assert "1 carry none" in line


@pytest.mark.asyncio
async def test_adoption_does_not_say_carries_of_a_plural(tmp_path, caplog):
    with caplog.at_level("WARNING"):
        await _oms(_Held(protected=True), tmp_path).adopt_broker_positions()

    line = next(r.getMessage() for r in caplog.records if "Adopted" in r.getMessage())
    assert "carries a stop" not in line
    assert "2 of 2 carry a stop" in line
    assert "0 carry none" in line


@pytest.mark.asyncio
async def test_the_over_cap_message_no_longer_claims_only_closing_unwinds_it(tmp_path, caplog):
    """It changed ten times overnight with every position still open.

    Asserted against the EMITTED line, not the source. A source scan failed
    the first time because the comment explaining the fix quotes the phrase it
    removed - the same false positive the colour guard had to learn about, and
    the reason that guard reads string tokens rather than text.
    """
    from qat.domain.risk_engine.delever import DeleverSweep
    from qat.domain.risk_engine.governor import PortfolioGovernor

    settings = Settings(
        _env_file=None,
        data_dir=str(tmp_path),
        delever_sweep_enabled=False,
        max_aggregate_risk_at_stop_pct=0.0001,  # anything held breaches it
    )
    oms = _oms(_Held(protected=True), tmp_path)
    await oms.adopt_broker_positions()
    sweep = DeleverSweep(oms, PortfolioGovernor(settings=settings), settings=settings)

    with caplog.at_level("WARNING"):
        await sweep.poll()

    line = next(
        r.getMessage() for r in caplog.records if "Aggregate risk-at-stop" in r.getMessage()
    )
    assert "only unwind as positions close" not in line
    assert "nothing will be sold" in line
    assert "as equity rises" in line
    assert "rises as equity falls" in line
