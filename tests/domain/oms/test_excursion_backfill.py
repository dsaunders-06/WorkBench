"""Excursion recovered from bars a restart cannot destroy (M44's other half).

`worst_price` and `best_price` EVOLVE over a trade's life, so persisting them at
open would restore a stale excursion - which is why M44's other half stayed open.
They are not persisted at all. They are recomputed at restore from the daily OHLC
bars warm start has already seeded into the bridge's own aggregator: the one whose
comment calls it "the most load-bearing of the three", because the ATR that sets
every stop distance comes from it.

⚠️ THE ENTRY DAY'S OWN BAR IS EXCLUDED, and that is the load-bearing rule. It
holds prices from before the position existed. Folding it in would attribute to
the trade a low it never experienced, which is the fabrication
`restore_open_lot`'s docstring already forbids. Understating a diagnostic is
acceptable; inventing one is not.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.bars import BAR_COLUMNS
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

# ⚠️ SYDNEY, NOT UTC, and this is not cosmetic. The real record reads
# "2026-08-24T15:19:36.392342+10:00". Written as UTC instead, the same clock
# time is already 25 August in Sydney, the entry day shifts by one, and the
# rule then excludes the WRONG bar - which is how this test data was wrong on
# first writing. The daily boundary is local midnight on the exchange (M111).
_OPENED = datetime(2026, 8, 24, 15, 19, 36, tzinfo=ZoneInfo("Australia/Sydney"))


def _bridge(tmp_path, ledger=None, broker=None) -> SignalToOrderBridge:
    """⚠️ `bar_interval_seconds` AND `bar_tz` MUST BE PASSED EXPLICITLY.

    `SignalToOrderBridge.__init__` defaults the interval to 60.0, while
    `Settings.bar_interval_seconds` defaults to 86,400 and `runtime.py` passes
    that plus the market's timezone. A fixture that omits them builds
    SIXTY-SECOND bars, and then "the entry day's boundary" is really the entry
    MINUTE's boundary.

    The entry-day test below would still pass under that mistake, because bars
    a day apart are also a minute apart - green for a reason that has nothing to
    do with the rule being tested. Mirror production or the test measures
    nothing.
    """
    settings = Settings(_env_file=None, data_dir=str(tmp_path), deployed_strategies="swing")
    bus = EventBus()
    switch = KillSwitch()
    oms = OMS(
        broker or MockBroker(seed=1),
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
    )
    return SignalToOrderBridge(
        bus,
        oms,
        settings=settings,
        trade_ledger=ledger,
        bar_interval_seconds=settings.bar_interval_seconds,
        bar_tz=ZoneInfo("Australia/Sydney"),
    )


def _seed_daily(
    bridge: SignalToOrderBridge, symbol: str, rows: list[tuple[str, float, float]]
) -> None:
    """rows are (iso date, low, high). Open and close sit between them."""
    frame = pd.DataFrame(
        [
            {
                "ts": pd.Timestamp(day, tz="UTC"),
                "open": (low + high) / 2,
                "high": high,
                "low": low,
                "close": (low + high) / 2,
                "volume": 1000.0,
            }
            for day, low, high in rows
        ],
        columns=list(BAR_COLUMNS),
    )
    bridge.bars.seed(symbol, frame)


def test_the_bridge_in_production_keeps_daily_bars() -> None:
    """The rule below says "the entry DAY's bar". That is only true while the
    shipped interval is a day, and nothing else in the suite pins it."""
    assert Settings(_env_file=None).bar_interval_seconds == 86_400.0


def test_the_excursion_comes_from_the_bars_after_the_entry_day(tmp_path) -> None:
    bridge = _bridge(tmp_path)
    _seed_daily(
        bridge,
        "AAA",
        [("2026-08-24", 49.0, 51.0), ("2026-08-25", 46.0, 52.0), ("2026-08-26", 47.0, 58.0)],
    )

    worst, best, bars = bridge._excursion_since("AAA", _OPENED)

    assert worst == pytest.approx(46.0)
    assert best == pytest.approx(58.0)
    assert bars == 2


def test_the_entry_days_own_bar_is_excluded(tmp_path) -> None:
    """⚠️ THE PLANTED VIOLATION. The entry day carries a low of 20.0 and a high
    of 99.0 - neither of which the position was open for, because it opened at
    15:19:36 that afternoon. Asserting the absence of a bad value alone would
    report the same clean result whether the rule works or the scan has gone
    blind, so the value that must not appear is planted where it would show."""
    bridge = _bridge(tmp_path)
    _seed_daily(
        bridge,
        "AAA",
        [("2026-08-24", 20.0, 99.0), ("2026-08-25", 46.0, 52.0), ("2026-08-26", 47.0, 58.0)],
    )

    worst, best, bars = bridge._excursion_since("AAA", _OPENED)

    assert worst == pytest.approx(46.0), "the entry day's low reached the excursion"
    assert best == pytest.approx(58.0), "the entry day's high reached the excursion"
    assert bars == 2


def test_a_symbol_with_no_bars_after_its_entry_day_reports_nothing(tmp_path) -> None:
    """Opened today, restarted today. Honest: there is nothing to measure yet."""
    bridge = _bridge(tmp_path)
    _seed_daily(bridge, "AAA", [("2026-08-24", 49.0, 51.0)])

    assert bridge._excursion_since("AAA", _OPENED) == (None, None, 0)


def test_a_symbol_the_aggregator_has_never_seen_reports_nothing(tmp_path) -> None:
    """⚠️ Warm start catches its own exceptions and continues - "a cold start
    beats no application" - so empty buffers are a live possibility, not a
    theoretical one. And this must not CREATE an aggregator by asking."""
    bridge = _bridge(tmp_path)

    assert bridge._excursion_since("NEVERSEEN", _OPENED) == (None, None, 0)
    assert (
        bridge.bars.frame_if_present("NEVERSEEN") is None
    ), "asking about a symbol must not start tracking it"
