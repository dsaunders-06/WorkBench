"""Does the correlation window explain why the cluster cap never binds?

M51 measured the correlated-cluster rail as never once the tightest constraint,
median 0% use. The rail is real and the threshold is 0.70. This asks whether
the 300-bar window it measures over is what makes it inert.
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf

SYMBOLS = ["AMAT", "AMD", "CRWD", "CSCO", "GS", "JNJ", "MS", "UNP", "VRTX", "WFC"]
THRESHOLD = 0.70

closes = {}
for symbol in SYMBOLS:
    bars = yf.Ticker(symbol).history(period="2y", interval="1d")
    if not bars.empty:
        closes[symbol] = bars["Close"]

frame = pd.DataFrame(closes).dropna()
returns = frame.pct_change().dropna()
print(f"{len(returns)} overlapping daily returns, {len(frame.columns)} symbols\n")


def pairs_over(window: int) -> tuple[int, int, float, list[str]]:
    corr = returns.tail(window).corr()
    over, total, values = [], 0, []
    for i, a in enumerate(corr.columns):
        for b in corr.columns[i + 1 :]:
            total += 1
            value = corr.loc[a, b]
            values.append(value)
            if value >= THRESHOLD:
                over.append(f"{a}/{b} {value:.2f}")
    return len(over), total, sum(values) / len(values), sorted(over, reverse=True)


print(f"{'window':>8}{'pairs >= 0.70':>16}{'of':>5}{'mean corr':>12}")
for window in (60, 120, 250, 300):
    n, total, mean, _ = pairs_over(min(window, len(returns)))
    print(f"{window:>8}{n:>16}{total:>5}{mean:>12.2f}")

print("\nPairs at or above the 0.70 threshold on a 60-day window:")
_, _, _, over60 = pairs_over(60)
print("  " + (", ".join(over60) if over60 else "(none)"))

print("\nSame pairs measured over the full 300-bar buffer the rail actually uses:")
corr300 = returns.tail(300).corr()
for entry in over60:
    a, b = entry.split()[0].split("/")
    print(f"  {a}/{b}: 60d {corr300.loc[a, b]:.2f} on 300d")
