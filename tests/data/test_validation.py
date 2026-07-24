from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from qat.data.validation import (
    CorporateAction,
    adjust_for_corporate_actions,
    align_timezone,
    dedupe,
    detect_and_fill_gaps,
    reject_outliers,
)


def _row(symbol: str, ts: datetime, price: float, volume: float = 100.0) -> dict[str, object]:
    return {
        "symbol": symbol,
        "ts": ts,
        "open": price,
        "high": price,
        "low": price,
        "close": price,
        "volume": volume,
    }


def test_dedupe_keeps_first_of_duplicate_symbol_ts():
    ts = datetime(2024, 1, 2, tzinfo=UTC)
    df = pd.DataFrame([_row("AAPL", ts, 1.0), _row("AAPL", ts, 2.0)])

    result = dedupe(df)

    assert len(result) == 1
    assert result.iloc[0]["close"] == 1.0


def test_reject_outliers_quarantines_large_moves_not_silently():
    ts0 = datetime(2024, 1, 1, tzinfo=UTC)
    df = pd.DataFrame(
        [
            _row("AAPL", ts0, 100.0),
            _row("AAPL", ts0 + timedelta(days=1), 101.0),
            _row("AAPL", ts0 + timedelta(days=2), 500.0),  # spike
        ]
    )

    clean, quarantined = reject_outliers(df, max_pct_move=0.2)

    assert len(clean) == 2
    assert len(quarantined) == 1
    assert quarantined.iloc[0]["close"] == 500.0
    assert 500.0 not in clean["close"].values


def test_detect_and_fill_gaps_inserts_flat_bars_and_reports_them():
    ts0 = datetime(2024, 1, 1, tzinfo=UTC)
    interval = timedelta(days=1)
    df = pd.DataFrame(
        [
            _row("AAPL", ts0, 10.0),
            _row("AAPL", ts0 + 3 * interval, 13.0),  # days 1, 2 missing
        ]
    )

    filled, gaps = detect_and_fill_gaps(df, interval)

    assert len(filled) == 4
    assert len(gaps) == 2
    assert filled.iloc[1]["close"] == 10.0  # forward-filled from previous close
    assert filled.iloc[1]["volume"] == 0.0
    assert filled.iloc[3]["close"] == 13.0


def test_align_timezone_localizes_naive_then_converts_to_utc():
    naive_ts = datetime(2024, 1, 2, 9, 30)  # naive, treated as exchange-local
    df = pd.DataFrame([_row("AAPL", naive_ts, 1.0)])

    aligned = align_timezone(df, exchange_tz="America/New_York")
    result_ts = aligned.iloc[0]["ts"]

    assert result_ts.tzinfo is not None
    # 09:30 America/New_York in January (EST, UTC-5) -> 14:30 UTC
    assert result_ts.hour == 14
    assert result_ts.minute == 30


def test_adjust_for_corporate_actions_split_halves_price_and_doubles_volume():
    ts0 = datetime(2024, 1, 1, tzinfo=UTC)
    ex_date = datetime(2024, 1, 3, tzinfo=UTC)
    df = pd.DataFrame(
        [
            _row("AAPL", ts0, 200.0, volume=100.0),
            _row("AAPL", ex_date, 100.0, volume=200.0),  # already post-split
        ]
    )
    actions = [CorporateAction(symbol="AAPL", ex_date=ex_date, split_ratio=2.0)]

    adjusted = adjust_for_corporate_actions(df, actions)

    assert adjusted.iloc[0]["close"] == pytest.approx(100.0)
    assert adjusted.iloc[0]["volume"] == pytest.approx(200.0)
    assert adjusted.iloc[1]["close"] == pytest.approx(100.0)  # on/after ex-date: unaffected


def test_adjust_for_corporate_actions_dividend_reduces_historical_price():
    ts0 = datetime(2024, 1, 1, tzinfo=UTC)
    ex_date = datetime(2024, 1, 3, tzinfo=UTC)
    df = pd.DataFrame(
        [
            _row("AAPL", ts0, 101.0),
            _row("AAPL", ex_date, 100.0),
        ]
    )
    actions = [CorporateAction(symbol="AAPL", ex_date=ex_date, dividend=1.0)]

    adjusted = adjust_for_corporate_actions(df, actions)

    expected = 101.0 * (1.0 - 1.0 / 101.0)
    assert adjusted.iloc[0]["close"] == pytest.approx(expected)
    assert adjusted.iloc[1]["close"] == pytest.approx(100.0)


def test_adjust_for_corporate_actions_with_no_actions_returns_copy():
    ts0 = datetime(2024, 1, 1, tzinfo=UTC)
    df = pd.DataFrame([_row("AAPL", ts0, 100.0)])

    adjusted = adjust_for_corporate_actions(df, [])

    assert adjusted.iloc[0]["close"] == 100.0
