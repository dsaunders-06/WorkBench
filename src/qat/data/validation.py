"""Bar validation & cleaning: de-dupe, gap-fill, outlier rejection, timezone
alignment, corporate-action adjustment (spec §D/§17.1).

Every function is pure (DataFrame in, DataFrame(s) out) so each safeguard is
independently unit-testable. Bad data is quarantined/flagged and returned
alongside the clean series - never silently dropped or silently used.

Expected bar DataFrame columns: symbol (str), ts (tz-aware datetime64),
open, high, low, close, volume (float).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

import pandas as pd

_OHLC_COLS = ("open", "high", "low", "close")


@dataclass(frozen=True, slots=True)
class GapRecord:
    symbol: str
    expected_ts: datetime


@dataclass(frozen=True, slots=True)
class CorporateAction:
    symbol: str
    ex_date: datetime
    split_ratio: float = 1.0  # e.g. 2.0 for a 2-for-1 split
    dividend: float = 0.0  # cash dividend per share


def dedupe(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop_duplicates(subset=["symbol", "ts"], keep="first").reset_index(drop=True)


def reject_outliers(
    df: pd.DataFrame, max_pct_move: float = 0.2
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split off bars whose close moves more than max_pct_move from the prior
    close for the same symbol. Returned as (clean, quarantined)."""
    ordered = df.sort_values(["symbol", "ts"]).reset_index(drop=True)
    prev_close = ordered.groupby("symbol")["close"].shift(1)
    pct_move = (ordered["close"] - prev_close).abs() / prev_close
    is_outlier = pct_move.gt(max_pct_move).fillna(False)
    clean = ordered.loc[~is_outlier].reset_index(drop=True)
    quarantined = ordered.loc[is_outlier].reset_index(drop=True)
    return clean, quarantined


def detect_and_fill_gaps(
    df: pd.DataFrame, expected_interval: timedelta
) -> tuple[pd.DataFrame, list[GapRecord]]:
    """Forward-fill (flat, zero-volume) any missing expected-interval bars per
    symbol, returning the filled frame plus a record of every gap inserted."""
    filled_frames: list[pd.DataFrame] = []
    gaps: list[GapRecord] = []
    for symbol, group in df.groupby("symbol", sort=False):
        ordered = group.sort_values("ts").reset_index(drop=True)
        rows: list[dict[str, Any]] = [cast(dict[str, Any], ordered.iloc[0].to_dict())]
        for i in range(1, len(ordered)):
            prev_ts: datetime = rows[-1]["ts"]
            current = cast(dict[str, Any], ordered.iloc[i].to_dict())
            missing_ts: datetime = prev_ts + expected_interval
            while missing_ts < current["ts"]:
                gaps.append(GapRecord(symbol=str(symbol), expected_ts=missing_ts))
                last_close = rows[-1]["close"]
                fill = dict(rows[-1])
                fill.update(
                    ts=missing_ts,
                    open=last_close,
                    high=last_close,
                    low=last_close,
                    close=last_close,
                    volume=0.0,
                )
                rows.append(fill)
                missing_ts = missing_ts + expected_interval
            rows.append(current)
        filled_frames.append(pd.DataFrame(rows))
    if not filled_frames:
        return df.copy(), gaps
    result = pd.concat(filled_frames, ignore_index=True)
    return result.sort_values(["symbol", "ts"]).reset_index(drop=True), gaps


def align_timezone(
    df: pd.DataFrame, ts_col: str = "ts", exchange_tz: str = "America/New_York"
) -> pd.DataFrame:
    """Localise naive timestamps to the exchange timezone, then convert to UTC."""
    aligned = df.copy()
    ts = aligned[ts_col]
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize(ZoneInfo(exchange_tz))
    aligned[ts_col] = ts.dt.tz_convert(UTC)
    return aligned


def adjust_for_corporate_actions(
    df: pd.DataFrame, actions: Sequence[CorporateAction]
) -> pd.DataFrame:
    """Back-adjust OHLC/volume for splits and dividends so historical series
    are comparable to current prices. Applied oldest-action-first so later
    actions compound correctly onto already-adjusted earlier bars."""
    if df.empty or not actions:
        return df.copy()

    adjusted = df.copy()
    by_symbol: dict[str, list[CorporateAction]] = {}
    for action in actions:
        by_symbol.setdefault(action.symbol, []).append(action)

    for symbol, symbol_actions in by_symbol.items():
        symbol_mask = adjusted["symbol"] == symbol
        for action in sorted(symbol_actions, key=lambda a: a.ex_date):
            before = symbol_mask & (adjusted["ts"] < action.ex_date)
            if not before.any():
                continue
            price_factor = 1.0 / action.split_ratio
            if action.dividend:
                ref_close = adjusted.loc[before, "close"].iloc[-1]
                if ref_close > 0:
                    price_factor *= 1.0 - (action.dividend / ref_close)
            for col in _OHLC_COLS:
                adjusted.loc[before, col] = adjusted.loc[before, col] * price_factor
            adjusted.loc[before, "volume"] = adjusted.loc[before, "volume"] * action.split_ratio

    return adjusted
