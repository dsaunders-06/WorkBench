"""Churn control: minimum hold, loss escape, time stop, turnover (M31).

Ten concurrent positions turned over weekly costs $6,240 a year at $12 a round
trip - 6.2% of a $100k account before a single losing trade. At ten trading
days it is 3.1%.

`enforce_min_holding_period` and `min_holding_trading_days` had existed as
settings since M27 and were read by nothing at all.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.adapter import Position
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.events import MarketDataEvent, OrderFilledEvent, SignalEvent
from qat.domain.oms.oms import OMS
from qat.domain.oms.signal_bridge import SignalToOrderBridge, _Entry, minimum_hold_status
from qat.domain.risk_engine.engine import RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch

_NOW = datetime.now(UTC)


class _Broker(MockBroker):
    def __init__(self, held: float = 100.0) -> None:
        super().__init__(seed=1)
        self.held = held
        self.exits: list[tuple[str, float]] = []

    async def positions(self) -> list[Position]:
        if self.held <= 0:
            return []
        return [Position(symbol="AAA", quantity=self.held, avg_price=100.0)]


def _bridge(broker: _Broker, **overrides) -> SignalToOrderBridge:
    # Its own data dir: the bridge persists entry dates (M31b), and the
    # session-scoped isolate_data_dir fixture is shared by every test, so
    # without this one test's open positions would be another's.
    base = {"_env_file": None, "data_dir": tempfile.mkdtemp()}
    base.update(overrides)
    settings = Settings(**base)  # type: ignore[arg-type]
    bus = EventBus()
    switch = KillSwitch()
    engine = RiskEngine(bus, switch, settings=settings)
    oms = OMS(broker, engine, switch, bus=bus)
    bridge = SignalToOrderBridge(bus, oms, settings=settings)
    bridge.bars.add_tick("AAA", _NOW - timedelta(days=1), 100.0, 1.0)
    bridge.bars.add_tick("AAA", _NOW, 100.0, 1.0)
    return bridge


async def _opened(bridge: SignalToOrderBridge, days_ago: int, stop: float | None = 95.0) -> None:
    await bridge._on_fill(
        OrderFilledEvent(
            order_id="o1",
            symbol="AAA",
            side="buy",
            quantity=100.0,
            price=100.0,
            strategy="swing",
            stop_price=stop,
            ts=_NOW - timedelta(days=days_ago),
        )
    )


def _exit_signal() -> SignalEvent:
    return SignalEvent(
        symbol="AAA",
        side="sell",
        conviction=1.0,
        strategy="swing",
        meta={"exit_reason": "trend_broken"},
        ts=_NOW,
    )


@pytest.mark.asyncio
async def test_a_signal_exit_inside_the_minimum_hold_is_held_back():
    broker = _Broker()
    bridge = _bridge(broker, min_holding_trading_days=10)
    await _opened(bridge, days_ago=2)

    await bridge._on_signal(_exit_signal())

    assert not broker.exits and bridge._entries["AAA"] is not None
    assert "AAA" in bridge._hold_blocked


@pytest.mark.asyncio
async def test_the_hold_stops_applying_once_the_thesis_is_far_enough_wrong():
    """The escape that makes a minimum hold defensible. Sitting through a
    broken thesis to save $12 of commission is the wrong trade."""
    broker = _Broker()
    bridge = _bridge(broker, min_holding_trading_days=10, min_holding_loss_escape_r=0.5)
    await _opened(bridge, days_ago=2, stop=95.0)  # 1R = $5

    # Down $3 = 0.6R, past the 0.5R escape.
    assert bridge._blocked_by_minimum_hold("AAA", price=97.0) is False
    # Down $1 = 0.2R, not far enough.
    assert bridge._blocked_by_minimum_hold("AAA", price=99.0) is True


@pytest.mark.asyncio
async def test_the_escape_says_in_the_log_why_it_let_the_exit_through(caplog):
    """An exit INSIDE the minimum hold is the surprising thing to find in the
    record, and this line is the only place that explains it.

    It existed, and the I3 extraction of `minimum_hold_status` dropped it: the
    blocked path kept its message and the escape path lost one, silently. The
    rule moved and its explanation did not move with it. Nothing failed,
    because nothing asserted on it - which is why this test exists rather than
    just the restored line.
    """
    broker = _Broker()
    bridge = _bridge(broker, min_holding_trading_days=10, min_holding_loss_escape_r=0.5)
    await _opened(bridge, days_ago=2, stop=95.0)  # 1R = $5

    with caplog.at_level("INFO", logger="qat.domain.oms.signal_bridge"):
        assert bridge._blocked_by_minimum_hold("AAA", price=97.0) is False  # 0.6R down

    escape_lines = [r for r in caplog.records if "does not" in r.getMessage()]
    assert len(escape_lines) == 1
    # The R figure itself, not just that something was logged - the number is
    # the whole reason an operator reads the line.
    assert "0.60R" in escape_lines[0].getMessage()
    assert "AAA" in escape_lines[0].getMessage()


@pytest.mark.asyncio
async def test_clearing_the_hold_normally_does_not_claim_an_escape(caplog):
    """A lot past its minimum hold is not "escaping" anything. `loss_r` is set
    on no path but the escape, which is what keeps the two apart."""
    broker = _Broker()
    bridge = _bridge(broker, min_holding_trading_days=10, min_holding_loss_escape_r=0.5)
    await _opened(bridge, days_ago=30, stop=95.0)

    with caplog.at_level("INFO", logger="qat.domain.oms.signal_bridge"):
        assert bridge._blocked_by_minimum_hold("AAA", price=97.0) is False

    assert [r for r in caplog.records if "does not" in r.getMessage()] == []


@pytest.mark.asyncio
async def test_a_signal_exit_after_the_minimum_hold_goes_through():
    broker = _Broker()
    bridge = _bridge(broker, min_holding_trading_days=10)
    await _opened(bridge, days_ago=30)

    assert bridge._blocked_by_minimum_hold("AAA", price=100.0) is False


@pytest.mark.asyncio
async def test_a_position_with_no_known_entry_is_never_trapped():
    """An adopted position has no entry this app recorded, and refusing to let
    a strategy exit it would be worse than churning."""
    broker = _Broker()
    bridge = _bridge(broker, min_holding_trading_days=10)

    assert bridge._blocked_by_minimum_hold("AAA", price=100.0) is False


# --- minimum_hold_status: the pure rule extracted for position_view.py to ---
# --- share rather than re-derive (I3, positions panel brief review) --------


def test_minimum_hold_status_blocks_inside_the_window():
    settings = Settings(_env_file=None, min_holding_trading_days=10)
    entry = _Entry(opened_at=_NOW - timedelta(days=2), price=100.0, stop_price=95.0)

    status = minimum_hold_status(entry, 100.0, _NOW, settings)

    assert status.blocked is True
    assert status.escape_evaluated is True


def test_minimum_hold_status_matches_the_bridges_own_escape_arithmetic():
    settings = Settings(_env_file=None, min_holding_trading_days=10, min_holding_loss_escape_r=0.5)
    entry = _Entry(opened_at=_NOW - timedelta(days=2), price=100.0, stop_price=95.0)  # 1R = $5

    # Down $3 = 0.6R, past the 0.5R escape.
    assert minimum_hold_status(entry, 97.0, _NOW, settings).blocked is False
    # Down $1 = 0.2R, not far enough.
    assert minimum_hold_status(entry, 99.0, _NOW, settings).blocked is True


def test_minimum_hold_status_escape_evaluated_is_false_with_no_price():
    """The C1 case: no broker mark to measure the loss escape against - the
    gate's state cannot be checked, which is a different fact from it being
    definitely on. The bridge itself never hits this branch (it always has
    a live tick price); only a display reading a possibly-absent mark can."""
    settings = Settings(_env_file=None, min_holding_trading_days=10, min_holding_loss_escape_r=0.5)
    entry = _Entry(opened_at=_NOW - timedelta(days=2), price=100.0, stop_price=95.0)

    status = minimum_hold_status(entry, None, _NOW, settings)

    assert status.blocked is True
    assert status.escape_evaluated is False


def test_minimum_hold_status_with_no_stop_is_definite_not_unknown():
    """No stop means no possible escape route regardless of price - a known
    fact, not an unknown one, even with no price supplied."""
    settings = Settings(_env_file=None, min_holding_trading_days=10)
    entry = _Entry(opened_at=_NOW - timedelta(days=2), price=100.0, stop_price=None)

    status = minimum_hold_status(entry, None, _NOW, settings)

    assert status.blocked is True
    assert status.escape_evaluated is True


def test_minimum_hold_status_off_when_the_rule_is_disabled():
    settings = Settings(_env_file=None, enforce_min_holding_period=False)
    entry = _Entry(opened_at=_NOW - timedelta(days=2), price=100.0, stop_price=95.0)

    assert minimum_hold_status(entry, 100.0, _NOW, settings).blocked is False


@pytest.mark.asyncio
async def test_the_time_stop_forces_an_exit_on_an_unresolved_thesis():
    broker = _Broker()
    bridge = _bridge(broker, time_stop_trading_days=30, enforce_min_holding_period=False)
    await _opened(bridge, days_ago=60)

    await bridge._on_market_data(MarketDataEvent(symbol="AAA", price=100.0, volume=1.0, ts=_NOW))

    assert "AAA" in bridge._time_stopped


@pytest.mark.asyncio
async def test_the_time_stop_does_not_fire_early():
    broker = _Broker()
    bridge = _bridge(broker, time_stop_trading_days=30)
    await _opened(bridge, days_ago=5)

    await bridge._on_market_data(MarketDataEvent(symbol="AAA", price=100.0, volume=1.0, ts=_NOW))

    assert "AAA" not in bridge._time_stopped


@pytest.mark.asyncio
async def test_the_turnover_budget_counts_a_rolling_seven_days():
    broker = _Broker(held=0.0)
    bridge = _bridge(broker, max_entries_per_week=3)

    for day in (1, 2, 3):
        bridge._entry_times.append(_NOW - timedelta(days=day))
    assert bridge._entries_this_week(_NOW) == 3

    # An entry from a fortnight ago has aged out of the window.
    bridge._entry_times.append(_NOW - timedelta(days=14))
    assert bridge._entries_this_week(_NOW) == 3


@pytest.mark.asyncio
async def test_the_turnover_budget_blocks_a_further_entry():
    broker = _Broker(held=0.0)
    bridge = _bridge(broker, max_entries_per_week=2)
    bridge._entry_times = [_NOW - timedelta(days=1), _NOW - timedelta(days=2)]

    await bridge._submit_entry(
        SignalEvent(symbol="AAA", side="buy", conviction=1.0, strategy="swing", meta={}, ts=_NOW),
        bars=pd.DataFrame(),
        price=100.0,
        positions=[],
    )

    assert not broker._orders, "the budget must stop the order before it is built"


# --- Entry dates survive a restart (M31b/4) --------------------------------


@pytest.mark.asyncio
async def test_entry_dates_survive_a_restart():
    """Rebuilt only from live fills, the record was empty after every restart -
    and both churn rails treat an unknown entry as "never applies", so a
    restart silently disarmed them on everything already held."""
    data_dir = tempfile.mkdtemp()
    broker = _Broker()
    first = _bridge(broker, data_dir=data_dir, min_holding_trading_days=10)
    await _opened(first, days_ago=2)

    # A new process, same data directory.
    second = _bridge(_Broker(), data_dir=data_dir, min_holding_trading_days=10)

    assert "AAA" in second._entries
    assert second._blocked_by_minimum_hold("AAA", price=100.0) is True


@pytest.mark.asyncio
async def test_a_closed_position_is_forgotten_across_a_restart():
    data_dir = tempfile.mkdtemp()
    broker = _Broker()
    first = _bridge(broker, data_dir=data_dir)
    await _opened(first, days_ago=2)
    # The sell happened AT THE BROKER, so the account is flat by the time the
    # event is handled. Whether the record may be dropped is now asked of the
    # account rather than assumed from the event (M53).
    broker.held = 0.0
    await first._on_fill(
        OrderFilledEvent(
            order_id="o2",
            symbol="AAA",
            side="sell",
            quantity=100.0,
            price=101.0,
            strategy="swing",
            stop_price=None,
            ts=_NOW,
        )
    )

    second = _bridge(_Broker(), data_dir=data_dir)

    assert "AAA" not in second._entries


@pytest.mark.asyncio
async def test_a_partial_exit_keeps_the_entry_record_for_what_remains():
    """M53. A partial sell used to drop the whole record, leaving the remaining
    shares with no stop to re-arm to, no minimum hold, no time stop, and no way
    for a later exit to become a closed trade - the entry it would have been
    measured from was gone.

    On 5 August a CVS stop filled 30 of 47. It was harmless only because the
    rest filled seconds later and the position went flat anyway."""
    data_dir = tempfile.mkdtemp()
    broker = _Broker()
    bridge = _bridge(broker, data_dir=data_dir)
    await _opened(bridge, days_ago=2)

    broker.held = 30.0  # 70 of 100 sold, 30 still held
    await bridge._on_fill(
        OrderFilledEvent(
            order_id="o2",
            symbol="AAA",
            side="sell",
            quantity=70.0,
            price=101.0,
            strategy="swing",
            stop_price=None,
            ts=_NOW,
        )
    )

    assert "AAA" in bridge._entries
    assert bridge._entries["AAA"].stop_price == 95.0
    # And it survives the restart, so the remainder can still be re-armed.
    assert "AAA" in _bridge(_Broker(held=30.0), data_dir=data_dir)._entries


def test_an_unreadable_entries_file_is_not_fatal():
    """A first run, or a corrupted file, must read as "no known entries" - the
    pre-M31b behaviour - not as a startup failure."""
    data_dir = tempfile.mkdtemp()
    (Path(data_dir) / "open_position_entries.json").write_text("{not json", encoding="utf-8")

    bridge = _bridge(_Broker(), data_dir=data_dir)

    assert bridge._entries == {}


# --- The rails are actually fed (M33) ----------------------------------------


def _seed_daily(bridge, symbol: str, start_price: float, step: float, n: int = 40) -> None:
    """Bars in strictly increasing time order. The aggregator folds an
    out-of-order tick into the forming bar, so seeding backwards silently
    produces a one-bar frame."""
    base = _NOW + timedelta(days=1)
    for i in range(n):
        bridge.bars.add_tick(symbol, base + timedelta(days=i), start_price + i * step, 1.0)


@pytest.mark.asyncio
async def test_held_positions_arrive_as_real_return_series():
    """existing_returns was an empty dict with a comment calling it a
    documented simplification. It made two rails inert rather than lenient:
    the correlated-cluster cap had nothing to correlate against, and
    PortfolioRiskChecker computed VaR and ES for a book it believed empty."""
    bridge = _bridge(_Broker(held=100.0))
    captured: dict[str, object] = {}

    async def _capture(candidate, equity, weights, returns, *args, **kwargs):
        captured["returns"] = returns
        captured["candidate"] = candidate
        return None

    bridge.oms.submit_order = _capture  # type: ignore[method-assign]

    _seed_daily(bridge, "HELD", 100.0, 1.0)
    _seed_daily(bridge, "CAND", 50.0, 0.5)

    await bridge._submit_sized(
        "CAND",
        "buy",
        bridge.bars.frame("CAND"),
        60.0,
        [Position(symbol="HELD", quantity=100.0, avg_price=100.0)],
    )

    returns = captured["returns"]
    assert "HELD" in returns, "the held position must arrive with a return series"
    assert len(returns["HELD"]) > 20
    # Indexed by timestamp, so correlating two symbols compares the same DAY
    # rather than the same bar number.
    assert isinstance(returns["HELD"].index, pd.DatetimeIndex)
    assert isinstance(captured["candidate"].candidate_returns.index, pd.DatetimeIndex)


@pytest.mark.asyncio
async def test_the_candidates_own_symbol_is_not_in_existing_returns():
    bridge = _bridge(_Broker(held=100.0))
    captured: dict[str, object] = {}

    async def _capture(candidate, equity, weights, returns, *args, **kwargs):
        captured["returns"] = returns
        return None

    bridge.oms.submit_order = _capture  # type: ignore[method-assign]
    _seed_daily(bridge, "CAND", 50.0, 0.5)

    await bridge._submit_sized(
        "CAND",
        "buy",
        bridge.bars.frame("CAND"),
        70.0,
        [Position(symbol="CAND", quantity=100.0, avg_price=60.0)],
    )

    assert captured["returns"] == {}
