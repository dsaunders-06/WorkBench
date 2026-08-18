# The US validation trial — what it landed, 19 August 2026

Written on the day the US phase closed and the ASX/IBKR move was called. Every
current-state figure here was **derived from the live record on 19 August**, not
carried forward from an earlier document. Where a number disagrees with an older
paragraph, this one was measured and that one was remembered.

---

## What the trial was for

One question: **does swing possess an edge that survives costs?** The promotion
gate encodes the answer's price — `promotion_min_trades` is **30** closed
trades, per strategy.

Everything else — the rails, the ledgers, the audit trail, the screens — existed
to make that question answerable and its answer trustworthy.

## What it produced

| | |
|---|---|
| Window | 31 July 13:30 UTC → 18 August 18:32 UTC |
| Sessions with decisions | **10** |
| Risk decisions | **4,876** |
| Approved | **45** (0.92%) |
| Refused | **4,831** |
| Closed trades | **2** |
| Closed trades the gate can count | **1** — CVS, swing, **r = −1.68** |
| Equity | 100,415.94 → 101,158.57 (**+0.74%**) |
| Decision journal | 1,769 rows |

### The headline is an absence

**The trial produced no edge evidence at all.** One usable closed trade against a
gate needing thirty. The second — MNST — carries no `r_multiple` and no
strategy, because it was hand-placed at the broker and its stop fired through a
2-for-1 split.

At the observed rate, roughly one and a half closed trades a month of which one
counts, **thirty trades is about eighteen months away**. ROADMAP predicted "ten
closed trades a month". The prediction was out by a factor of six, and that gap
— not the expectancy — is the trial's most important measurement.

**Why so few:** the book filled on day one and never emptied. 4,456 of 4,831
refusals are the 10-position limit. The strategy kept finding setups; there was
never room.

### Rails that actually bound in production

| Rail | Refusals |
|---|---|
| Position limit | 4,456 |
| Cost-to-risk | 269 |
| Aggregate risk-at-stop cap | 106 |

**Three of thirteen.** Single-name, sector, correlated-cluster, gap-risk and
portfolio-ES never bound once. The minimum hold, the time stop and the churn cap
are unobservable by construction — they refuse inside the bridge and write no
audit row.

---

## What worked

**The machinery, which is what the phase was really validating.** Ten positions
carried a resting broker stop at every check across nineteen days. Zero
kill-switch trips on a non-discrepancy, zero reconciliation mismatches, zero
sessions lost to a crash or a hang. The feed dropped nothing. The ledgers were
written every session.

**The research harness (W2), which is the durable asset.** `ReplaySession` drives
historical bars through the *real* strategy engine, bridge, OMS, regime engine
and autonomy path into a simulated broker. Nothing re-implements a strategy, a
rail or a fill. It answers the one question live trading never can — *do the
rails help* — because the same window can be held twice with a rail on and off.

**The discipline, measured by what it caught.** Roughly forty defects in three
weeks, and the categories repeat:

* **A sentence that explains and is wrong.** M81 (a startup warning that was the
  opposite of the truth), M82 (two more), the risk-cap message, `session_check`'s
  three false alarms. *Every defect found on 11 August was in a sentence that
  predicted or explained — never in a number.*
* **A value that cannot be what it claims.** M66/M90 (the cap measured entry
  prices — the running book read 5.01% then 6.34% on the same positions fifteen
  minutes apart), M65, M70, M71.
* **A check that cannot fail.** `refusals.py`'s `"es limit"` pattern never matched
  anything; the first convergence counter could never fire; two tests passed
  against unfixed code.
* **Wall-clock assumptions.** Nine found. One disabled three rails in every
  replay ever run.

---

## What didn't work

**The trial design.** A 10-position cap and a 5% aggregate cap on a $100k account
means the book fills immediately and then nothing happens. The rails were sized
for capital preservation and the trial needed throughput; those are opposed, and
the conflict was never resolved because it was never stated.

**Waiting for observation instead of reading the code.** M71 was parked from
8 August "until a live sell is observed". No app-transmitted sell ever happened —
five sessions of watching, zero. When it was finally fixed from the code on
17 August the cause was exactly what the code had said all along. Eleven days of
waiting bought nothing.

**Hand-maintained state.** Four counts were asserted and wrong in three days.
`handoff_state.py` — deriving the deploy gap, milestone and test count — ended
that class of error outright.

**Three of four "next steps" in the 14 August handoff were void**: already
shipped, impossible, or built on a symbol not in the tradable universe.

---

## What remains untested

Recorded plainly, because an untested path is not a working one.

* **An app-transmitted sell has never happened.** Every closed trade came from a
  broker-side stop. M71's fix, the exit-price correction and the amendment of a
  written row are all **unexercised in production**.
* **The kill-switch has never tripped on a real discrepancy.**
* **M60's declare-then-quarantine has never been exercised.** The MNST split was
  allowed to run as an accepted cost.
* **The corporate-action ADJUSTMENT path is unobserved.** Only the ex-date gate
  was seen working, refusing CRWD in production.
* **The delever sweep has never run** — `QAT_DELEVER_SWEEP_ENABLED=false`.
* **Five rails have never bound**: single-name, sector, correlated-cluster,
  gap-risk, portfolio-ES.
* **The regime gate's value is unmeasured.** The ablation ran on ASX data and all
  three testable rails came back **inside noise** — 0.30 to 0.67 standard errors
  on 80 trades with a 1.21R standard deviation. Resolving a 0.09R effect needs
  roughly **2,800 trades per arm**. No realistic window supplies that.
* **Whether the record can distinguish a measured regime from a default** — it
  could not until M94, deployed today. Every decision written before then is
  ambiguous.

---

## What transfers, and what does not

**Transfers:** the machinery, the research harness, the rails, the ledgers and
audit trail, the evidence framework, the defect-hunting discipline, and every
milestone from M39 onward that is not Alpaca-shaped.

**Does not transfer:** the US expectancy figures, which were never a deliverable
after 12 August; the Alpaca corporate-action measurements; and — found on
17 August — **M70 and M71 both go dormant on IBKR**, because
`_correct_announced_price` only runs from `absorb_broker_fills`, which needs
`recent_fills`, which `IBAdapter` does not implement. That is W1.1's territory
and it is now the critical path.

**The regime engine must be re-sourced, not ported.** All five macro series are
US, and the two carrying most of the signal have no FRED-hosted Australian
equivalent.

---

## The one-line verdict

**The trial failed to answer its own question and succeeded at everything else.**
It could not produce thirty closed trades because its own rails would not let it,
and that is a finding about the design rather than a disappointment. What it did
produce — machinery that holds, an instrument that can ask the edge question
properly, and a documented habit of checking claims against code — is what the
ASX phase starts from.
