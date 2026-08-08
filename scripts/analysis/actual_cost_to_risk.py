"""What does a round trip actually cost, as a fraction of the risk taken?

I quoted 13.2% from the daily report. Those rows are REFUSALS - candidates the
cost rail rejected precisely because they were too small. This asks the same
question of the ten positions actually held, using the application's own cost
model rather than an assumption.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from qat.config import Settings
from qat.domain.backtester.costs import CostModel

entries = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
settings = Settings(_env_file=None)
costs = CostModel.from_settings(settings)
equity = 101_363.0

held = {
    "AMAT": 7,
    "AMD": 7,
    "CRWD": 16,
    "CSCO": 44,
    "GS": 7,
    "JNJ": 19,
    "MS": 41,
    "UNP": 17,
    "VRTX": 19,
    "WFC": 58,
}

print(
    f"cost model: commission {costs.commission_bps}bps, slippage {costs.slippage_bps}bps, "
    f"floor ${costs.min_commission}, third-party {costs.third_party_bps}bps\n"
)
print(
    f"{'sym':<6}{'qty':>5}{'entry':>10}{'notional':>11}{'risk $':>9}"
    f"{'risk %eq':>10}{'round trip':>12}{'cost/risk':>11}"
)

total_risk = total_notional = total_cost = 0.0
for symbol, qty in held.items():
    d = entries[symbol]
    entry, stop = float(d["price"]), float(d["stop_price"])
    notional = qty * entry
    risk = qty * (entry - stop)
    round_trip = costs.round_trip(notional)
    total_risk += risk
    total_notional += notional
    total_cost += round_trip
    print(
        f"{symbol:<6}{qty:>5}{entry:>10.2f}{notional:>11,.0f}{risk:>9,.0f}"
        f"{risk / equity:>10.2%}{round_trip:>12.2f}{round_trip / risk:>11.1%}"
    )

print(
    f"\n{'TOTAL':<6}{'':>5}{'':>10}{total_notional:>11,.0f}{total_risk:>9,.0f}"
    f"{total_risk / equity:>10.2%}{total_cost:>12.2f}{total_cost / total_risk:>11.1%}"
)
print(
    f"\nmean risk per position : ${total_risk / len(held):,.0f} "
    f"({total_risk / len(held) / equity:.2%} of equity)"
)
print(f"weighted cost / risk   : {total_cost / total_risk:.1%}  <- cost in R per round trip")
print(f"gross exposure         : {total_notional / equity:.1%} of equity")
