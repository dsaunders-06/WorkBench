"""A public read of the entry record (positions panel brief, piece 3).

`entry_open_dates` and `opened_symbols()` already read `_entries` for other
callers; `position_entries()` follows the same shape for a caller - the
positions panel - that needs the whole record rather than one field of it.
`_Entry` itself stays private, so this returns a public, frozen copy per
symbol instead.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qat.config import Settings
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import PositionEntry, SignalToOrderBridge, _Entry
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


def _bridge(tmp_path) -> SignalToOrderBridge:
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    switch = KillSwitch()
    risk_engine = RiskEngine(bus, switch, settings=settings)
    oms = OMS(
        None,  # type: ignore[arg-type]  # not exercised: no test here awaits a broker call
        risk_engine,
        switch,
        bus=bus,
        settings=settings,
    )
    return SignalToOrderBridge(bus=bus, oms=oms, settings=settings)


def test_position_entries_is_empty_with_nothing_recorded(tmp_path):
    bridge = _bridge(tmp_path)
    assert bridge.position_entries() == {}


def test_position_entries_exposes_the_public_fields(tmp_path):
    bridge = _bridge(tmp_path)
    opened = datetime(2026, 8, 10, tzinfo=UTC)
    bridge._entries["AAA"] = _Entry(
        opened_at=opened,
        price=91.18,
        stop_price=72.68,
        target_price=110.0,
        strategy="swing",
    )

    entries = bridge.position_entries()

    assert entries == {
        "AAA": PositionEntry(
            opened_at=opened,
            price=91.18,
            stop_price=72.68,
            target_price=110.0,
            strategy="swing",
        )
    }


def test_position_entries_does_not_leak_the_private_entry_type(tmp_path):
    """`_Entry` stays private - the panel gets a public dataclass instead."""
    bridge = _bridge(tmp_path)
    bridge._entries["AAA"] = _Entry(opened_at=datetime.now(UTC), price=100.0, stop_price=95.0)

    entry = bridge.position_entries()["AAA"]

    assert isinstance(entry, PositionEntry)
    assert not isinstance(entry, _Entry)


def test_position_entries_returns_a_copy_not_the_live_dict(tmp_path):
    """A display must not be able to mutate the bridge's own state."""
    bridge = _bridge(tmp_path)
    bridge._entries["AAA"] = _Entry(opened_at=datetime.now(UTC), price=100.0, stop_price=95.0)

    entries = bridge.position_entries()
    entries["BBB"] = PositionEntry(
        opened_at=datetime.now(UTC), price=1.0, stop_price=None, target_price=None, strategy=None
    )

    assert "BBB" not in bridge.position_entries()
    assert "BBB" not in bridge._entries
