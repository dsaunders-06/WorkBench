"""What would changing position size actually buy?

Two parts. First the cost curve, which is pure arithmetic over the app's own
cost model and is therefore trustworthy. Then the constraint arithmetic, which
is what makes the sizing question narrower than it looks.
"""

from __future__ import annotations

from qat.config import Settings
from qat.domain.backtester.costs import CostModel

settings = Settings(_env_file=None)
costs = CostModel.from_settings(settings)
EQUITY = 101_363.0

# Measured on the ten held positions: $4,977 of risk against $55,502 of
# notional. The stop sits about 9% below entry on average.
RISK_PER_NOTIONAL = 4_977 / 55_502

print(
    f"cost model: {costs.commission_bps}bps commission (floor ${costs.min_commission}), "
    f"{costs.slippage_bps}bps slippage"
)
print(f"measured stop distance: {RISK_PER_NOTIONAL:.1%} of notional\n")

print("COST AS A FRACTION OF RISK, BY POSITION SIZE")
print(f"{'notional':>10}{'risk $':>9}{'round trip':>12}{'cost/risk':>11}{'':>4}")
for notional in (2_000, 3_500, 5_550, 8_000, 10_000, 13_200, 20_000, 40_000):
    risk = notional * RISK_PER_NOTIONAL
    rt = costs.round_trip(notional)
    marker = (
        "  <- today" if notional == 5_550 else ("  <- floor escaped" if notional == 13_200 else "")
    )
    print(f"{notional:>10,}{risk:>9,.0f}{rt:>12.2f}{rt / risk:>11.2%}{marker}")

floor_crossover = costs.min_commission / (costs.commission_bps / 10_000.0)
print(f"\nThe commission floor stops binding at ${floor_crossover:,.0f} of notional.")
print("Above it, cost is proportional and cost/risk is flat - more size buys nothing further.\n")

print("THE CONSTRAINT THAT MAKES THIS NARROW")
cap = settings.max_aggregate_risk_at_stop_pct
limit = settings.max_concurrent_positions
print(f"  aggregate risk-at-stop cap : {cap:.0%}")
print(f"  max concurrent positions   : {limit}")
print(f"  => per-position risk is pinned at {cap / limit:.2%} of equity when the book is full")
print("  observed                   : 0.49% - the book is already at the ceiling\n")

print("WHAT EACH OPTION ACTUALLY DOES")
print(
    f"{'':<26}{'posns':>7}{'risk/ea':>9}{'aggregate':>11}{'notional':>10}"
    f"{'cost/risk':>11}{'trades/yr':>11}"
)
scenarios = [
    ("A  today", 10, 0.0049),
    ("B  fewer, larger", 5, 0.0100),
    ("C  same count, 2x cap", 10, 0.0100),
    ("D  fewer, much larger", 4, 0.0125),
]
TURNS_PER_SLOT = 250 / 16.3  # mean holding from the replay
for label, positions, risk_pct in scenarios:
    risk_dollars = EQUITY * risk_pct
    notional = risk_dollars / RISK_PER_NOTIONAL
    rt = costs.round_trip(notional)
    print(
        f"{label:<26}{positions:>7}{risk_pct:>9.2%}{positions * risk_pct:>11.1%}"
        f"{notional:>10,.0f}{rt / risk_dollars:>11.2%}{positions * TURNS_PER_SLOT:>11.0f}"
    )

print("\nWorst case if every stop fills at once = the aggregate column.")
print("Trades/yr is the evidence rate: it tracks position COUNT, not position size.")
