# Evaluation baseline — what is measured, what is used, what is missing

**Drafted 6 August 2026, against build M56.** The first step of M51: before
deciding what to evaluate, establish what the system already knows about itself.

Everything here is traced from the source, not recalled. Where a field is
described as unread, it means a search of `src/` found no consumer outside the
module that writes it.

---

## 1. What actually changes a decision

Four things. That is the whole list.

| Measurement | Computed by | What it changes |
|---|---|---|
| `win_rate`, `average_win`, `average_loss` | `compute_stats` | **Position size.** `EdgeEstimator` turns these into the Kelly inputs once `edge_min_trades` (20) closed trades exist. Below that the shipped defaults 0.55 / 1.5 are used |
| `trade_count`, `average_r`, `win_rate`, `worst_trade`, `average_win` | `compute_stats` | **Promotion.** `StrategyScorecard` gates unattended trading on these. Advisory unless `enforce_promotion_evidence` is set |
| Resting stops at the broker | `resting_stops()` | **Every new order.** A position with no known stop counts its full value against the 5% aggregate cap |
| Blocked-decision reasons | `summarise_blocked_reasons` | **Nothing.** Rendered into the daily report only |

The first two are the entire feedback loop from outcomes back into behaviour.
Both are driven by **`net_pnl` and `r_multiple`** and nothing else — every other
recorded field is descriptive.

**Consequence worth stating plainly.** With one closed trade, the sizing loop is
inert and will stay inert until 20 exist. Every position taken so far was sized
on two invented constants, and will be for roughly the next two months.

---

## 2. Captured and never read

Measured by searching for each field's use outside the module that writes it.

### The M37 diagnostics — the whole set

| Field | Written | Read by |
|---|---|---|
| `mae_r` | every closed trade | nothing |
| `mfe_r` | every closed trade | nothing |
| `entry_slippage` | every closed trade | nothing |
| `regime_at_entry` | every closed trade | nothing |
| `regime_probability` | every closed trade | nothing |
| `exit_reason` | every closed trade | nothing |
| `gross_r_multiple` | every closed trade | nothing |
| `holding_days` | every closed trade | nothing |
| `entry_cost` / `exit_cost` | every closed trade | nothing |

M37's own docstring says these exist so a completed trial can answer *why* a
result happened rather than only what it was. That was honest about intent, and
the intent has not been acted on. Nothing reads them, no screen shows them, no
report summarises them. They are correct, complete, and inert.

**This is not waste — it is deferred work.** The data cannot be reconstructed
afterwards, so capturing first was right. But "captured" has been mistaken for
"used" in every status summary since, including mine.

### The two largest files on disk

| File | Size | Read by |
|---|---|---|
| `risk_decisions.csv` | 626 KB | **nothing** — the audit log is read from memory by three screens; the file is never opened |
| `decision_journal.csv` | 453 KB | one function, `summarise_blocked_reasons`, for a single daily-report line |
| `equity_curve.csv` | 326 KB | drawdown and Sharpe in reports; the Dashboard chart since M56 |
| `closed_trades.csv` | 0.5 KB | everything in §1 |

The two files that record *why the system did what it did* are 1.1 MB of
evidence feeding one line of prose. The file that drives every decision holds
one trade.

---

## 3. What should be measured and is not captured

Ordered by what last night showed.

### 3.1 Why an order did NOT happen, aggregated

`risk_decisions.csv` holds every refusal with its binding rail — 504 rows
overnight, 479 of them the position limit. Nothing aggregates it. The single
most useful fact about last night's trading came from an ad-hoc query, not from
the application.

**A strategy that is never allowed to trade looks identical to one with no
setups.** The promotion gate counts what happened; nothing counts what was
prevented, so a rail that is silently strangling a strategy is invisible.

### 3.2 Which rail binds, over time

Related but distinct. Knowing the position limit bound 479 times says the book
was full. It does not say whether that limit *helped*. The counterfactual —
what the refused trades would have done — is unknowable, but the *distribution*
of binding rails over weeks is not, and a rail that binds 95% of the time is
either load-bearing or miscalibrated.

### 3.3 Slot allocation order

When the book is full, the next entry goes to whichever symbol signals first
after a slot opens. Last night MU signalled 348 times and never traded; VRTX
signalled 9 times and got the slot CVS vacated. **Tick arrival order, not
conviction.** Nothing records which candidates were competing for a slot at the
moment it opened, so this cannot currently be measured — only inferred.

### 3.4 Whether the AI advisory layer changes anything

It cannot place, size or approve an order, so its entire value is whether the
operator's decisions are better with it than without. Nothing records that an
advisory response was produced, what it said, or whether the operator acted on
it. **This is the clearest example of the M51 question**: information is
captured, presented, and its effect on effectiveness is unmeasured in either
direction.

### 3.5 Cost model accuracy

`entry_slippage` was added specifically to answer whether the assumed 5bps holds.
It is recorded and unread. One data point exists so far, and it is not
encouraging in a different way: the CVS stop gapped and cost **1.68R**, not the
1R the sizing assumes. If that is typical, every position is sized against an
understated downside.

### 3.6 Regime attribution

`regime_at_entry` and `exposure_scalar` are on every trade. Nothing groups
outcomes by regime, so "does the regime engine add value" — the question that
justifies the whole HMM — cannot be answered from the record even though the
data to answer it is being written.

---

## 4. The shape this suggests

Not a proposal, an observation about where the gaps cluster.

* **Reading is the gap, not recording.** With one exception (§3.3), everything
  needed to answer §3 is already on disk. The evaluation framework is mostly an
  analysis layer, not new instrumentation.
* **The unit of evaluation is the refusal, not the trade.** The trade ledger is
  the smallest file and the best-used one. The refusal logs are the largest and
  the least used, and they are where the behaviour actually lives at a
  ten-position cap.
* **Two questions cannot be answered by better analysis alone** — whether the AI
  changes outcomes (§3.4), and what was competing for a slot (§3.3). Those need
  new recording, and both are cheap.

---

## 5. Deliberately not decided here

What to *do* about any of it. This document establishes the baseline the
operator asked for — what is measured, what is used, what is missing — so that
the framework is designed against evidence rather than against a guess about
what is being collected.
