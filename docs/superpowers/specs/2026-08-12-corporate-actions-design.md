# M39 corporate actions: detection and adjustment — 12 August 2026

Design for the remaining half of ROADMAP Group 1. M60 built the containment —
reconciliation can be told a difference is explained, and a position can be put
in a state the ordinary path must not act on. **What remains is the DETECTION
and the ADJUSTMENT**, and both were waiting on a measurement that has now been
taken, at a cost.

## Why this is not the design the ROADMAP describes

The original M39 entry predicts the failure as *"the broker's share count
doubles, reconciliation compares tracked 16 against broker 32 and trips the
kill-switch"*. **The MNST split on 11 August measured something different, and
the difference decides the whole design.**

Alpaca halved the PRICE to ~$46 and **never delivered the shares.** Quantity
went 8 → 0, never 8 → 16. `avg_entry_price` stayed stale at $91.1838. Order
`34ffd4cd` was not cancelled, not re-priced, not re-quantified — it sat at
$72.68 while the market was $46, and it fired at the open in three partials
(1 @ 46.34, 3 @ 46.16, 4 @ 45.79) for a real net loss of **−$375.23, −51.4% on
a position that should have been roughly flat.**

Three consequences, each of which contradicts the original brief:

1. **A quantity-triggered detector would never have fired.** The quantity never
   changed in the direction the brief anticipates. Detection must be
   **announcement-driven and proactive**, before the ex-date open.
2. **A split can arrive in halves** — price first, shares later or never. The
   window between the two is exactly where an unadjusted stop is lethal.
3. **Account activities are useless for detection.** `SPLIT: 0`, `CSD: 0`,
   `DIV: 0` through a real split. The announcements endpoint is the only source.

**Caveat, load-bearing:** this is a PAPER account, and Alpaca paper's
corporate-action handling may be incomplete in ways a live account is not.
Whether live Alpaca would have delivered the shares is unknown and must not be
assumed either way. This design is built for **the behaviour measured, not the
behaviour preferred.**

## Scope — splits only

Forward and reverse splits are detected **and adjusted**, because the ratio is a
single unambiguous number and SFBS 2-for-1 on 21 August is the next candidate
event. Spin-offs, mergers, ticker changes and dividends are out of scope for
adjustment: their maths is not one ratio, and this account has **zero
observations** of any of them. Where such an announcement is seen it is logged,
not acted on.

## Requirements the operator set, which shape the architecture

**R1 — the state cannot be lost when moving across screens.** This project has
found the same defect five times: `shows_advanced()` had no consumers from M45
until M63, `theme.callout` none until M72, `is_synthetic` reached the language
model but never the operator until M72, `refusals.rail_of` reached the reporter
but never the Blotter until M77, the M37 diagnostics reached nothing until M79.
A corporate-action state living on one screen would be that defect with a new
name. **One source of truth, many readers, and a test that asserts each reader.**

**R2 — it must be a decision input, not a display.** The state must be a domain
concept the autonomous path queries and the decision journal records, with
presentation as one consumer among several. This is why it cannot live in the
presentation layer, and why it gets its own module rather than a method on an
existing class.

## Architecture

A new subsystem rather than an extension of `SignalToOrderBridge`. The bridge
already holds both halves and already owns `rearm_protective_stops`, which makes
it the tempting home — but it is ~1,100 lines already carrying churn control,
entry records, sizing, lot restoration, re-arming and the protection sweep, and
R1 and R2 both want a clean queryable interface rather than another method on an
overloaded class.

```
src/qat/domain/corporate_actions/
  announcements.py   Announcement, AnnouncementStore
  detector.py        SplitDetector, PendingAction
  adjuster.py        StopAdjuster            <- the invariant lives here
  monitor.py         CorporateActionMonitor  <- engine, and the public face
```

`CorporateActionMonitor` is registered as an orchestrator engine alongside the
others. `SignalToOrderBridge` changes by one call: it asks the monitor whether a
symbol has a pending action before re-arming protection.

**M60 is used as designed, not inverted.** A candidate approach was to have the
detector declare an anomaly and let `rearm_protective_stops` do the adjusting.
That was rejected: quarantine means *"the ordinary path must not act on this
symbol"*, and re-arm is explicitly one of the things it blocks. Making re-arm
the adjuster would break the guarantee M60 exists to give.

### Data model

```python
@dataclass(frozen=True, slots=True)
class Announcement:
    symbol: str
    ex_date: date
    ratio: float          # new_rate / old_rate. 2.0 for a 2-for-1.
    action_id: str        # Alpaca's stable corporate_action_id
    payable_date: date | None
    fetched_at: datetime
```

**Deduped on `(symbol, ex_date)`, not on `action_id`.** Alpaca returned the same
announcement more than once and the COUNT changed — one record on the Saturday,
two byte-identical ones on the Monday. A detector reading a changing count as a
changing action would act twice.

```python
@dataclass(frozen=True, slots=True)
class PendingAction:
    announcement: Announcement
    position_opened_at: datetime
    current_stop: float | None
    adjusted_stop: float | None
    state: str            # "pending" | "shadowed" | "applied" | "refused"
    refusal: str | None
```

The broker adapter protocol gains `announcements(symbol, since, until)`, with
Alpaca and Mock implementations. **No announcements code exists in `src/` today**
— it lives only in probe scripts, so this is genuinely new surface.

The store is **persisted**. A query that fails on ex-date morning must not mean
acting blind on the one day it matters.

## Detection gating

Four gates. Each exists because of something specific.

| Gate | Why |
|---|---|
| `ex_date > position.opened_at` | **The CRWD gate.** CRWD split 4-for-1 with ex-date 2 July; we hold 16 bought on 31 July, correctly sized post-split, and the resting OCO is right. Without this gate CRWD is flagged today and adjusted wrongly. **The false positive is in the book, not in a thought experiment.** |
| `ex_date <= next trading session` | So a split announced for October does not re-price a stop in August. Uses the existing market calendar. |
| `1e-4 < ratio < 1e4` and `ratio != 1.0` | A ratio of 1 is not a split. The bound is wide on purpose: the ROADMAP records `old_rate=1000.0, new_rate=1.0` as a real observed shape, giving ratio **0.001**, so a tighter bound would refuse a genuine 1-for-1000 reverse split. A ratio outside the bound is **refused and warned**, never silently dropped. |
| Symbol is held and carries a resting stop | Nothing to adjust otherwise. |

**Keyed on `ex_date` throughout, never `payable_date`.** CRWD's are 1 and 2
July — the payable date precedes the ex-date, so keying on it would act a day
early or not at all.

Per-symbol queries, never a market-wide scan: `target_symbol` is absent on
roughly 10% of records (32 of 291 reverse and 8 of 63 forward splits in an
88-day sample), so a scan cannot be trusted to attribute an announcement to a
symbol.

The monitor runs at engine start and then on its own periodic sweep, reusing
`settings.protection_sweep_seconds` (default 300) rather than introducing a
second cadence to keep in step.

"Next trading session" means
`market_calendar.next_open(market)` — the existing function, checked rather than
assumed; there is no `next_session_date`, and `next_open` already returns a
timezone-aware datetime of the next regular open, skipping weekends and
holidays. Its date component is what the gate compares against.

Evaluated **in the market's timezone, not the operator's.** The operator is in
AEST and the US open lands at 23:30 local, so a naive "today" would be a day out
for half of every session. `next_open` already resolves in market time, which is
why it is the right function to lean on. It returns `None` if no trading day
turns up within its search window; that reads as "cannot determine the session",
and the adjuster refuses rather than guessing.

So the adjustment evaluates when `ex_date <= next_open(market).date()`.

## Phase 1 — announcement-driven: re-price the stop, and nothing else

`new_stop = current_stop / ratio`.

**Quantity and entry basis are not touched.** The stop is the only thing that
loses money by being stale.

This is the design's most important restraint. Had the basis been halved to
$45.59 on the announcement, MNST's recorded P&L would have shown roughly flat —
and **the loss was real.** The account genuinely paid $91.18 for 8 shares and
sold 8 at ~$46; verified against `/v2/account/activities` with no SPLIT, no CSD
and no share delivery of any kind, and equity moving 101,754.81 → 101,387.14
consistently. Adjusting the basis proactively would have manufactured exactly
the "split artefact, not a loss" claim that two earlier documents asserted and
got wrong.

**The basis and the quantity move together, or not at all**, and only on
observation.

### The never-tighten invariant

Two hard guards before anything is placed:

1. **The new stop must sit below the current market price.** Otherwise it is a
   market order wearing a stop's clothing — the MNST failure exactly.
2. **Relative distance may not shrink.** Stated without ambiguity, because "the
   original distance" could mean two things:

   ```
   before = (pre_action_price  - current_stop) / pre_action_price
   after  = (post_action_price - new_stop)     / post_action_price
   require: after >= before - tolerance
   ```

   `pre_action_price` is the last price observed before the action was applied;
   `post_action_price` is the current one. On MNST this passes and it is worth
   checking against the real numbers: before = (91.18 − 72.68)/91.18 = **20.3%**,
   after = (46 − 36.34)/46 = **21.0%**. The invariant admits the correct
   adjustment and would have prevented the loss.

Failing either, the adjuster **refuses, declares an anomaly, and warns loudly**
rather than placing anything. The asymmetry is deliberate: a wrong ratio can
then leave a stop too FAR away, which costs more if the position runs against
us, but it can never liquidate on contact. One failure is a worse loss; the
other is a guaranteed one.

## Phase 2 — observation-driven, and deliberately incomplete

Triggered only when the broker's quantity actually changes AND an announcement
explains the ratio. Then:

* tracked quantity is adjusted;
* the resting stop's **quantity** is raised to cover the whole holding — 8
  shares of protection against 16 held leaves half the position naked;
* the ledger basis correction is **computed and logged, and NOT applied.**

**Phase 2 has zero observations.** MNST never reached the share adjustment; the
stop closed the position first. So the record rewrite stays manual, as the CVS
and MNST corrections were, until there is one observed event to build against.
That is slower than ideal and it is the right trade: the piece that can be wrong
in the dangerous direction is the piece that waits for evidence.

Phase 2 declares through M60's existing store, so the quarantine gives a partial
adjustment somewhere safe to fail. **The four-way atomicity risk is real** —
tracked quantity, entry record, resting protection, ledger basis — and correcting
the quantity but not the stop is worse than correcting neither.

## Shadow mode, and how it is promoted

`QAT_CORPORATE_ACTION_MODE`, one of `shadow` (default) or `act`.

In `shadow`, everything runs — the query, the store, the gating, the ratio, the
invariant — and the adjuster logs precisely what it WOULD place, calling
`modify_order` zero times. It costs no risk budget, needs no free position slot,
and exercises the real path against real announcement data including the CRWD
false positive already in the book.

Promotion to `act` is a deliberate config change. **The default means the first
deployment of this changes nothing at all**, which is also what keeps it clearly
inside the freeze on arrival.

This is the M37 pattern: record first, act later.

## R1 — the visibility contract

One source of truth: `CorporateActionMonitor.pending_action(symbol)` and
`.pending_actions()`.

Required readers, each with its own test:

| Reader | What it shows |
|---|---|
| Dashboard | A banner when any held position has a pending action |
| Risk Console | Symbol, ex-date, ratio, current stop, adjusted stop, mode |
| Order Blotter | The adjustment as an order event carrying its reason |
| Workbench, Screener | A caveat on the symbol, so a proposal is not read as clean |
| AI Advisor context | Included, per R2 — the model must not reason about a position whose share count is about to change |
| Daily report | Its own section |
| Decision journal | Every entry or exit decision on the symbol records the pending action |

**Enforcement takes two tests, not one.** The first draft of this spec said
M80's existing `test_computed_values_have_readers` could be extended to cover
this. Read rather than assumed, it cannot: that test walks `@property`
definitions in three watched modules and asserts something *anywhere in `src/`*
reads each one. "Read by something" is a much weaker claim than "read by the
Blotter", and R1 is the stronger claim.

So:

1. **The generic guard** gains `domain/corporate_actions/detector.py` in its
   `_WATCHED` tuple, so any computed property added there is covered by the
   existing rule.
2. **A new explicit test** asserts that each module in the R1 table above
   references the monitor's API. That one fails if a screen is added later
   without wiring the state in, which the generic guard would not catch.

The distinction matters because the five-times-repeated defect was never "no
reader at all". `is_synthetic` had a reader from M40 — the language model. What
it lacked was the *operator*, for two milestones. A guard that accepts any
reader would have passed it.

## R2 — decision input

A symbol with a pending action inside the window is **refused for new entries**,
with the reason written to `risk_decisions.csv`. The size basis is about to
change; entering against it would size on a number with a known expiry.

The monitor's output becomes a field on the decision context, so autonomous
sizing reads it directly rather than inferring it. This is the hook the
longer-term intent needs: the state is available to the decision path from the
first version, even while only some consumers use it.

## Position under the freeze

**No lift is required.** Stated explicitly so it is not re-argued:

* **Phase 1 is fix-immediately.** The standing rule lists *"protective orders
  not resting, or not being repaired."* A sell-stop at $72.68 against a $46
  market is not protecting a position — it is a liquidation order, and repairing
  it is the named category.
* **Refusing new entries on a pending action refuses strictly more**, which is
  the exact argument M60 was accepted under: *"the application halts less only
  where a human has explicitly said why, and otherwise refuses strictly more
  than before."*
* **No strategy parameter, sizing rule, cap, threshold or weight changes.**
* **Shadow is the default**, so the first deployment is a no-op by construction.

What WOULD need a recorded lift, and is therefore not in this design: anything
touching entry sizing, and any automatic rewrite of the ledger.

## Testing

Both real events as regressions, with their actual numbers:

* **CRWD must NOT flag.** 4-for-1, ex-date 2 July, bought 31 July, 16 held.
* **MNST must flag and compute 36.34.** 2-for-1, ex-date 11 August, bought
  10 August, stop 72.68, price halving to ~46 — and place it before the open.

Then:

* an inverted ratio (0.5 supplied for a forward split) → computed stop above
  price → refused, anomaly declared, warned;
* **a 1-for-1000 reverse split (ratio 0.001) is accepted, not refused** — the
  case the first draft's `0.01` lower bound would have thrown away, using the
  `old_rate=1000.0, new_rate=1.0` shape the ROADMAP records as real;
* `next_open` returning `None` → the adjuster refuses rather than guessing at a
  session date;
* the same announcement returned twice with a changed count → one pending
  action;
* the announcements query raising → served from the persisted store;
* `payable_date` before `ex_date` → keys on `ex_date`;
* `shadow` mode → `modify_order` called zero times, assertion on the mock;
* a reader test for every row of the R1 table.

**Every test that builds an OMS passes its own `data_dir`** — `conftest` sets
`QAT_DATA_DIR` session-wide and the anomaly store persists there, so one
declared anomaly would leak a quarantine into every later test.

## What this deliberately does not do

* No spin-off, merger, ticker-change or dividend adjustment.
* No automatic ledger basis rewrite (Phase 2 logs it instead).
* No quantity adjustment from an announcement — only from observation.
* No change to which trades the strategy chooses or how it sizes them.

## The measurement still outstanding

**What happens when a position SURVIVES to the share adjustment.** MNST never
reached it. SFBS 2-for-1 on 21 August is the next candidate, but **SFBS cannot
currently be bought** — both rails bind, with 10 of 10 position slots filled and
aggregate risk-at-stop at 5.01% against a 5.00% cap, so every entry is refused.
The 31 July positions clear their ten-day minimum hold around 14 August, which
may free a slot in time; it is not guaranteed.

Shadow mode is what makes that uncertainty tolerable — the machinery accumulates
evidence about its own judgement without needing the event.
