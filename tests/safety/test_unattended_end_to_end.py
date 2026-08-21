"""The whole unattended path, once, from a price tick to a filled order.

Every part of this chain has tests. The chain itself has never had one, and
has never run: after four live sessions `decision_journal.csv` and
`risk_decisions.csv` had still never been written, because no signal ever
reached them. Each session failed for a different reason upstream, and each
time the parts below were assumed to work because their own tests passed.

Built on the real Runtime rather than hand-wired parts, so it exercises the
same graph a session does - including the deployment that M27b made
configurable, without which nothing downstream is reachable at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pandas as pd
import pytest

from qat.config import Settings
from qat.domain import market_calendar as mc
from qat.domain.events import MarketDataEvent, RegimeEvent
from qat.domain.regime import Regime
from qat.presentation.runtime import Runtime

_SYMBOL = "AAPL"


def _uptrend(days: int, last_day: datetime) -> pd.DataFrame:
    """A clean EMA20 > EMA50 uptrend, ending the day before `last_day`.

    Priced to finish near MockBroker's synthetic quote. The autonomy gate
    refuses an order whose price has drifted more than 3% from the price it was
    sized against, and it is right to: sizing, stop and target would all be
    stale. A series ending anywhere else fails on that rail rather than on the
    thing under test.
    """
    closes = [60.0 + i * 0.32 for i in range(days)]
    return pd.DataFrame(
        [
            {
                "ts": last_day - timedelta(days=days - i),
                "open": close * 0.995,
                "high": close * 1.01,
                "low": close * 0.985,
                "close": close,
                "volume": 1_000_000.0,
            }
            for i, close in enumerate(closes)
        ]
    )


def _runtime(data_dir: str) -> Runtime:
    return Runtime.build_demo(
        settings=Settings(
            _env_file=None,
            data_dir=data_dir,
            execution_mode="auto",
            autonomous_strategies="swing",
            deployed_strategies="swing",
            market_data_source="synthetic",
            broker="mock",
            bar_interval_seconds=86_400.0,
        ),
        watchlist=(_SYMBOL,),
    )


@pytest.mark.asyncio
async def test_a_configured_strategy_is_live_without_anyone_clicking_anything(tmp_path):
    runtime = _runtime(str(tmp_path))

    assert [s.name for s in runtime.strategy_engine.strategies] == ["swing"]


@pytest.mark.asyncio
async def test_a_tick_becomes_a_signed_order_and_a_journal_entry(tmp_path):
    """The end-to-end claim, asserted rather than assumed.

    Two ticks, because that is what the live path needs: the bridge sizes from
    its own aggregator and refuses below two bars, so the first tick opens its
    history and the second completes swing's pullback-and-reclaim.
    """
    runtime = _runtime(str(tmp_path))
    # No warm start: this test supplies its own history, and the real one
    # would reach for a vendor.
    runtime.orchestrator._engines = [
        e for e in runtime.orchestrator._engines if e.name != "warm-start"
    ]
    # The autonomy gate refuses a shut market, so the clock is pinned to a
    # real trading session rather than to whenever the suite happens to run.
    # 29 July 2026 is a Wednesday and 15:00 UTC is 11:00 in New York, inside
    # the "Morning Trend" phase that permits unattended execution.
    runtime.autonomy_gate.clock = lambda: datetime(2026, 7, 29, 15, 0, tzinfo=UTC)

    # M120. Was `datetime.now(UTC).replace(hour=12, ...)`, which is a UTC date
    # and not a trading day. The bars below are keyed on the exchange's date, so
    # whenever the market's date lagged the UTC one - every run between 00:00
    # UTC and the exchange catching up - this fixture dated itself into the
    # future and no order was ever placed. CI passed at 23:14 UTC on 20 August
    # and the same commit failed at 00:30 UTC on the 21st.
    session_day = mc.trading_date("US", datetime.now(UTC))
    today = datetime.combine(session_day, time(12, 0), tzinfo=UTC)
    history = _uptrend(days=118, last_day=today - timedelta(days=1))
    runtime.strategy_engine.bars.seed(_SYMBOL, history, now=today - timedelta(days=2))
    # The bridge keeps its own aggregator and sizes the order from it, which is
    # why WarmStart seeds all three in the live app. Seeding only the strategy
    # engine here would leave the stop and the position size computed from an
    # empty buffer - the exact bug M27a's third item exists to prevent.
    bridge = next(e for e in runtime.orchestrator._engines if e.name == "signal-to-order-bridge")
    bridge.bars.seed(_SYMBOL, history, now=today - timedelta(days=2))

    trend_close = float(history["close"].iloc[-1])
    pullback = trend_close * 0.955  # dips below EMA20
    reclaim = trend_close * 1.02  # and closes back above it

    await runtime.orchestrator.start_all()
    try:
        await runtime.bus.publish(
            RegimeEvent(
                label=Regime.BULL.value,
                probs={Regime.BULL.value: 1.0},
                exposure_scalar=1.0,
                ts=today,
            )
        )
        await runtime.bus.publish(
            MarketDataEvent(
                symbol=_SYMBOL, price=pullback, volume=1e6, ts=today - timedelta(days=1)
            )
        )
        await runtime.bus.publish(
            MarketDataEvent(symbol=_SYMBOL, price=reclaim, volume=1e6, ts=today)
        )
    finally:
        await runtime.orchestrator.stop_all()

    positions = await runtime.broker.positions()
    assert positions, "no order reached the broker - the unattended path is still unproven"
    assert positions[0].symbol == _SYMBOL
    assert positions[0].quantity > 0

    journal = tmp_path / "decision_journal.csv"
    assert journal.exists(), "the decision journal is still unwritten after a filled order"
    assert "swing" in journal.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_an_unknown_strategy_name_is_reported_not_ignored(caplog):
    """A typo here costs a whole session, and looks exactly like a market with
    no setups."""
    import logging

    with caplog.at_level(logging.ERROR, logger="qat.presentation.runtime"):
        runtime = Runtime.build_demo(
            settings=Settings(_env_file=None, deployed_strategies="swng,swing")
        )

    assert [s.name for s in runtime.strategy_engine.strategies] == ["swing"]
    assert "swng" in caplog.text
    assert "do not exist" in caplog.text
