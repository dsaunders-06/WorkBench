# Development stack after M27

## Standing rule during the data-collection phase

**Nothing lands that changes a trading decision.** The phase exists to find out
whether the machinery runs end to end and produces a reviewable record. A change
that alters which trades are taken contaminates the only measurement being made.

The install stays on **M26** for the duration. M27 is committed but not deployed:
it adds a rail that refuses trades, which works against a phase whose purpose is
accumulating them - and it would refuse them on cost assumptions that cannot yet
be audited, because the metrics are still gross.

### Blocking - fix immediately

Anything that stops data existing:

* the feed dying, or symbols silently dropped
* the app crashing, hanging, or failing to survive a session
* `decision_journal.csv` or `risk_decisions.csv` not being written (still
  unproven - no signal has ever reached them)
* reconciliation false-tripping the kill-switch and halting a session
* orders rejected by a bug rather than by a rule
* the daily report failing at the close

### Deferred - however tempting

Anything that changes decisions: cost-rail calibration, concentration limits,
exit rules, holding periods, promotion settings, strategy parameters.

The test: *would this change which trades happen?* If yes, it waits.

### Morning check

1. `Trading session started - US is open` at 13:30 UTC, then ticks
2. Any `MARKET DATA DOWN`
3. Whether the journal and audit CSVs exist yet
4. Counts: signals generated, orders proposed, orders filled
5. The daily report's Metrics block

Looking for *does the pipeline move*, not *did it make money*. At these sample
sizes P&L is noise.

## The stack

Ordered on one principle: **make the measurement honest before making the
strategy better.** Everything downstream inherits a measurement error.

### M28a - The staleness rail (promoted ahead of the cost work)

Not a tuning problem. **The rail has never once fired correctly** - every trip it
has produced has been a false positive, and it was only ever masked by the feed
being broken in other ways:

| Trip | Symbol | Reported age | Reality |
|---|---|---|---|
| 27 Jul | (feed dead) | - | never fired; per-symbol staleness skips symbols that have not ticked |
| 28 Jul 13:30 | BRK.B | 63,017s | thin on IEX, last print was the previous close |
| 28 Jul 13:35 | HON | 97s | liquid; the poll interval itself |

The defect is one line:

```python
self._last_seen[tick.symbol] = tick.ts        # the TRADE's timestamp
self._last_tick_at = datetime.now(UTC)        # the RECEIVE time (M26, correct)
```

The rail reads `_last_seen`, so it measures **how old the last trade was**, not
**whether the feed is delivering**. With `market data poll = 60s` and
`data_staleness_seconds = 60`, a trade that occurred 40s before a poll arrives
already 40s old and the next poll is 60s later, so the measured age routinely
lands between 60 and 120 seconds through entirely normal operation. On any
symbol. A trip was not a risk, it was arithmetic.

**Currently suppressed** by `QAT_DATA_STALENESS_SECONDS=250000` in the operator
`.env` - ~69 hours, sized to clear a weekend gap (Monday's open is 65 hours
after Friday's close). This effectively disables the rail. Acceptable on paper
because M26's feed-health check covers genuine feed death using receive time;
**not acceptable before live money**, because it leaves a partial outage
undetected - the feed continuing to deliver some symbols while silently
stopping on others.

The redesign separates two ideas the current code conflates:

* **feed liveness** - measured on receive time - *may* halt trading
* **quote freshness** - measured on the trade timestamp - excludes that ONE
  symbol from signal generation, and never halts the account

A stale quote on one thin ticker should stop trading that ticker. Halting the
whole account because Berkshire had not printed on IEX by 09:30:15 is a rail
doing considerably more damage than the hazard it guards against.

### M28 - Cost-truthful measurement

Fees on `ClosedTrade`, gross and net both retained; cost drag in the Metrics tab
and reports. Expectancy, average R, profit factor and the promotion gate all
become net. Everything else waits on this, because every judgement about the
strategy reads these numbers.

### M29 - Governance consistency

Turn on `enforce_promotion_evidence`. Today the policy says "earn autonomy" and
the code grants it anyway.

**Sequencing note.** An external review recommended enabling this immediately.
Doing so during the paper phase would halt data collection - swing has zero
closed trades against a 30-trade bar, so nothing would trade unattended. Correct
before live money, self-defeating during a paper test. And it must follow M28:
the gate reads expectancy and average R, which are gross today, so enforcing it
first would gate on numbers already known to be wrong.

### M30 - Gap risk as its own concept

Every risk figure currently means *"if the stop fills."* The 5% aggregate cap is
really "5% if every stop fills as intended". A 1%-risk trade with a 5% stop is
**20% of equity in notional**; a 30% gap through the stop costs **6% of the
account**, six times the budgeted loss, from one name.

* separate stop risk from gap risk in the governor
* measure overnight gap exposure
* single-name concentration 25% -> 10-15%, sector 40% -> 30%

Matters more on ASX, where halts pending price-sensitive announcements are
routine for small and mid caps and a two-week hold spans them by design.

### M31 - Churn control

The pieces deferred from M27: minimum holding period for signal-driven exits
(10 trading days, configurable, never delaying a protective exit), a turnover
budget on `trades_per_week`, and a time stop.

Open tension to decide explicitly: a minimum hold blocks a *signal-deterioration*
exit, which is not protective. Sitting through a broken thesis to save $13 of
commission is the wrong trade above some loss threshold.

### M32 - ASX readiness

**The blocker nobody flagged: there is no ASX market data source.** Alpaca is US
equities only, and the entire live data path hardened through M17/M25/M26 serves
US symbols. Needs a feed decision (yfinance, delayed and unofficial, vs IBKR's
own), currency handling, and the IBKR live path actually exercised.

Also: slippage is modelled at a flat 5bps, optimistic for ASX small and mid caps
where a $20,000 position can be a meaningful share of daily volume.

### M33 - Validation using what already exists

`monte_carlo.py` and `walk_forward.py` have been built since M4 and never run in
anger. Run them on swing. Promote correlation from a Risk Console display to an
actual portfolio limit - sector is currently a proxy for correlation, and in a
crisis it is a poor one.

## Already built, despite appearing on review wishlists

Monte Carlo; walk-forward (on the Workbench since M19); regime probabilities and
an exposure scalar the risk engine applies; volatility-targeted sizing (the 1% is
a ceiling, not a constant); EMA rather than simple moving averages; a correlation
table.
