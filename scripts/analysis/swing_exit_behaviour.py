"""What actually ends a swing trade, and how long it takes.

Replays the real entry rule, the real ATR stop and 2R target, and the two churn
rails against two years of daily bars. The question is not whether the strategy
is profitable - it is what terminates a position, how long that takes, and how
much of the best price is given back by the time it happens.

Read-only. Nothing here touches application state.
"""

from __future__ import annotations

import sys

import pandas as pd
import yfinance as yf

from qat.data.features import compute_atr

SYMBOLS = ["AMAT", "AMD", "CRWD", "CSCO", "GS", "JNJ", "MS", "UNP", "VRTX", "WFC"]

FAST, SLOW, ATR_WINDOW = 20, 50, 14
ATR_STOP_MULTIPLE, REWARD_RISK = 2.5, 2.0
MIN_HOLD_DAYS, TIME_STOP_DAYS = 10, 30
LOSS_ESCAPE_R = 0.5

period = sys.argv[1] if len(sys.argv) > 1 else "2y"
trades: list[dict[str, object]] = []

for symbol in SYMBOLS:
    bars = yf.Ticker(symbol).history(period=period, interval="1d")
    if bars.empty:
        continue
    close, high, low = bars["Close"], bars["High"], bars["Low"]
    fast = close.ewm(span=FAST, adjust=False).mean()
    slow = close.ewm(span=SLOW, adjust=False).mean()
    atr = compute_atr(high, low, close, ATR_WINDOW)

    i = SLOW + 2
    while i < len(close) - 1:
        # --- the real entry rule ---
        if not (fast.iloc[i] > slow.iloc[i]):
            i += 1
            continue
        if not (close.iloc[i - 1] <= fast.iloc[i - 1] and close.iloc[i] > fast.iloc[i]):
            i += 1
            continue
        a = atr.iloc[i]
        if pd.isna(a) or a <= 0:
            i += 1
            continue

        entry = float(close.iloc[i])
        stop = entry - ATR_STOP_MULTIPLE * a
        risk = entry - stop
        target = entry + REWARD_RISK * risk

        best = entry
        best_day = 0
        exit_reason = exit_day = exit_price = None

        for held in range(1, TIME_STOP_DAYS + 1):
            j = i + held
            if j >= len(close):
                break
            bar_low, bar_high, bar_close = (
                float(low.iloc[j]),
                float(high.iloc[j]),
                float(close.iloc[j]),
            )
            if bar_high > best:
                best, best_day = bar_high, held

            # Protective legs rest at the broker and are never delayed.
            if bar_low <= stop:
                exit_reason, exit_day, exit_price = "stop", held, stop
                break
            if bar_high >= target:
                exit_reason, exit_day, exit_price = "target", held, target
                break

            # The signal exit, subject to the minimum hold and its loss escape.
            if fast.iloc[j] <= slow.iloc[j]:
                down_r = (entry - bar_close) / risk
                if held >= MIN_HOLD_DAYS or down_r >= LOSS_ESCAPE_R:
                    exit_reason, exit_day, exit_price = "signal", held, bar_close
                    break

            if held == TIME_STOP_DAYS:
                exit_reason, exit_day, exit_price = "time_stop", held, bar_close

        if exit_reason is None:
            break

        trades.append(
            {
                "symbol": symbol,
                "reason": exit_reason,
                "days": exit_day,
                "r": (exit_price - entry) / risk,
                "mfe_r": (best - entry) / risk,
                "peak_day": best_day,
                "given_back_r": (best - exit_price) / risk,
            }
        )
        i += exit_day + 1

df = pd.DataFrame(trades)
print(f"simulated trades: {len(df)}  ({period} of daily bars, {len(SYMBOLS)} symbols)\n")

print("WHAT ENDS A TRADE")
summary = df.groupby("reason").agg(
    n=("r", "size"),
    pct=("r", lambda s: len(s) / len(df)),
    median_days=("days", "median"),
    mean_r=("r", "mean"),
    mean_mfe_r=("mfe_r", "mean"),
    mean_given_back_r=("given_back_r", "mean"),
)
summary = summary.sort_values("n", ascending=False)
print(summary.to_string(float_format=lambda v: f"{v:,.2f}"))

print(f"\nMedian days to exit, all trades : {df['days'].median():.0f}")
print(f"Median day of the best price    : {df['peak_day'].median():.0f}")
print(f"Mean peak reached (MFE)         : {df['mfe_r'].mean():.2f}R")
print(f"Mean realised                   : {df['r'].mean():.2f}R")
print(f"Mean given back from the peak   : {df['given_back_r'].mean():.2f}R")

held_past_peak = df[df["days"] > df["peak_day"]]
print(
    f"\nTrades still open after their best price: {len(held_past_peak)} of {len(df)} "
    f"({len(held_past_peak) / len(df):.0%}), for a median of "
    f"{(held_past_peak['days'] - held_past_peak['peak_day']).median():.0f} further days"
)
