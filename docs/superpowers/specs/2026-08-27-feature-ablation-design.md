# Macro Milestone C — a `--feature` arm for the ablation harness

**Design, 27 August 2026.** Approved by the operator before writing.

**Goal:** let the ablation harness adjudicate a *regime feature column* the way
it already adjudicates a *rail*, so Milestone B's `^AXVI` question is answered
by the instrument rather than by a hand-rolled script.

**Why it is the gate on everything macro.** Milestone B is planned, measured and
correctly blocked behind this. Adding `^AXVI` moves the regime label on **69 of
300 bars (23.0%)**, always toward more defensive — and that may be signal, or it
may be volatility over-representation, because the matrix would then carry
**three volatility columns out of seven** under `covariance_type="diag"`, which
treats columns as independent and therefore double-counts correlated ones. A
systematic shift toward defensive labels is exactly what that artefact would
look like. Marginal correlations cannot separate the two. An ablation can.

`docs/superpowers/plans/2026-08-26-macro-milestone-b.md` states the dependency
in its own closing section: *Task 5 uses a hand-rolled comparison because the
ablation harness has no `--feature` arm yet. Building that arm is Milestone C.*

---

## The constraint everything else is shaped by

`src/qat/domain/backtester/ablation.py` opens with the harness's founding rule:

> A rail is disabled by setting its existing `Settings` value beyond reach, so
> the shipped `RiskEngine` and `PortfolioGovernor` run exactly as they trade.
> Nothing in the trading path is edited, which is what makes this compatible
> with a freeze whose test is *would this change which trades happen*.

and it records the tempting alternative as **already rejected**:

> REJECTED, and it will be proposed again: threading a rail set through
> `RiskEngine` and `PortfolioGovernor` with `if enabled(...)` guards … a guard
> defaulting to on is still an edit to the decision path.

**This design does not reopen that.** A feature is made absent the same way a
rail is: by a `Settings` value.

---

## Architecture

Six components. Three change shipped code, three are harness-side only.

| Component | Where | Shipped? |
|---|---|---|
| 1. `regime_features` setting | `config.py`, `feature_matrix.py`, `hmm_core.py` | **yes — sizing input** |
| 2. `FEATURES` table | `backtester/ablation.py` | research only |
| 3. Per-bar regime record | `scripts/research/run_ablation.py` | research only |
| 4. Terminal equity | `backtester/manifest.py`, `run_ablation.py` | research only |
| 5. `compare_feature_runs` | `backtester/run_comparison.py` (sibling) | research only |
| 6. CLI | `scripts/research/run_ablation.py` | research only |

### 1. `regime_features` becomes a Setting

An **ordered** list naming the enabled feature columns, defaulting to exactly
today's six. `RegimeFeatureBuilder` emits only the named columns; the current
module-level `FEATURE_NAMES` tuple becomes that default rather than a constant.

The list is ordered because the matrix is positional and the HMM is fitted on
column order. Two runs whose lists differ only in order would produce a
different matrix and be silently incomparable.

⚠️ **`hmm_core.py:20-21` reads two columns positionally:**

    _LOG_RETURN_COL = 0
    _REALIZED_VOL_COL = 1

used at `:192-193` to build each fitted state's `mean_return` and `mean_vol` —
that is, to **describe** a state, which is how a label gets its meaning. These
become index lookups against the run's own list.

**`log_return` and `realized_vol` are therefore refused by name as
unablatable**, with the reason recorded — exactly the way `_TWO_CONSUMERS`
already refuses `apply_costs_in_paper`. Dropping either would not ablate a
feature; it would break state description, and every label downstream with it.
Refusing loudly beats returning a run whose labels mean something else.

### 2. A `FEATURES` table in `ablation.py`

Mirrors `RAILS`: which columns can be ablated, and which are refused with the
reason. Milestone B's `asx_vix_z` later joins by adding one line — so **"drop
one of six" and "admit a seventh" become the same operation**, which is the
property that makes B's question answerable at all.

A `feature_settings(base, disabled)` sibling to `ablated_settings`, re-validated
through `Settings.model_validate` for the same reason its neighbour is: a
`model_copy(update=...)` writes fields without running their validators.

An unknown or refused feature raises **`UnablatableFeature`** — a new exception
class beside `UnablatableRail`, not a reuse of it, so a caller can tell a rail
problem from a feature problem without parsing a message. Raised rather than
ignored, for the reason the existing docstring already gives and which holds
here unchanged: *silently running a baseline twice and reporting no difference
is indistinguishable from a rail that costs nothing.*

### 3. A per-bar regime record

`_one()` subscribes to `RegimeEvent` on the session bus and writes
`regime_path.csv` — `ts, label, exposure_scalar` — into the run directory.

The harness listens to an event the app already publishes. **No trading-path
change**, and it is the same seam `_one()` already uses for `start_regime`.

⚠️ **`risk_decisions.csv` cannot serve this.** It carries `regime_label` in its
`inputs` only on bars where a decision happened, so "the label never differed"
would be indistinguishable from "no decisions happened" — which is precisely the
blindness `run_comparison.py` exists to refuse.

### 4. Terminal equity in the manifest

`_one()` reads `broker.get_account().net_liquidation` after `session.run()`, and
`build_manifest` carries it. `SimulatedBroker.get_account` already computes it
(`simulated_broker.py:187`) as cash plus market value.

### 5. `compare_feature_runs` — guard first, same as its sibling

A sibling of `compare_runs`, not a modification of it: the rail arm's guards are
correct for rails and this arm needs different ones.

**Guards, in order:**

* **NOT EXERCISED** — the label never differed between the arms across the
  window. The feature changed nothing there was anything to change. Every number
  suppressed, not printed as a zero. (The analogue of a rail that never bound.)
* **STILL ENABLED** — the ablated arm's manifest still lists the feature. Cheap
  to cause by passing the wrong directory and invisible unless checked.
* **UNKNOWN FEATURE** — named, never guessed.

**Report, when none of those fire:**

1. **Terminal equity per arm and the delta** — the headline.
2. **Bars where the label differs**, count and percent — the mechanism.
3. **The existing trades / win / R block underneath** — so a changed trade *set*
   stays visible separately from a changed *size*.

⚠️ **Why the headline is equity and not R.** `compare_runs._arm()` reports
trades, win%, R-mean and R-total. R-multiple is normalised by risk and win% is
scale-free, so **a feature that halved every position leaves all four figures
identical**. A regime feature moves the exposure scalar, which moves position
*size*. The one thing the existing report prints is the one thing that cannot
see the effect. Size does feed back into the aggregate-risk and concentration
caps, so some trades will differ — but that is second-order, and reporting it
alone would print "the feature cost nothing" for a feature that halved the book.
That is the *a zero gets quoted and a caveat does not* failure, in the module
built to prevent it.

`manifest.py` already models this kind of rail and needs no fourth category —
its docstring names the regime gate as `Observability.SCALAR`: *"the rail never
refuses, it multiplies SIZE."* Reused rather than reinvented.

### 6. CLI

* `--feature X`, mutually exclusive with `--rail`; one of the two required.
* `--list` grows a features section alongside the rails.
* `--feature` defaults the universe to **ASX**.

⚠️ **The ASX default is per-arm and that is a mild footgun, accepted
deliberately.** The regime question is about a 94-stock ASX book. The US G1
cache is 200 sessions against `warm_bars=120`, leaving **80 replay bars** — too
few for a regime label to move meaningfully. ASX is 500 against 250, leaving
~250. `--rail` keeps its US default so every existing invocation is unchanged.

---

## Error handling

* An unknown feature, or a refused one (`log_return`, `realized_vol`), raises
  with the reason. Never a silent baseline-twice.
* A feature named in `regime_features` that no builder can produce raises at
  matrix construction rather than emitting a constant column. **A series that
  cannot be produced is ABSENT, never zero** — the rule this codebase enforces
  everywhere, and `engine.py:_fit` already logs a constant column by name.
* **The matrix cannot be narrowed below two columns**, because `log_return` and
  `realized_vol` are refused as unablatable — so "too few columns to fit" is
  unreachable by construction rather than guarded at runtime. Said explicitly
  because the first draft carried a vague "hard error" for a case that cannot
  arise, and a guard for an impossible case is a guard nothing will ever
  exercise.

## Testing

* `feature_settings` refuses `log_return` and `realized_vol` by name, with the
  reason, and refuses an unknown feature.
* The default list produces a matrix **byte-identical** to today's six columns.
* A narrowed list produces the expected width, and the expected columns in the
  expected order.
* The `_LOG_RETURN_COL` / `_REALIZED_VOL_COL` lookups resolve against a
  reordered list — the case the positional constants got right only by accident.
* Each `compare_feature_runs` guard, constructed rather than described.
* The `regime_path.csv` recorder writes one row per `RegimeEvent`.

⚠️ **Every guard must be seen to FAIL before it is believed.** The habit that
paid for itself on 26 August: a test never observed failing is not evidence.

---

## What this deliberately does NOT do

* **It does not add `^AXVI`.** That is Milestone B Tasks 1–4, which plug into
  the table in §2. C is the instrument; B is the measurement.
* **It does not change the shipped default.** `regime_features` must produce a
  byte-identical six-column matrix. ⚠️ **If any existing regime test changes
  behaviour, STOP** — that means the default is not being applied. Do not adjust
  the test.
* **It does not touch `RegimeFusion`, `HysteresisGate` or `exposure_scalar_for`.**
* **It does not decide `BAA10Y` vs `BAMLH0A0HYM2`.** That swap removes a feature
  as well as adding one, and it should be judged by this harness on the same
  footing as everything else rather than smuggled in beside it. It becomes
  answerable once this arm exists, which is a reason to build the arm and not a
  reason to widen it.

## Risks, stated rather than discovered later

1. **This is a sizing-input change.** `FEATURE_NAMES` goes from a module
   constant to a `Settings`-driven list, and the regime label sets the exposure
   scalar. The default is a no-op, but the mechanism is live in the shipped
   binary. **Deploy after the close**, like any other sizing change — never
   mid-session.
2. **The windows will not line up.** The ASX cache gives ~250 replay bars
   against Milestone B's 300-bar measurement, so the two are not directly
   comparable. ⚠️ Per the ninefold-slip lesson of 26 August — where a three-day
   calendar shift understated an effect from 23.0% to 2.7% — **the arm prints
   its date range**, and any number is checked against it before being believed.
3. **A new setting must be documented in the manual** or
   `test_manual_documents_every_setting` fails.
4. **The result may be null, and that is a legitimate outcome.** If the ablation
   says `^AXVI` buys nothing, Milestone B is rejected with its numbers recorded.
   Building the instrument is worth it either way; shipping a feature for its
   own sake is not.

## Global constraints

* **PowerShell, never Bash**, for anything touching
  `%LOCALAPPDATA%\QuantAdvisoryTerminal` or constructing `Settings()`.
* **Format with `black`, not `ruff format`.** All four clean: `ruff check .`,
  `black --check .`, `mypy src`, `bandit -r src`.
* ⚠️ **CI is at the GitHub billing wall.** The local suite is the ONLY
  verification. Baseline: **2,775 passed, 25 skipped**.
* ⚠️ **Commits are LOCAL — the operator has a standing hold on pushing** as of
  27 August 2026.
* ⚠️ A KILLED build leaves `src/qat/_build_stamp.py` behind and four version
  tests then fail; delete that generated file to recover.
