"""M130: the feed's delay is a claim, so it gets checked against the vendor.

`source_delay_seconds` is 1,200 because the ASX opened at 10:00 on 21 August
2026 and the first intraday bars appeared at 10:22. One observation, one
morning, one vendor - and nothing else in the system checks it. The replay
harness bypasses `MarketDataFeed` entirely (no `RawTick`, no staleness rail),
and the unit tests supply their own timestamps. A number supported by a single
observation should be re-observed continuously.

**It never adjusts the threshold.** A safety rail that widens its own tolerance
when the feed degrades is blind exactly when it matters most: a stalling feed
would grow the observed lag, the rail would accommodate it, and the accommodation
would hide the stall. So this only ever reports, and the operator changes the
setting.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest

from qat.data.market_data import MarketDataFeed
from qat.domain.bus import EventBus


def _feed(configured_delay: float) -> MarketDataFeed:
    return MarketDataFeed(
        EventBus(),
        source=None,  # type: ignore[arg-type]
        symbols=["MGR.AX"],
        staleness_seconds=900.0,
        source_delay_seconds=configured_delay,
    )


def _observe(feed: MarketDataFeed, lag_seconds: float, count: int = 30) -> None:
    arrived = datetime.now(UTC)
    for _ in range(count):
        feed._observe_lag(arrived - timedelta(seconds=lag_seconds), arrived)


def test_it_says_nothing_until_it_has_seen_enough() -> None:
    """One tick is not a measurement of a vendor's publication delay."""
    feed = _feed(1200.0)
    _observe(feed, lag_seconds=1200.0, count=5)

    assert feed.observed_delay_seconds() is None


def test_a_feed_behaving_as_configured_is_quiet(caplog) -> None:
    feed = _feed(1200.0)
    _observe(feed, lag_seconds=1215.0)

    with caplog.at_level(logging.WARNING, logger="qat.data.market_data"):
        feed._check_delay_claim()

    assert feed.observed_delay_seconds() == pytest.approx(1215.0)
    assert not caplog.records, "jitter inside the tolerance is not news"


def test_a_vendor_that_got_slower_is_reported_as_blindness(caplog) -> None:
    """The dangerous direction. Staleness is measured BEYOND the configured
    figure, so if the real delay grows the rail loses exactly that much sight
    without anything failing."""
    feed = _feed(1200.0)
    _observe(feed, lag_seconds=2100.0)

    with caplog.at_level(logging.WARNING, logger="qat.data.market_data"):
        feed._check_delay_claim()

    said = " ".join(record.getMessage() for record in caplog.records)
    assert "OUT OF DATE" in said
    assert "blind" in said
    assert "QAT_MARKET_DATA_DELAY_SECONDS" in said


def test_a_vendor_that_got_faster_is_reported_as_tighter(caplog) -> None:
    """The other direction is not dangerous, but it is still wrong - the rail
    is stricter than intended and will exclude symbols that are fine."""
    feed = _feed(1200.0)
    _observe(feed, lag_seconds=60.0)

    with caplog.at_level(logging.WARNING, logger="qat.data.market_data"):
        feed._check_delay_claim()

    said = " ".join(record.getMessage() for record in caplog.records)
    assert "tighter than intended" in said


def test_observing_a_slower_feed_does_not_move_the_threshold() -> None:
    """THE SAFETY PROPERTY. A rail that tuned itself would accommodate the very
    degradation it exists to catch."""
    feed = _feed(1200.0)
    before = feed.source_delay_seconds

    _observe(feed, lag_seconds=3600.0)
    feed._check_delay_claim()

    assert feed.source_delay_seconds == before == 1200.0


def test_it_reports_on_the_edge_rather_than_every_interval(caplog) -> None:
    feed = _feed(1200.0)
    _observe(feed, lag_seconds=2100.0)

    with caplog.at_level(logging.WARNING, logger="qat.data.market_data"):
        for _ in range(5):
            feed._check_delay_claim()

    warnings = [r for r in caplog.records if "OUT OF DATE" in r.getMessage()]
    assert len(warnings) == 1


def test_a_recovered_feed_says_so(caplog) -> None:
    feed = _feed(1200.0)
    _observe(feed, lag_seconds=2100.0)
    feed._check_delay_claim()

    feed._observed_lags.clear()
    _observe(feed, lag_seconds=1200.0)
    with caplog.at_level(logging.INFO, logger="qat.data.market_data"):
        feed._check_delay_claim()

    assert any("back in line" in record.getMessage() for record in caplog.records)


def test_a_naive_timestamp_is_skipped_rather_than_guessed_at() -> None:
    """A source that does not say which clock it used cannot be measured against
    ours, and assuming UTC would manufacture a lag rather than observe one."""
    feed = _feed(1200.0)
    arrived = datetime.now(UTC)
    for _ in range(30):
        feed._observe_lag(datetime.now().replace(tzinfo=None), arrived)

    assert feed.observed_delay_seconds() is None


def test_a_bar_stamped_in_the_future_is_not_counted() -> None:
    """A negative lag is a clock problem, not a delay, and averaging it in would
    drag the median toward a reassuring number."""
    feed = _feed(1200.0)
    arrived = datetime.now(UTC)
    for _ in range(30):
        feed._observe_lag(arrived + timedelta(seconds=600), arrived)

    assert feed.observed_delay_seconds() is None


def test_a_real_time_source_expects_no_lag(caplog) -> None:
    """Configured zero, observed zero - the US path must stay quiet."""
    feed = _feed(0.0)
    _observe(feed, lag_seconds=2.0)

    with caplog.at_level(logging.WARNING, logger="qat.data.market_data"):
        feed._check_delay_claim()

    assert not caplog.records
