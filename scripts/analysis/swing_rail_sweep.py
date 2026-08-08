"""Does holding for 30 days buy anything the move has not already given?

Same replay, sweeping the two churn rails. Decision support only - nothing here
changes configuration, and the freeze still owns that decision.
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf

from qat.data.features import compute_atr

SYMBOLS = ["AMAT", "AMD", "CRWD", "CSCO", "GS", "JNJ", "MS", "UNP", "VRTX", "WFC"]
FAST, SLOW, ATR_WINDOW = 20, 50, 14
ATR_STOP_MULTIPLE, REWARD_RISK, LOSS_ESCAPE_R = 2.5, 2.0, 0.5

bars_by_symbol = {}
for symbol in SYMBOLS:
    bars = yf.Ticker(symbol).history(period="2y", interval="1d")
    if not bars.empty:
        bars_by_symbol[symbol] = bars


def replay(min_hold: int, time_stop: int) -> pd.DataFrame:
    trades = []
    for _symbol, bars in bars_by_symbol.items():
        close, high, low = bars["Close"], bars["High"], bars["Low"]
        fast = close.ewm(span=FAST, adjust=False).mean()
        slow = close.ewm(span=SLOW, adjust=False).mean()
        atr = compute_atr(high, low, close, ATR_WINDOW)

        i = SLOW + 2
        while i < len(close) - 1:
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
            reason = day = price = None

            for held in range(1, time_stop + 1):
                j = i + held
                if j >= len(close):
                    break
                bl, bh, bc = float(low.iloc[j]), float(high.iloc[j]), float(close.iloc[j])
                best = max(best, bh)
                if bl <= stop:
                    reason, day, price = "stop", held, stop
                    break
                if bh >= target:
                    reason, day, price = "target", held, target
                    break
                if fast.iloc[j] <= slow.iloc[j]:
                    if held >= min_hold or (entry - bc) / risk >= LOSS_ESCAPE_R:
                        reason, day, price = "signal", held, bc
                        break
                if held == time_stop:
                    reason, day, price = "time_stop", held, bc

            if reason is None:
                break
            trades.append(
                {
                    "reason": reason,
                    "days": day,
                    "r": (price - entry) / risk,
                    "given_back_r": (best - price) / risk,
                }
            )
            i += day + 1
    return pd.DataFrame(trades)


print("Sweeping the time stop, minimum hold held at 10\n")
print(
    f"{'time stop':>10}{'trades':>8}{'mean R':>9}{'med days':>10}"
    f"{'given back':>12}{'R/yr/slot':>11}"
)
for time_stop in (8, 10, 12, 15, 20, 30, 45):
    df = replay(10, time_stop)
    # What a single position slot earns per year: expectancy per trade divided
    # by how long the trade occupies the slot.
    per_year = df["r"].mean() * (250.0 / df["days"].mean())
    print(
        f"{time_stop:>10}{len(df):>8}{df['r'].mean():>9.2f}{df['days'].median():>13.0f}"
        f"{df['given_back_r'].mean():>12.2f}{per_year:>11.2f}"
    )

print("\nSweeping the minimum hold, time stop held at 30\n")
print(f"{'min hold':>10}{'trades':>8}{'mean R':>9}{'signal exits':>14}{'given back':>12}")
for min_hold in (0, 3, 5, 10, 15):
    df = replay(min_hold, 30)
    signals = int((df["reason"] == "signal").sum())
    print(
        f"{min_hold:>10}{len(df):>8}{df['r'].mean():>9.2f}"
        f"{signals:>8} ({signals / len(df):>3.0%}){df['given_back_r'].mean():>12.2f}"
    )
