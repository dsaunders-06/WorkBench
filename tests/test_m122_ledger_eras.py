"""M122: one ledger, two eras, no way to tell them apart.

`closed_trades.csv` carried no market, no broker and no currency. On 21 August
it held exactly two rows, both from the Alpaca/US period that ended on the 19th:

  * CVS, strategy `swing`, net -482.18 USD - a real trade;
  * MNST, no strategy, no stop, no r-multiple, exit 45.9975 against an entry of
    91.1838. Almost exactly half. That is an unadjusted split recorded as a
    stop-out, and MNST is the case `corporate_actions/monitor.py` names.

Both sat in the file the ASX trial appends to. Two consequences, one of them
silent and one of them expensive:

  * every money total summed USD with AUD and still returned a number;
  * `EdgeEstimator` filters on STRATEGY ALONE, so at swing's twentieth closed
    trade an Alpaca US loss would have been a twentieth of the win rate that
    sets position size.

The trades are not deleted here. They happened, and a ledger that quietly loses
rows is worse than one that mislabels them - so they are LABELLED, and the
readers that must not mix eras are scoped.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest

from qat.config import Settings
from qat.domain.bus import EventBus
from qat.domain.events import OrderFilledEvent
from qat.domain.market_calendar import currency_for
from qat.domain.performance.edge import EdgeEstimator
from qat.domain.performance.metrics import compute_stats
from qat.domain.performance.trades import ClosedTrade, TradeLedger

_BASE = datetime(2026, 8, 21, 2, 0, tzinfo=UTC)


def _settings(tmp_path, market: str) -> Settings:
    return Settings(_env_file=None, data_dir=str(tmp_path), market=market)


async def _ledger(tmp_path, market: str) -> TradeLedger:
    ledger = TradeLedger(EventBus(), tmp_path, settings=_settings(tmp_path, market))
    await ledger.start()
    return ledger


async def _round_trip(ledger: TradeLedger, symbol: str = "RIO.AX") -> None:
    for side, price, day in (("buy", 100.0, 0), ("sell", 110.0, 1)):
        await ledger._on_fill(
            OrderFilledEvent(
                order_id=f"{side}-{symbol}-{day}",
                symbol=symbol,
                side=side,  # type: ignore[arg-type]
                quantity=10,
                price=price,
                strategy="swing",
                stop_price=95.0,
                ts=_BASE + timedelta(days=day),
            )
        )


def test_the_currency_map_covers_every_market() -> None:
    assert currency_for("ASX") == "AUD"
    assert currency_for("US") == "USD"


@pytest.mark.asyncio
async def test_a_closed_trade_records_its_market_and_currency(tmp_path) -> None:
    ledger = await _ledger(tmp_path, "ASX")
    await _round_trip(ledger)

    trade = ledger.closed_trades()[0]
    assert trade.market == "ASX"
    assert trade.currency == "AUD"

    # And it survives the file, which is where the era question actually bites.
    written = (tmp_path / "closed_trades.csv").read_text(encoding="utf-8")
    assert "market" in written.splitlines()[0]
    assert "AUD" in written


@pytest.mark.asyncio
async def test_closed_trades_can_be_scoped_to_one_market(tmp_path) -> None:
    ledger = await _ledger(tmp_path, "ASX")
    await _round_trip(ledger)
    # A row from the previous era, as it reads back off the real file: no
    # market, no currency, because neither column existed when it was written.
    ledger._closed.append(
        ClosedTrade(
            symbol="CVS",
            strategy="swing",
            quantity=47,
            entry_price=105.475,
            exit_price=95.5972,
            stop_price=99.3554,
            opened_at=_BASE - timedelta(days=20),
            closed_at=_BASE - timedelta(days=16),
        )
    )

    assert len(ledger.closed_trades("swing")) == 2
    assert len(ledger.closed_trades("swing", market="ASX")) == 1
    assert ledger.closed_trades("swing", market="ASX")[0].symbol == "RIO.AX"


class _ForeignLedger:
    """Twenty-five closed trades, all from the other market."""

    def __init__(self) -> None:
        self.trades = [
            ClosedTrade(
                symbol="CVS",
                strategy="swing",
                quantity=10,
                entry_price=100.0,
                exit_price=90.0,
                stop_price=95.0,
                opened_at=_BASE,
                closed_at=_BASE + timedelta(days=1),
                market="US",
                currency="USD",
            )
            for _ in range(25)
        ]

    def closed_trades(self, strategy=None, market=None):
        found = [t for t in self.trades if strategy is None or t.strategy == strategy]
        if market is not None:
            found = [t for t in found if t.market == market]
        return found


def test_edge_does_not_measure_itself_on_another_markets_trades(tmp_path) -> None:
    """The expensive one. Twenty-five US losses are past `edge_min_trades`, so
    without scoping this returns a MEASURED edge - a 0% win rate on another
    broker in another currency - and that number sets position size."""
    settings = _settings(tmp_path, "ASX")
    edge = EdgeEstimator(_ForeignLedger(), settings=settings)

    result = edge.estimate("swing")

    assert result.source == "default", "US trades must not measure the ASX trial"
    assert result.trade_count == 0


def test_mixed_currency_totals_are_called_out(caplog) -> None:
    trades = [
        ClosedTrade(
            symbol=symbol,
            strategy="swing",
            quantity=10,
            entry_price=100.0,
            exit_price=exit_price,
            stop_price=95.0,
            opened_at=_BASE,
            closed_at=_BASE + timedelta(days=1),
            market=market,
            currency=currency,
        )
        for symbol, exit_price, market, currency in (
            ("CVS", 90.0, "US", "USD"),
            ("RIO.AX", 110.0, "ASX", "AUD"),
        )
    ]

    with caplog.at_level(logging.ERROR, logger="qat.domain.performance.metrics"):
        stats = compute_stats(trades)

    assert stats.trade_count == 2  # it still computes...
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "MIXED-CURRENCY" in messages  # ...but it says the total is meaningless
    assert "AUD" in messages and "USD" in messages


def test_one_currency_is_not_warned_about(caplog) -> None:
    """The guard must be quiet in the ordinary case, or it becomes noise."""
    trades = [
        ClosedTrade(
            symbol="RIO.AX",
            strategy="swing",
            quantity=10,
            entry_price=100.0,
            exit_price=110.0,
            stop_price=95.0,
            opened_at=_BASE,
            closed_at=_BASE + timedelta(days=1),
            market="ASX",
            currency="AUD",
        )
    ]

    with caplog.at_level(logging.ERROR, logger="qat.domain.performance.metrics"):
        compute_stats(trades)

    assert not [r for r in caplog.records if "MIXED-CURRENCY" in r.getMessage()]
