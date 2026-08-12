# How a decision actually gets made

Written 12 August 2026, read out of the code rather than from memory. Swing is
the only deployed strategy, so every scenario below is swing.

Two things are true throughout and worth stating once:

* **Nothing reaches the broker except through sign-off.** Both `submit_order`
  and `submit_exit_order` only ever create an order with status
  `pending_signoff`. `sign_off()` is the single path to the broker.
* **Every refusal is written down.** Entries go to `decision_journal.csv`, risk
  evaluations to `risk_decisions.csv`. A rail that refuses silently would be a
  defect.

Current settings, for reference:

| Setting | Value |
|---|---|
| Per-trade risk | 1% of equity |
| Aggregate risk-at-stop cap | 5% |
| Max concurrent positions | 10 |
| Max entries per week | 10 |
| Single-name cap | 15% |
| Correlated-cluster cap | 30% |
| Gap-risk budget | 5%, against a 6% assumed overnight gap |
| Cost-to-risk limit | 10% |
| Minimum hold | 10 trading days, escapable at 0.5R down |
| Time stop | 30 trading days |
| ATR stop multiple | 2.5 |
| Swing reward:risk | 2.0 |

---

## Scenario 1: opening a new position

This is the long path. Everything else is shorter.

### Does swing get to speak at all

| Step | Rail | What it checks |
|---|---|---|
| 1 | Regime eligibility | The regime engine publishes a probability distribution, not a label. Swing's suitable regimes are Sideways, Bull, Low-Vol and Recovery. Their combined probability must be at least 0.5, or swing emits nothing. |
| 2 | Session gate | Outside market hours the strategy engine stops emitting. Ticks still accumulate so the buffer is warm at the open. |
| 3 | Staleness | A symbol whose last print is too old is dropped from signal generation. The rest of the watchlist keeps trading. |

### Swing's own thesis

Not a rail. This is the strategy deciding it wants the trade.

Three conditions, all on the daily bars:

1. Fast EMA above slow EMA. An uptrend exists.
2. Previous close at or below the fast EMA. It pulled back.
3. Latest close above the fast EMA. It reclaimed.

If all three hold, swing proposes a buy with `stop = close - 2.5 x ATR` and
`target = close + 2 x risk`.

### Cheap local checks

These cost nothing and run first so repeat ticks never touch the broker. A
strategy re-emits its signal on every tick for as long as its condition holds,
so this has to be idempotent.

| Rail | Refuses when |
|---|---|
| Pending sign-off | Something for this symbol is already awaiting sign-off |
| History | Fewer bars than the sizer needs |
| No pyramiding | The position is already held |
| Live order | A buy for this symbol is already out but not yet filled |
| Turnover budget | 10 entries already taken in the last seven days |
| ATR | ATR is zero or unavailable, so no stop can be sized |

### Reading the account

The broker is asked for the account. If that call fails the signal is **refused
and recorded**, not dropped. A rail that throws is invisible; a rail that refuses
is auditable.

### OMS-level gates

| Rail | Refuses when |
|---|---|
| Symbol allow list | Symbol is not permitted at all |
| Entry allow list | Symbol may be held but not newly entered |
| Position anomaly | The symbol is quarantined (see Scenario 7) |
| Kill switch | The kill switch is tripped |

### The risk engine, in order

Order matters here, because each step can shrink the share count the next step
sees.

1. **Kill switch** again.
2. **Sizing.** Kelly-bounded, from swing's own realised edge. Until swing has 20
   closed trades it sizes on the documented defaults of 0.55 win rate and 1.5
   win/loss ratio. Zero shares means no edge or no ATR, and the order is
   refused.
3. **Stop source.** Swing proposed a stop, so that one is used. If a strategy
   proposes none, the ATR stop is used instead. Either way the position reaches
   the broker with a bracket rather than naked.
4. **Per-trade risk cap.** Shares times stop distance must not exceed 1% of
   equity. If it does, the order is *resized down*, not refused.
5. **Regime scalar** and **earnings scalar** both multiply the size. An earnings
   print within five trading days sizes the trade at 50%.
6. **No leverage.** A buy can never cost more than available cash less the
   reserve. Resized if it would, refused if it affords less than one share.
7. **Portfolio governor.** Six caps. The first two refuse; the next four trim,
   and the final size is the smallest of them.

   | Cap | Refuses or trims |
   |---|---|
   | Position count (10) | Refuses |
   | Aggregate risk-at-stop (5%) | Refuses when headroom is gone |
   | Single name (15%) | Trims |
   | Sector | Trims |
   | Correlated cluster (30%) | Trims |
   | Gap risk (5% budget, 6% gap) | Trims, refuses under one share |

8. **Portfolio VaR and expected shortfall.** VaR 95 and 99, ES 97.5, single-name
   and sector percentages.
9. **Cost rail, last.** It runs last on purpose, because the cash cap and the
   governor both shrink orders and a trade worth its fees at full size may not be
   at a third of it. Round-trip cost must be under 10% of the dollars at risk.
   Measured against risk rather than notional.

### Turning it into an order

| Rail | Refuses when |
|---|---|
| Whole shares | Floored, never rounded up. Under one whole share is refused, because a fractional quantity cannot carry a protective bracket |
| Per-order notional cap | Order value above the cap |

The order now exists as `pending_signoff`.

### The autonomy gate

Only reached because execution mode is `auto`. In `recommend` mode everything
stops here and waits for a human.

| Rail | Blocks when |
|---|---|
| Execution mode | Mode is `recommend` |
| Live permission | Live account without the explicit autonomous-live flag |
| Kill switch | Tripped |
| Order state | Not `pending_signoff`, or quantity not positive |
| Market hours | Market is closed. **A resting protective order skips this** and is allowed, because a GTC stop rests fine out of hours and that is the window it is most needed |
| Session phase | Phase is not eligible unattended. Opening Volatility is not eligible |
| Strategy attribution | The order carries no strategy |
| Promotion list | Strategy is not on the autonomous list |
| Evidence bar | Strategy no longer meets the promotion bar. **Currently inert on paper.** It is enforced automatically on any live account |
| Day P&L pause | Day P&L at or below -4% |
| Price drift | Price has moved more than 3% from the price the order was sized against |
| Day P&L halving | At or below -2% the size is halved rather than blocked |

Sells skip the appetite rails entirely. Risk-reducing orders are not gated on
risk appetite.

### After the fill

The entry record gets `opened_at`, price, stop, target and strategy. The ledger
opens a lot. The bracket rests at the broker.

---

## Scenario 2: an entry refused because the book is full

This is the live state right now, so it is worth showing on its own.

Ten of ten positions are held and aggregate risk-at-stop is 5.01% against the
5.00% cap. Two governor rails refuse, and either one alone would be enough.

Overnight on 5-6 August this refused 503 orders: 479 on the position limit and 24
on the aggregate cap. The two rails are co-binding by construction, because
measured per-position risk averages 0.49% of equity and ten positions fill a 5%
budget almost exactly. Raising one alone changes nothing.

The refusal is journaled with its reason. Nothing is lost, and the signal is
reconsidered on the next tick.

---

## Scenario 3: swing decides to exit

Swing asks a held position a different question from an empty one. Not "is this a
good entry" but "does the reason I am holding still hold".

1. Fast EMA falls to or below slow EMA. Swing emits a sell with
   `exit_reason: trend_broken`. It checks this on the bare crossover with no
   buffer, because a marginally early exit costs some upside and a marginally
   late one keeps a broken position.
2. **Minimum hold rail.** If the position is younger than 10 trading days it is
   held back, unless it is already 0.5R down. The escape is what makes the rail
   defensible: without it, a minimum hold would sit through a broken thesis to
   save $12 of commission.
3. The exit is sized to **exactly what is held**, read from the broker. The entry
   sizer is not involved.
4. The autonomy gate passes it as risk-reducing.
5. The closed trade records `exit_reason: signal`.

Only signal-driven exits reach the minimum-hold rail. The resting broker stop,
the de-lever sweep and the kill switch all take other paths, so no protective
exit can ever be delayed by it.

---

## Scenario 4: the stop fires at the broker

No rail is involved, and that is deliberate.

The bracket's stop executes with the app uninvolved, possibly while it is not
even running. On the next fill scan `absorb_broker_fills` finds it and records
the closed trade with `exit_reason: stop`. R-multiple is computed from the lot's
entry and stop.

This is the path that closed both CVS and MNST.

---

## Scenario 5: the time stop

A position held 30 trading days without resolving is exited with
`exit_reason: time_stop`. It is sized to what is held. No appetite rail applies.

---

## Scenario 6: protection is missing and gets re-armed

1. At startup, and every 300 seconds after, the app compares held positions
   against resting stops at the broker.
2. A position with no resting stop gets one proposed, at the level from **its
   entry record**. That is the level the risk budget was actually spent on, so
   re-arming anywhere else would protect the position at a distance nobody
   approved.
3. A position whose entry record has no stop is left alone and logged. A
   fabricated stop is worse than a visible gap.
4. The autonomy gate lets it through even with the market shut, because it rests
   GTC.
5. A quarantined symbol is refused. Its recorded stop predates whatever
   quarantined it.

---

## Scenario 7: something outside the app changed a position

1. Reconciliation compares tracked quantity against the broker's.
2. An undeclared difference trips the kill switch and halts the session.
3. A declared anomaly is treated as explained instead, but only for the exact
   broker quantity it was declared at. A difference declared at 16-to-64 does not
   explain a later 64-to-128.
4. While quarantined: new entries refused, de-lever trims refused, **exits
   allowed** and re-sized from the broker rather than from the tracked quantity.
   Selling 16 of 64 would leave three quarters of a position nobody meant to
   keep.
5. Re-arming protection is refused, because the recorded stop is stale.
6. The records are **not** repaired by this. That is still manual.

---

## Scenario 8: a split is announced on a held position (M39, proposed)

Designed, not built. Spec at
`docs/superpowers/specs/2026-08-12-corporate-actions-design.md`.

Forward and reverse splits only. Other corporate actions are logged, not acted
on.

### Detection

The monitor queries announcements one symbol at a time and persists what it
finds, so a failed query on ex-date morning does not mean acting blind.

| Gate | Purpose |
|---|---|
| `ex_date` after the position was opened | CRWD split 4-for-1 on 2 July and we bought on 31 July, correctly sized. Without this gate CRWD is flagged today and wrongly adjusted |
| `ex_date` on or before the next market open | So an October split does not move a stop in August |
| Ratio between 1e-4 and 1e4, and not 1.0 | A ratio of 1 is not a split. The bound is wide because a real 1-for-1000 reverse split gives 0.001 |
| Symbol held, with a resting stop | Nothing to adjust otherwise |

### Phase 1, before the ex-date open

New stop is the current stop divided by the ratio. **Quantity and entry basis are
not touched.**

Two guards before anything is placed:

1. The new stop must sit below the current market price. Otherwise it is a market
   order wearing a stop's clothing, which is what cost $375 on MNST.
2. Relative distance may not shrink. On MNST: 20.3% before, 21.0% after, so the
   correct adjustment is admitted.

Fail either and it refuses, declares an anomaly and warns. A wrong ratio can then
leave a stop too far away. It can never liquidate on contact.

**Shadow mode is the default.** Everything runs and logs what it would place,
and `modify_order` is called zero times.

### Phase 2, only on an observed quantity change

Tracked quantity is adjusted, and the resting stop's quantity is raised to cover
the whole holding. The ledger basis correction is computed and logged but **not
applied**, because that path has never been observed running.

### While an action is pending

New entries on that symbol are refused. The size basis is about to change, so
sizing against it would use a number with a known expiry.

---

## What can never be blocked

Worth stating plainly, because several of these were defects once:

* An exit. A rail whose effect is "the account may not de-risk" is a broken rail.
* A protective order resting outside market hours.
* A stop already resting at the broker.
* The kill switch.

## Where the freeze sits

Nothing lands that changes which trades happen or how large they are. Every
number in the settings table above is frozen. Recording more about decisions
already being made is explicitly allowed, and a defect that corrupts the record
is fixed immediately.
