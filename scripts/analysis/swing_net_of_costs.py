"""The same comparison, net of what a round trip actually costs.

Gross R flatters anything that trades more often. The live cost rail measures a
$18.24 round trip against roughly $138 at risk - 0.13R a trade - and that is
charged here, because it is the number that decides between these variants.
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf

from qat.data.features import compute_atr

SYMBOLS = ["AMAT", "AMD", "CRWD", "CSCO", "GS", "JNJ", "MS", "UNP", "VRTX", "WFC"]
FAST, SLOW, ATR_WINDOW = 20, 50, 14
ATR_STOP_MULTIPLE, REWARD_RISK, LOSS_ESCAPE_R = 2.5, 2.0, 0.5
# $187.50 of round trips across $4,977 of risk on the ten positions ACTUALLY
# held, priced by the app's own CostModel. The 0.132 used earlier came from the
# report's refusal rows - candidates the cost rail rejected for being too
# small - which is the rejected population, not the accepted one.
COST_R = 0.038

bars_by_symbol = {}
for symbol in SYMBOLS:
    bars = yf.Ticker(symbol).history(period="2y", interval="1d")
    if not bars.empty:
        bars_by_symbol[symbol] = bars


def replay(variant: str, min_hold: int = 10, time_stop: int = 30) -> pd.DataFrame:
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
            best, live_stop = entry, stop
            reason = day = price = None

            for held in range(1, time_stop + 1):
                j = i + held
                if j >= len(close):
                    break
                bl, bh, bc = float(low.iloc[j]), float(high.iloc[j]), float(close.iloc[j])
                if bl <= live_stop:
                    reason, day, price = "stop", held, live_stop
                    break
                if bh >= target:
                    reason, day, price = "target", held, target
                    break
                best = max(best, bh)
                if variant == "trail_1atr":
                    live_stop = max(live_stop, best - 1.0 * float(atr.iloc[j]))
                elif variant == "trail_2atr":
                    live_stop = max(live_stop, best - 2.0 * float(atr.iloc[j]))
                if fast.iloc[j] <= slow.iloc[j] and (
                    held >= min_hold or (entry - bc) / risk >= LOSS_ESCAPE_R
                ):
                    reason, day, price = "signal", held, bc
                    break
                if held == time_stop:
                    reason, day, price = "time_stop", held, bc

            if reason is None:
                break
            trades.append({"days": day, "r": (price - entry) / risk})
            i += day + 1
    return pd.DataFrame(trades)


def report(label: str, df: pd.DataFrame) -> None:
    gross, mean_days = df["r"].mean(), df["days"].mean()
    net = gross - COST_R
    turns = 250.0 / mean_days
    print(
        f"{label:<22}{len(df):>7}{gross:>9.2f}{net:>9.2f}{turns:>9.1f}"
        f"{gross * turns:>11.2f}{net * turns:>11.2f}"
    )


print(f"Charging {COST_R:.3f}R a round trip\n")
head = (
    f"{'':<22}{'trades':>7}{'gross R':>9}{'net R':>9}{'turns/yr':>9}{'gross/yr':>11}{'net/yr':>11}"
)

print("EXIT VARIANTS (time stop 30, min hold 10)")
print(head)
for variant in ("baseline", "trail_2atr", "trail_1atr"):
    report(variant, replay(variant))

print("\nTIME STOP (baseline exits)")
print(head)
for time_stop in (10, 15, 20, 30, 45):
    report(f"time stop {time_stop}", replay("baseline", time_stop=time_stop))
