"""The OMS's fill watermark reads a clock, and in a replay that clock is not now.

`_load_fill_state` falls back to `datetime.now(UTC)` when there is no state
file, which is every replay given its own scratch `data_dir`. A replay of a
2026 window then asks the broker for fills "since now", every simulated fill is
older than that, and the absorb sweep records NOTHING while reporting success -
an honest-looking zero closed trades.

The fourth injectable clock in the trading path, and the fourth for the same
reason: `SignalToOrderBridge(clock=)`, `AutonomyGate(clock=)` and
`RiskEngine(clock=)` came first. Every wall-clock read in the trading path is a
place a replay silently produces nothing.

Defaults to the wall clock, so live behaviour is unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qat.config import Settings
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

_SIMULATED = datetime(2026, 7, 31, 15, 0, tzinfo=UTC)


def _oms(tmp_path, clock=None) -> OMS:
    # Its own data_dir, per the standing constraint: conftest sets QAT_DATA_DIR
    # session-wide and the anomaly store persists there, so one declared anomaly
    # would leak a quarantine into every later test.
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    return OMS(
        MockBroker(seed=1),
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
        clock=clock,
    )


def test_without_a_clock_the_watermark_is_now(tmp_path):
    """Live behaviour, unchanged. The default must stay the wall clock."""
    before = datetime.now(UTC)

    oms = _oms(tmp_path)

    assert before <= oms._last_fill_scan <= datetime.now(UTC)


def test_an_injected_clock_sets_the_watermark(tmp_path):
    """Without this a replay asks for fills since NOW, gets none, and records no
    closed trades while looking like it worked."""
    oms = _oms(tmp_path, clock=lambda: _SIMULATED)

    assert oms._last_fill_scan == _SIMULATED


def test_an_unreadable_state_file_falls_back_to_the_clock(tmp_path):
    """The other `return datetime.now(UTC)` in `_load_fill_state`. A corrupt
    file degrades to "start from the clock" - pre-M50 behaviour, which was
    incomplete rather than wrong - and in a replay that must still be the
    SIMULATED clock, or the same silent zero returns by a slower route."""
    (tmp_path / "absorbed_fills.json").write_text("{ not json", encoding="utf-8")

    oms = _oms(tmp_path, clock=lambda: _SIMULATED)

    assert oms._last_fill_scan == _SIMULATED
