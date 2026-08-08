# M66 — aggregate risk-at-stop on current prices, 8 August 2026

## The defect

`PortfolioGovernor.snapshot` computes each position's risk as
`price = prices.get(pos.symbol) or pos.avg_price`, and `avg_price` maps to the
broker's `avg_entry_price`. The `prices` argument is threaded through
`snapshot`, `evaluate` and `delever_fraction` — and **nothing in the trading
path ever passes it.** `RiskEngine` calls `governor.evaluate(...)` without it;
`DeleverSweep` calls `governor.snapshot(...)` without it. The only caller that
supplies prices is `adopted.py`, a display path.

So every entry decision and every de-lever check this system has made was
measured against the prices its positions were **opened** at.

Measured on the live book:

```
basis                                 risk $     pct
current price (what is at risk NOW)  5,947.28   5.87%
avg entry price (the fallback)       5,078.77   5.02%   <- matches the app exactly
```

**The direction is what matters.** Risk per share is `price − stop`, so a
position that has gained has further to fall. **A winning book understates its
risk** and believes it has headroom it does not have; a losing book overstates
it and refuses trades it could take. The bias is backwards from prudent and
grows with profit. The book is presently at 5.87% against a 5.00% cap while
reporting 5.02% — already 17% over in reality, marginally over on paper.

Same shape as `shows_advanced()` before M63: a parameter plumbed through every
layer and supplied by nothing. The habit is to ask what *reads* a thing; here it
was what **writes** it.

## The finding that simplifies the fix

**Alpaca's `Position.current_price` is the consolidated tape.** Measured against
both feeds for all ten held positions:

```
matches SIP: 10   matches IEX: 0   neither: 0
```

So the price this fix needs is already inside every `positions()` response the
application makes, is free on this account's tier, and **carries none of the IEX
range bias** documented in `MARKET_DATA_FINDINGS.md`.

**This corrects an earlier claim.** Both ROADMAP M66 and the 8 August handoff
said the fix was coupled to the market-data decision and should wait for it.
That was wrong: the broker's own mark is consolidated regardless of which feed
the application subscribes to for its own bars and ticks.

## The change

Three edits, and **no caller changes**.

**1. `Position` gains an optional mark** (`data/broker/adapter.py`):

```python
@dataclass(slots=True)
class Position:
    symbol: str
    quantity: float
    avg_price: float
    current_price: float | None = None
```

Optional and defaulted, so `MockBroker`, the unimplemented IBKR seam and every
existing test keep working untouched. `None` means "this adapter does not report
a mark", which is a different claim from "the mark is zero".

**2. The Alpaca adapter populates it** from the field already present in the
response it parses.

**3. `PortfolioGovernor.snapshot` gains one fallback tier:**

```python
price = prices.get(pos.symbol) or pos.current_price or pos.avg_price
```

The governor already receives `positions`, so `RiskEngine`, `DeleverSweep` and
`adopted.py` all begin measuring correctly at once — with no price map threaded
through four call sites, no additional broker request, and the explicit `prices`
argument preserved as an override.

### The alternative, and why it is rejected

Threading a price map from the application's own market-data buffer would mean a
new argument at four call sites, an **empty map at startup** — exactly when the
first entries of a session are considered — and IEX prices carrying a ~4% range
bias into the risk cap. The broker's mark has none of those problems.

## What it changes in practice

The reported figure moves **5.02% → 5.87%** against a 5.00% cap. Because a
gained position has further to fall to its stop, the cap becomes **stricter on a
winning book**, which is the conservative direction.

**Nothing is forced to sell.** `QAT_DELEVER_SWEEP_ENABLED=false` is set
explicitly in the live configuration, so the sweep only logs. This was checked
rather than assumed: with the sweep *enabled*, a figure jumping from 5.02% to
5.87% would have triggered a proportional trim of all ten positions the moment
it deployed.

Entries are already refused at 5.02%, so the immediate behavioural change is
nil.

## Position under the validation freeze

**It changes which trades are permitted, so it needs a deliberate, recorded
lift** — like M56c, M57 and M58b.

* **For:** the cap has never measured what it claims to. Every figure it has
  produced was computed against stale prices, and the error grows with profit.
* **Against:** it moves a number the two-week baseline was measured on.

**Not to be deployed before Tuesday** regardless, so that nothing about sizing
changes between now and the MNST split measurement.

## Error handling

`current_price` absent means fall through to `avg_price` — today's behaviour,
unchanged. A broker that reports no mark is not treated as reporting a zero,
which would make every position read as risk-free.

No new request is made, so there is no new failure mode: if `positions()` fails
the caller already handles it.

## Testing

* A position carrying a mark is measured on it.
* A position without one falls back to `avg_price` — **the old behaviour, pinned
  so the change cannot silently alter adapters that report no mark.**
* An explicit `prices` argument still wins, so `adopted.py` is unaffected.
* **The real book, reproduced:** the ten live positions with their actual marks
  and stops produce 5.87%, and the same positions without marks produce 5.02%.
  This pins both the defect and the fix to measured numbers rather than invented
  ones — and it is the test that would have caught this in the first place.
* A gained position raises measured risk; a lost one lowers it.
* The Alpaca adapter maps the field, asserted against a fake response, so the
  mapping cannot silently stop populating it.
