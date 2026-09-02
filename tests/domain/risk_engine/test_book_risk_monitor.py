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

⚠️ A DEGRADED SNAPSHOT (`error` set) IS REFUSED THE SAME WAY A RAISED
EXCEPTION IS. `AccountPoller._fetch` swallows the broker's own exceptions
and returns `_degrade(...)`, which keeps serving the LAST GOOD reading with
`taken_at` carried forward unchanged - `snapshot()` itself never raises on a
broker outage, so a poller that only reacts to a raised exception never
notices one. `poll()` also stamps `computed_at` from the snapshot's own
`taken_at`, not the clock, so `age_seconds` measures how old the READING is,
not how long ago `poll()` happened to run.
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


def _snapshot(positions, equity, *, taken_at=NOW, error=None):
    return SimpleNamespace(
        positions=tuple(positions),
        balances=SimpleNamespace(equity=equity),
        taken_at=taken_at,
        error=error,
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
async def test_a_degraded_snapshot_is_refused_not_read_as_fresh():
    """The shape the REAL AccountPoller actually produces on a broker outage
    (account_poller.py `_fetch` -> `_degrade`), which does NOT raise: it
    keeps serving the last good reading with `error` set and `taken_at`
    carried FORWARD UNCHANGED. The test above proves the survival path with a
    stub that raises - a shape `_fetch` itself already catches and never lets
    reach here - so it is near-dead in production while this one, the
    untested one, is what actually runs on a real outage.

    Uses a MUTABLE clock, not the fixed one `_monitor()` injects, because the
    bug this pins is about the CLOCK advancing while the DATA does not: a
    fixed clock would stamp the same `computed_at` either way and the
    pre-fix/post-fix difference would only show up as object identity, not as
    a reader being told stale data is current - the failure mode this task
    exists to close.
    """
    clock_box = {"t": NOW}
    good = _Poller(_snapshot([_position("A2M.AX", 1000, 120.0)], 1_000_000.0, taken_at=NOW))
    monitor = BookRiskMonitor(
        account_poller=good,
        bars=_Aggregator({"A2M.AX": _bars()}),
        settings=Settings(),
        sector_by_symbol={"A2M.AX": "Consumer Staples"},
        clock=lambda: clock_box["t"],
    )
    await monitor.poll()
    before = monitor.latest
    assert before is not None
    assert before.computed_at == NOW

    # Four hours pass with the broker down the whole time. _degrade() carries
    # taken_at forward UNCHANGED - the data is still dated NOW, not re-dated -
    # while the wall clock a reader would use has moved on.
    clock_box["t"] = NOW + timedelta(hours=4)
    degraded = _snapshot(
        [_position("A2M.AX", 1000, 120.0)],
        1_000_000.0,
        taken_at=NOW,
        error="broker down",
    )
    monitor.account_poller = _Poller(degraded)
    await monitor.poll()

    # Refused exactly like the raising case: the previous measurement
    # survives untouched, not recomputed from degraded data with a re-dated
    # computed_at.
    assert monitor.latest is before

    # The decisive check: a reader asking right now must be told this
    # four-hour-old book is ABSENT, not handed it as current.
    assert monitor.fresh(now=clock_box["t"]) is None


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


@pytest.mark.asyncio
async def test_fresh_boundary_is_inclusive_at_exactly_the_max_age():
    """Pins the `>` in fresh() against a mutation to `>=`. 179/181 above land
    well inside/outside on EITHER operator - this is the one point, exactly
    at book_risk_max_age_seconds, where the two disagree."""
    poller = _Poller(_snapshot([_position("A2M.AX", 1000, 120.0)], 1_000_000.0))
    monitor = _monitor(poller, _Aggregator({"A2M.AX": _bars()}))
    await monitor.poll()

    at_bound = NOW + timedelta(seconds=180)
    just_past = NOW + timedelta(seconds=180, microseconds=1)

    assert monitor.fresh(now=at_bound) is not None
    assert monitor.fresh(now=just_past) is None


@pytest.mark.asyncio
async def test_fresh_refuses_a_measurement_dated_in_the_future():
    """Clock skew, or any other way computed_at ends up ahead of `now`: a
    NEGATIVE age must not read as fresher than fresh. Absent, not eager."""
    poller = _Poller(_snapshot([_position("A2M.AX", 1000, 120.0)], 1_000_000.0))
    monitor = _monitor(poller, _Aggregator({"A2M.AX": _bars()}))
    await monitor.poll()

    before_the_measurement_was_computed = NOW - timedelta(seconds=1)

    assert monitor.fresh(now=before_the_measurement_was_computed) is None


@pytest.mark.asyncio
async def test_a_healthy_but_old_snapshot_is_dated_from_the_data_not_the_clock():
    """Account snapshots are cached by AccountPoller for up to
    `account_poll_seconds` (Settings.account_poll_seconds), which has no upper
    bound. Even a healthy snapshot (error=None) can legitimately be older than
    the staleness bound. The age_seconds bound in fresh() must measure the
    reading's actual age, not how long ago poll() happened to run, so
    computed_at MUST be stamped from snapshot.taken_at, not from the clock."""
    stale_reading = _snapshot(
        [_position("A2M.AX", 1000, 120.0)],
        1_000_000.0,
        taken_at=NOW - timedelta(seconds=200),  # error stays None
    )
    monitor = _monitor(_Poller(stale_reading), _Aggregator({"A2M.AX": _bars()}))
    result = await monitor.poll()
    assert result is not None
    assert result.computed_at == NOW - timedelta(seconds=200)
    assert monitor.fresh(now=NOW) is None
