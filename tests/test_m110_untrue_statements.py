"""M110: three things the app or its universe stated that were not true.

Found on 20 August, the day after the first ASX session, while checking the
handoff document's claims against the code. Two of the document's claims did
not survive that check either, which is the reason this file exists as a set of
assertions rather than as a paragraph.

None of these changes what trades happen. All three change what a reader is
told, and each one had already misled somebody.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from qat.config import Settings
from qat.data import universe
from qat.domain.bus import EventBus
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge
from qat.domain.performance.trades import TradeLedger
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch
from qat.preflight import PROBE_CAP, Status, probe_plan

# Verified dead on 20 August: yfinance returned no real daily bars for any of
# these six, and `fetch_daily_panel` correctly left them unseeded and named
# them. They cost a fetch each on every warm start and produce a warning that
# is true and permanent, which is the kind of alarm a reader learns to skip.
DEAD_ON_20_AUGUST = {"AWC.AX", "BKW.AX", "DHG.AX", "IPL.AX", "NSR.AX", "SVW.AX"}


def test_the_six_tickers_verified_dead_are_gone_from_the_asx_pool() -> None:
    pool = set(universe.MARKET_WATCHLISTS["ASX"]["megacap"])

    assert not (pool & DEAD_ON_20_AUGUST)


def test_the_asx_pool_is_still_a_useful_size_after_the_prune() -> None:
    """Guards the prune itself: removing six should not have removed six
    hundred, and an empty pool would make `megacap` silently untradeable."""
    assert len(universe.MARKET_WATCHLISTS["ASX"]["megacap"]) >= 90


def test_a_small_watchlist_is_covered_completely() -> None:
    """The 20 August bug. `--sample` defaulted to 5, chosen when the watchlist
    was 100. On the six-symbol ASX watchlist the pre-flight priced five of six
    and reported "all 5 priced", which reads as a clean feed check of the
    watchlist. The sixth was never contacted."""
    watchlist = ["RIO.AX", "APA.AX", "AMC.AX", "MGR.AX", "SGP.AX", "NHF.AX"]

    probe, check = probe_plan(watchlist, None)

    assert list(probe) == watchlist
    assert check.status is Status.OK
    assert "6 of 6" in check.detail


def test_a_large_watchlist_is_capped_and_SAYS_it_was_capped() -> None:
    """The cap is real - IBKR paces contract resolution, so pricing a hundred
    symbols is slow. Capping is fine. Capping silently is not."""
    watchlist = [f"SYM{i}.AX" for i in range(100)]

    probe, check = probe_plan(watchlist, None)

    assert len(probe) == PROBE_CAP
    assert check.status is Status.WARN
    assert f"{PROBE_CAP} of 100" in check.detail
    assert "unverified" in check.detail.lower()


def test_an_explicit_sample_is_still_honoured_and_still_reports_coverage() -> None:
    """An operator asking for two symbols gets two, and is still told that is
    two of six rather than a clean bill of health."""
    watchlist = ["RIO.AX", "APA.AX", "AMC.AX", "MGR.AX", "SGP.AX", "NHF.AX"]

    probe, check = probe_plan(watchlist, 2)

    assert list(probe) == ["RIO.AX", "APA.AX"]
    assert check.status is Status.WARN
    assert "2 of 6" in check.detail


def test_an_empty_watchlist_does_not_claim_full_coverage() -> None:
    """Zero of zero is not a pass. An empty watchlist is already FAILed by its
    own check, and this must not quietly agree that everything was verified."""
    probe, check = probe_plan([], None)

    assert list(probe) == []
    assert check.status is not Status.OK


# --- the startup line that asserted what it had not established --------------


def _bridge_with_entry_file(data_dir: Path, record: dict[str, dict]) -> object:
    """Its OWN data_dir, per the standing rule - the anomaly store persists
    there and one declared anomaly would leak a quarantine into later tests."""
    (data_dir / "open_position_entries.json").write_text(json.dumps(record), encoding="utf-8")

    class _Broker:
        async def positions(self) -> list[object]:
            return []

        async def resting_stops(self) -> dict[str, float]:
            return {}

        async def recent_fills(self, since: object) -> list[object]:
            return []

    settings = Settings(_env_file=None, data_dir=str(data_dir), deployed_strategies="swing")
    bus = EventBus()
    switch = KillSwitch()
    oms = OMS(
        _Broker(),
        RiskEngine(bus, switch, settings=settings),
        switch,
        bus=bus,
        settings=settings,
    )
    ledger = TradeLedger(bus, data_dir, settings=settings)
    return SignalToOrderBridge(bus=bus, oms=oms, settings=settings, trade_ledger=ledger)


def test_restoring_entry_records_does_not_claim_the_positions_are_held(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """20 August, tonight's launch on M109:

        16:41:12  Restored entry dates for 10 held position(s): AMAT, AMD, ...
        16:41:26  No pre-existing broker positions to adopt

    The same startup produced both, fourteen seconds apart, and they contradict
    each other. The first is the wrong one: it reads a JSON file and cannot
    know what is held - the broker settles that, later. Those ten named an
    Alpaca account this build no longer trades.
    """
    record = {
        "AMAT": {
            "opened_at": "2026-08-01T01:08:21+10:00",
            "price": 256.43,
            "stop_price": 240.58,
            "target_price": 288.11,
            "strategy": "swing",
        },
        "AMD": {
            "opened_at": "2026-08-04T14:01:25.595076+00:00",
            "price": 503.16,
            "stop_price": 405.54,
            "target_price": 698.38,
            "strategy": "swing",
        },
    }

    with caplog.at_level(logging.INFO):
        bridge = _bridge_with_entry_file(tmp_path, record)

    # The first draft of this test PASSED before the fix existed. The record
    # shape was wrong, both entries were rejected as unreadable, the restore
    # line never fired, and `next(...)` matched "Ignoring an unreadable entry
    # record for AMAT" - which happens to contain AMAT, omit "held position"
    # and contain "record". Assert the records actually loaded, so the line
    # under test is the line being read.
    assert set(bridge._entries) == {"AMAT", "AMD"}

    line = next(m for m in caplog.messages if m.startswith("Restored"))
    assert "held position" not in line
    assert "record" in line
    assert "AMAT" in line
