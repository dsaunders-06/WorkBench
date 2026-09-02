"""BookRiskMonitor: samples compute_book_risk on a timer, off the SHARED poller.

⚠️ IT MUST NOT POLL THE BROKER. Positions and equity come from the shared,
throttled `account_poller.snapshot()` - the same one the Dashboard already
reads - never from a broker adapter of its own. `EquityMonitor` states the
principle for its own sampler: "a separate poller would double the broker
traffic to record the same number."

⚠️ `fresh()` IS THE ONLY ACCESSOR A READER MAY CALL. A snapshot older than
`book_risk_max_age_seconds` must read as absent, identically to no snapshot
at all - there is no third state and no "probably still fine" path. A failed
poll leaves the previous value standing, which is safe only because every
value carries `computed_at` and readers go through `fresh()` rather than
`latest` directly.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from qat.config import Settings
from qat.domain.risk_engine.book_risk import BookRiskMonitor

NOW = datetime(2026, 9, 2, 17, 0, tzinfo=UTC)


def _bars(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    closes = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.01, n)))
    return pd.DataFrame({"ts": pd.date_range("2026-01-01", periods=n, freq="D"), "close": closes})


class _Aggregator:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    def frame_if_present(self, symbol: str, include_forming: bool = True):
        return self._frames.get(symbol)


class _Poller:
    def __init__(self, snapshot) -> None:
        self._snapshot = snapshot
        self.calls = 0

    async def snapshot(self, force: bool = False):
        self.calls += 1
        if isinstance(self._snapshot, Exception):
            raise self._snapshot
        return self._snapshot


def _snapshot(positions, equity):
    return SimpleNamespace(
        positions=tuple(positions),
        balances=SimpleNamespace(equity=equity),
    )


def _position(symbol: str, quantity: float, avg_price: float):
    return SimpleNamespace(symbol=symbol, quantity=quantity, avg_price=avg_price)


def _monitor(poller, aggregator, **kwargs) -> BookRiskMonitor:
    return BookRiskMonitor(
        account_poller=poller,
        bars=aggregator,
        settings=Settings(),
        sector_by_symbol={"A2M.AX": "Consumer Staples", "ANZ.AX": "Financials"},
        clock=lambda: NOW,
        **kwargs,
    )


def test_latest_is_none_before_the_first_poll():
    """The state at every startup, which is where the bug this replaces lives."""
    monitor = _monitor(_Poller(_snapshot([], 1.0)), _Aggregator({}))
    assert monitor.latest is None
    assert monitor.fresh() is None


@pytest.mark.asyncio
async def test_a_poll_measures_the_book():
    poller = _Poller(
        _snapshot(
            [_position("A2M.AX", 1000, 120.0), _position("ANZ.AX", 3000, 30.0)],
            1_000_000.0,
        )
    )
    aggregator = _Aggregator({"A2M.AX": _bars(), "ANZ.AX": _bars()})

    result = await _monitor(poller, aggregator).poll()

    assert result is not None
    assert result.symbols == 2
    assert result.var_95 is not None
    assert result.single_name_pct == 0.12


@pytest.mark.asyncio
async def test_a_snapshot_with_no_equity_leaves_latest_alone():
    """AccountSnapshot.balances.equity is None on a failed read. Real state."""
    good = _Poller(_snapshot([_position("A2M.AX", 1000, 120.0)], 1_000_000.0))
    aggregator = _Aggregator({"A2M.AX": _bars()})
    monitor = _monitor(good, aggregator)
    await monitor.poll()
    before = monitor.latest
    assert before is not None

    monitor.account_poller = _Poller(_snapshot([_position("A2M.AX", 1000, 120.0)], None))
    await monitor.poll()

    assert monitor.latest is before


@pytest.mark.asyncio
async def test_a_raising_poller_is_logged_and_the_previous_value_survives():
    good = _Poller(_snapshot([_position("A2M.AX", 1000, 120.0)], 1_000_000.0))
    monitor = _monitor(good, _Aggregator({"A2M.AX": _bars()}))
    await monitor.poll()
    before = monitor.latest

    monitor.account_poller = _Poller(RuntimeError("broker down"))
    await monitor.poll()

    assert monitor.latest is before


@pytest.mark.asyncio
async def test_a_held_symbol_with_no_frame_still_counts_for_concentration():
    poller = _Poller(
        _snapshot(
            [_position("A2M.AX", 1000, 120.0), _position("ANZ.AX", 10000, 30.0)],
            1_000_000.0,
        )
    )
    # ANZ has no frame - the state during a warm start.
    aggregator = _Aggregator({"A2M.AX": _bars()})

    result = await _monitor(poller, aggregator).poll()

    assert result is not None
    assert result.symbols == 2
    assert result.single_name_pct == 0.3


@pytest.mark.asyncio
async def test_it_never_touches_the_broker():
    """⚠️ EquityMonitor's own comment: a separate poller doubles broker traffic
    to record the same number. This engine reads the SHARED throttled poller."""

    class _ExplodingBroker:
        def __getattr__(self, name):
            raise AssertionError(f"BookRiskMonitor called broker.{name}")

    poller = _Poller(_snapshot([_position("A2M.AX", 1000, 120.0)], 1_000_000.0))
    monitor = _monitor(poller, _Aggregator({"A2M.AX": _bars()}))

    # The STRUCTURAL guarantee, which no future edit can leave passing by
    # accident: this engine was never given a broker to call.
    assert not hasattr(monitor, "broker"), (
        "BookRiskMonitor acquired a broker attribute - the whole point is that it "
        "reads the shared throttled poller instead"
    )

    # And the regression guard, for the day someone adds one anyway.
    monitor.broker = _ExplodingBroker()

    await monitor.poll()

    assert poller.calls == 1


@pytest.mark.asyncio
async def test_fresh_refuses_a_stale_snapshot():
    poller = _Poller(_snapshot([_position("A2M.AX", 1000, 120.0)], 1_000_000.0))
    monitor = _monitor(poller, _Aggregator({"A2M.AX": _bars()}))
    await monitor.poll()

    inside = NOW + timedelta(seconds=179)
    outside = NOW + timedelta(seconds=181)

    assert monitor.fresh(now=inside) is not None
    assert monitor.fresh(now=outside) is None
