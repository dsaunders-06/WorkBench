"""M111: UTC stood in for the trading day, and the ASX is about to move.

Australian Eastern time is UTC+10 until the first Sunday in October and UTC+11
after it. Today, 20 August, the ASX session runs 00:00-06:00 UTC, so a UTC
calendar date and an ASX trading date are the same thing and nothing that
confuses them can be caught. `market_calendar` even says so in a comment:
"the ASX trades 00:00-06:00 UTC".

From Monday 5 October 2026 that is false. The session runs 23:00 UTC on the
previous day to 05:00 UTC, and **crosses UTC midnight at 11:00 AEDT - one hour
after the open.** Two things key the trading day on UTC:

* `EquityMonitor._refresh_state` re-baselines `day_start_equity` when the UTC
  date changes, and it is called every 60 seconds. An hour into the session it
  would log "New trading day", forget the morning, and hand a book already down
  2% a fresh 3% of room. That is a RISK RAIL resetting mid-session.
* `floor_to_interval` bins on raw epoch seconds, so an 86,400-second bar starts
  at UTC midnight. Each ASX session would produce two partial "daily" bars, and
  `bars[-2]` - the pullback leg the swing entry reads - would change an hour
  into the session.

The exchange's own date is the trading day. `market_calendar` already carries
`ASX_TZ` and is DST-aware, so this is about routing through it, not about
teaching the system what a timezone is.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.bars import BarAggregator, floor_to_interval
from qat.domain.autonomy.equity_monitor import EquityMonitor
from qat.domain.market_calendar import trading_date
from qat.domain.risk_engine.kill_switch import KillSwitch

SYD = ZoneInfo("Australia/Sydney")

# 5 October 2026 is the first ASX trading day on AEDT (UTC+11).
OPEN_5_OCT = datetime(2026, 10, 5, 10, 30, tzinfo=SYD)  # 2026-10-04 23:30 UTC
LATER_5_OCT = datetime(2026, 10, 5, 11, 30, tzinfo=SYD)  # 2026-10-05 00:30 UTC
NEXT_DAY = datetime(2026, 10, 6, 10, 30, tzinfo=SYD)  # a genuinely new session


def test_the_dates_this_milestone_turns_on_are_what_we_think() -> None:
    """Guards the premise. If these two moments ever stop straddling UTC
    midnight the tests below would pass for no reason at all."""
    assert OPEN_5_OCT.astimezone(UTC).date().day == 4
    assert LATER_5_OCT.astimezone(UTC).date().day == 5
    assert OPEN_5_OCT.utcoffset().total_seconds() == 11 * 3600


def test_trading_date_is_the_exchange_date_not_the_utc_date() -> None:
    assert trading_date("ASX", OPEN_5_OCT).isoformat() == "2026-10-05"
    assert trading_date("ASX", LATER_5_OCT).isoformat() == "2026-10-05"
    # ...and the UTC date disagrees with the first of those, which is the bug.
    assert OPEN_5_OCT.astimezone(UTC).date().isoformat() == "2026-10-04"


def test_trading_date_still_works_for_the_US_market() -> None:
    """Not an ASX-only helper. A US session at 09:30 ET on 5 October is
    13:30 UTC the same day, so nothing changes there - which is the point:
    one helper, right in both markets."""
    ny = datetime(2026, 10, 5, 9, 30, tzinfo=ZoneInfo("America/New_York"))

    assert trading_date("US", ny).isoformat() == "2026-10-05"


class _Broker:
    def __init__(self, equity: float) -> None:
        self.equity = equity

    async def account(self) -> object:
        class _A:
            net_liquidation = self.equity
            cash = self.equity

        return _A()


def _monitor(tmp_path: Path, clock_value: list[datetime], equity: float) -> EquityMonitor:
    """Its OWN data_dir, per the standing rule."""
    settings = Settings(_env_file=None, data_dir=str(tmp_path), market="ASX")
    return EquityMonitor(
        _Broker(equity),
        KillSwitch(),
        settings=settings,
        data_dir=tmp_path,
        clock=lambda: clock_value[0],
    )


@pytest.mark.asyncio
async def test_the_daily_loss_baseline_survives_utc_midnight_mid_session(
    tmp_path: Path,
) -> None:
    """THE DEFECT. Both polls are inside one ASX session on 5 October; only
    the UTC date changes between them. `day_start_equity` must not move."""
    now = [OPEN_5_OCT]
    monitor = _monitor(tmp_path, now, equity=1_000_000.0)

    opening = await monitor.poll()
    assert opening.day_start_equity == 1_000_000.0

    now[0] = LATER_5_OCT
    monitor.broker.equity = 970_000.0  # down 3% in the first hour
    later = await monitor.poll()

    assert later.day_start_equity == 1_000_000.0, (
        "the baseline re-armed an hour into the session, so a book already "
        "down 3% would be handed a fresh 3% of room"
    )
    assert monitor.day_pnl_pct(970_000.0) == pytest.approx(-0.03)


@pytest.mark.asyncio
async def test_a_genuinely_new_session_does_re_baseline(tmp_path: Path) -> None:
    """The other half. Fixing the false rollover must not remove the real one,
    or the daily loss limit would measure from the first day it ever ran."""
    now = [LATER_5_OCT]
    monitor = _monitor(tmp_path, now, equity=970_000.0)
    await monitor.poll()

    now[0] = NEXT_DAY
    monitor.broker.equity = 965_000.0
    tomorrow = await monitor.poll()

    assert tomorrow.day_start_equity == 965_000.0
    assert tomorrow.high_water_mark == 970_000.0, "drawdown-from-peak is not a daily measure"


# --- the daily bar boundary --------------------------------------------------


def test_a_daily_bar_does_not_split_when_the_session_crosses_utc_midnight() -> None:
    """THE SECOND DEFECT. Both ticks are inside the 5 October ASX session.
    A daily bar must contain both, or `bars[-2]` - the pullback leg the swing
    entry reads - changes an hour into the session, and today's high and low
    are computed over one hour instead of six."""
    agg = BarAggregator(interval_seconds=86_400.0, tz=SYD)

    agg.add_tick(OPEN_5_OCT, 100.0)
    agg.add_tick(LATER_5_OCT, 101.0)

    assert agg.completed_bars() == [], "the session was split into two daily bars"
    forming = agg.forming
    assert forming is not None
    assert (forming.open, forming.high, forming.low, forming.close) == (100.0, 101.0, 100.0, 101.0)


def test_a_real_session_change_still_closes_the_bar() -> None:
    """Fixing the false split must not stop daily bars closing at all."""
    agg = BarAggregator(interval_seconds=86_400.0, tz=SYD)
    agg.add_tick(OPEN_5_OCT, 100.0)
    agg.add_tick(LATER_5_OCT, 101.0)

    agg.add_tick(NEXT_DAY, 102.0)

    completed = agg.completed_bars()
    assert len(completed) == 1
    assert completed[0].close == 101.0


def test_without_a_timezone_the_old_utc_split_is_what_happens() -> None:
    """Pins the defect itself, so the fix is visible rather than asserted.
    This is exactly what the running build does today, and it is harmless only
    because AEST puts the whole session inside one UTC date."""
    agg = BarAggregator(interval_seconds=86_400.0)

    agg.add_tick(OPEN_5_OCT, 100.0)
    agg.add_tick(LATER_5_OCT, 101.0)

    assert len(agg.completed_bars()) == 1, "expected the un-fixed UTC-midnight split"


def test_intraday_bars_stay_epoch_anchored_even_with_a_timezone() -> None:
    """The epoch anchor exists so two symbols that started streaming at
    different moments still land on the same boundaries - cross-sectional
    work (breadth, relative strength, pairs) depends on it. A timezone must
    change the DAILY boundary only."""
    moment = datetime(2026, 10, 5, 10, 37, 42, tzinfo=SYD)

    assert floor_to_interval(moment, 60.0, tz=SYD) == floor_to_interval(moment, 60.0)
    assert floor_to_interval(moment, 300.0, tz=SYD) == floor_to_interval(moment, 300.0)


def test_the_daily_boundary_is_local_midnight_in_both_offsets() -> None:
    """AEST and AEDT, so the fix is not accidentally right for one of them."""
    aest = datetime(2026, 8, 20, 11, 11, tzinfo=SYD)  # UTC+10
    aedt = datetime(2026, 10, 5, 11, 30, tzinfo=SYD)  # UTC+11

    assert floor_to_interval(aest, 86_400.0, tz=SYD).astimezone(SYD).hour == 0
    assert floor_to_interval(aedt, 86_400.0, tz=SYD).astimezone(SYD).hour == 0
    assert floor_to_interval(aedt, 86_400.0, tz=SYD).astimezone(SYD).date().isoformat() == (
        "2026-10-05"
    )


# --- the wiring, which is the half that silently does nothing ----------------


def test_the_runtime_gives_every_daily_aggregator_the_market_timezone() -> None:
    """Four call sites had to be changed for this fix to reach the app, and a
    fix that is wired everywhere except one place is worse than no fix: the
    aggregators would disagree with each other about which day it is.

    This project's recurring failure is machinery that is built and never
    reached - `resolve_broker` refusing `ibkr` while a whole adapter sat behind
    it (M101), and M70/M71 going dormant on IBKR without erroring. Assert the
    wiring, not just the mechanism.
    """
    from qat.domain.market_calendar import ASX_TZ
    from qat.presentation.runtime import Runtime

    runtime = Runtime.build_demo(
        settings=Settings(_env_file=None, market="ASX", bar_interval_seconds=86_400.0)
    )

    assert runtime.strategy_engine.bars.tz == ASX_TZ
    assert runtime.signal_bridge is not None
    assert runtime.signal_bridge.bars.tz == ASX_TZ
    assert runtime.regime_engine.bar_tz == ASX_TZ

    feature_engines = [e for e in runtime.orchestrator._engines if hasattr(e, "bars")]
    assert feature_engines, "no engine with a bar buffer was registered"
    for engine in feature_engines:
        assert engine.bars.tz == ASX_TZ, f"{type(engine).__name__} kept the UTC boundary"


def test_a_US_runtime_gets_new_york_not_sydney() -> None:
    """The helper is market-driven, not ASX-hardcoded. A US session does not
    cross UTC midnight, so this changes nothing there - which is the point."""
    from qat.domain.market_calendar import US_TZ
    from qat.presentation.runtime import Runtime

    runtime = Runtime.build_demo(
        settings=Settings(_env_file=None, market="US", bar_interval_seconds=86_400.0)
    )

    assert runtime.strategy_engine.bars.tz == US_TZ


# --- the part that is wrong TODAY, not in October ----------------------------


def _asx_daily_frame() -> pd.DataFrame:
    """Three ASX daily bars in the shape yfinance actually returns them:
    midnight, exchange-local, tz-aware. Verified against a live RIO.AX pull on
    20 August - `2026-08-20 00:00:00+10:00`."""
    return pd.DataFrame(
        {
            "ts": pd.to_datetime(
                [
                    "2026-08-18 00:00+10:00",
                    "2026-08-19 00:00+10:00",
                    "2026-08-20 00:00+10:00",
                ]
            ),
            "open": [1.0, 2.0, 3.0],
            "high": [1.0, 2.0, 3.0],
            "low": [1.0, 2.0, 3.0],
            "close": [10.0, 20.0, 30.0],
            "volume": [1.0, 1.0, 1.0],
        }
    )


def test_todays_partial_session_is_seeded_as_the_forming_bar() -> None:
    """`seed` documents this exactly: "A vendor's daily bar for *today* is a
    partial session, so it is loaded as the *forming* bar rather than a
    completed one... admitting it as completed would leave today represented
    twice."

    On the ASX it did the opposite, and had since the move. A bar stamped
    `2026-08-20 00:00+10:00` is `2026-08-19 14:00` UTC, which floors to the
    19th - earlier than the current UTC boundary - so today's HALF-FINISHED
    session was admitted as a closed bar for yesterday, and the strategy's
    "previous bar" contained today's prices.
    """
    mid_session = datetime(2026, 8, 20, 11, 11, tzinfo=SYD)
    agg = BarAggregator(interval_seconds=86_400.0, tz=SYD)

    agg.seed(_asx_daily_frame(), now=mid_session)

    forming = agg.forming
    assert forming is not None, "today's partial session was admitted as a completed bar"
    assert forming.close == 30.0
    assert forming.ts.astimezone(SYD).date().isoformat() == "2026-08-20"
    assert [b.ts.astimezone(SYD).date().isoformat() for b in agg.completed_bars()] == [
        "2026-08-18",
        "2026-08-19",
    ]


def test_the_seeded_bars_carry_the_date_the_exchange_traded_them() -> None:
    """The label shift on its own. Every seeded ASX daily bar was stamped one
    day early, so anything reading a bar's date - a chart axis, a replay
    window, a manifest - read the wrong day."""
    agg = BarAggregator(interval_seconds=86_400.0, tz=SYD)
    agg.seed(_asx_daily_frame(), now=datetime(2026, 8, 20, 11, 11, tzinfo=SYD))

    first = agg.completed_bars()[0]

    assert first.close == 10.0
    assert first.ts.astimezone(SYD).date().isoformat() == "2026-08-18"
