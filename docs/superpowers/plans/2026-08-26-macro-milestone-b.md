# Macro Milestone B — Australian Regime Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the regime engine an Australian volatility feature, so the label that sets position size on a 94-stock ASX book is not classified entirely on American data.

**Architecture:** A per-series transformation policy in `feature_matrix.py`, an as-of history join generalised beyond FRED, and a `MarketSeriesSource` for yfinance tickers behind the existing `MacroDataSource` protocol. **One feature is admitted, not five** — `^AXVI`, the ASX 200 VIX — because that is what the measurements support.

**Tech Stack:** Python 3.12, `hmmlearn` 0.3.3, yfinance, NumPy, pytest.

## Gate: Milestone A has run live

Deployed as M146 at 14:35 on 26 August, ran to the close. Live confirmation matched the offline prediction to the decimal — `Raw feature spread is led by vix_level at 85.0% of the total`, and `REGIME none -> bull (exposure scalar 1.00)` against a predicted `label=bull scalar=1.00`. **The matrix is scale-neutral and the label did not move.** That was B's precondition.

## ⚠️ The measurements, and how they change the sketch

The original research listed `^AXVI`, the AU curve, `AUDUSD=X` and `TIO=F` as candidates. Measured 26 August over 508 daily bars, each in the form it would actually enter the matrix, against ASX 200 realised volatility 20 days FORWARD:

| Candidate | Form | Drift (÷sd) | vs vol | vs vol **+20d** |
|---|---|---|---|---|
| `^AXVI` ASX 200 VIX | **20d z-score** | **0.01** | +0.277 | **+0.455** |
| `^AXVI` | level | 0.09 | +0.564 | +0.404 |
| `^AXVI` | log-change | 0.00 | −0.073 | +0.086 |
| `^AXJO` ASX 200 | 20d z-score | 0.26 | −0.310 | −0.382 |
| `^AXFJ` Financials | 20d z-score | 0.37 | −0.163 | −0.290 |
| `TIO=F` iron ore | level | 0.69 | +0.023 | +0.165 |
| `AUDUSD=X` | level | 1.35 | +0.110 | +0.091 |

**Three conclusions, and two of them reject work the sketch assumed:**

1. **`^AXVI` is the feature worth adding**, and its **z-score** form is better forward than its level (+0.455 vs +0.404) while being the most stationary thing measured. It also beats the incumbent `VIXCLS` (+0.289 forward).
2. **`AUDUSD=X` and `TIO=F` do not earn a place.** Best-case +0.091 and +0.165, in no form better than noise for this purpose. **They are rejected on evidence, and that rejection is recorded rather than quietly dropped.**
3. **`^AXJO` is redundant.** Its z-score looks strong (−0.382) but the matrix already carries `log_return` and `realized_vol` derived from STW.AX, which tracks it. Adding it would re-express information already present, and under `covariance_type="diag"` correlated columns double-count.

⚠️ **These are MARGINAL PAIRWISE correlations on ONE two-year window.** The HMM uses joint structure; a feature can contribute through interaction while looking weak alone. This is evidence for admitting one candidate provisionally, not a verdict. **Milestone C's ablation is what adjudicates**, and Task 5 gates on it.

⚠️ **`statsmodels` is NOT installed**, so the stationarity column is a drift proxy — the shift in mean between the first and second half of the window, in standard deviations — not an ADF test. It separates 0.01 from 1.35 clearly enough to decide form, and it should not be quoted as a formal test.

## Global Constraints

- **PowerShell, never the Bash tool**, for anything touching `%LOCALAPPDATA%\QuantAdvisoryTerminal` or constructing `Settings()`.
- **Format with `black`, not `ruff format`.** All four clean: `ruff check .`, `black --check .`, `mypy src`, `bandit -r src`.
- ⚠️ **CI is BLOCKED at the GitHub billing wall.** The local suite is the ONLY verification.
- ⚠️ **A new setting must be documented in the manual** or `test_manual_documents_every_setting` fails.
- ⚠️ **A KILLED build leaves `src/qat/_build_stamp.py` behind** and four version tests then fail; delete that generated file to recover.
- **Deploy before the open or after the close.** This changes a sizing input.
- Baseline: **2,775 passed, 25 skipped.**

---

## File Structure

| File | Responsibility |
|---|---|
| `src/qat/data/market_series.py` | **Create.** `MarketSeriesSource` — yfinance tickers behind the existing `MacroDataSource` protocol. |
| `src/qat/data/macro_fred.py` | **Modify.** Generalise `load_macro_history` so the as-of join is not FRED-shaped. |
| `src/qat/domain/regime_engine/feature_matrix.py` | **Modify.** A per-series transformation policy, and the new column. |
| `src/qat/config.py` | **Modify.** The ticker list and the feature toggle. |
| `tests/data/test_market_series.py` | **Create.** Absent-not-zero, and the protocol contract. |
| `tests/domain/regime_engine/test_feature_transforms.py` | **Create.** The transformation policy. |

---

## Task 1: `MarketSeriesSource` — yfinance behind the existing protocol

**Files:**
- Create: `src/qat/data/market_series.py`
- Test: `tests/data/test_market_series.py`

**Interfaces:**
- Produces: `MarketSeriesSource` satisfying `MacroDataSource` — `async def fetch_series(self, series_id: str) -> list[MacroObservation]`, oldest observation first, where `series_id` is a yfinance ticker such as `^AXVI`.

⚠️ **The rule this codebase enforces everywhere: a series that cannot be fetched is ABSENT, never zero.** M73's `var_95=0.0` and this week's `held_in_sector_dollars: 0.0` are the same failure. A macro source that silently reports a flat series is that failure again — and `engine.py:_fit` already logs a constant column by name, which is the behaviour to preserve.

- [ ] **Step 1: Write the failing test**

Create `tests/data/test_market_series.py` covering, each as its own test:
- a successful fetch returns `MacroObservation` records with `series`, `ts` and `value`, **oldest first**, matching what `load_macro_history`'s as-of join expects;
- a fetch that raises **propagates** rather than returning `[]` — `load_macro_history` already catches, retries once, and logs "seeding without it", and that is the layer that should decide;
- a ticker that yfinance returns EMPTY for raises rather than returning an empty list silently. ⚠️ yfinance returns an empty frame for a bad ticker rather than raising — measured 26 August, when a bad symbol produced `possibly delisted; no price data found` at ERROR and an empty result, not an exception.

Use a fake in place of the network. Do not hit yfinance in a unit test.

- [ ] **Step 2: Run and confirm it fails** — `ModuleNotFoundError`.

- [ ] **Step 3: Implement** `MarketSeriesSource`, mirroring `FredMacroSource`'s shape (it takes no constructor arguments and does its blocking work in `asyncio.to_thread`).

- [ ] **Step 4: Run** `.venv\Scripts\python.exe -m pytest tests/data/ -q`

- [ ] **Step 5: Commit** — `Milestone B: a market-series macro source behind the existing protocol`

---

## Task 2: Generalise the as-of history join

**Files:**
- Modify: `src/qat/data/macro_fred.py` — `load_macro_history`, `MacroHistory`
- Test: append to the existing macro history tests

**Interfaces:**
- Consumes: `MacroDataSource` (either implementation).
- Produces: `load_macro_history(sources, series_ids)` able to draw different series from different sources, with the as-of join unchanged.

**Why this is its own task.** `load_macro_history` takes ONE source and a list of ids. `^AXVI` comes from yfinance while `VIXCLS` comes from FRED, and the warm start needs both on one bar timeline. This is the hidden cost the original research did not price.

⚠️ **Do not change the as-of semantics.** The forward-fill onto the bar timeline is deliberate and documented; this task changes only where a series comes FROM.

⚠️ **Preserve the per-series failure behaviour exactly**: a series that cannot be fetched is omitted, retried once, and logged as "seeding without it — its feature column will be constant for this session". That message is what makes a missing series diagnosable.

- [ ] **Step 1** Write a failing test: two series from two different sources land on one timeline, and a failure in one does not lose the other.
- [ ] **Step 2** Confirm it fails.
- [ ] **Step 3** Implement.
- [ ] **Step 4** Full suite.
- [ ] **Step 5** Commit — `Milestone B: draw macro history from more than one source`

---

## Task 3: The transformation policy

**Files:**
- Modify: `src/qat/domain/regime_engine/feature_matrix.py`
- Test: `tests/domain/regime_engine/test_feature_transforms.py`

**Interfaces:**
- Produces: a declared per-series transform applied in `update_macro`, with `level` the default so every existing feature is unchanged.

**This is the task Milestone A does NOT cover.** Standardisation fixed scale; it does nothing about stationarity. A z-score of a trending level is still a trend, because the mean and std are fitted once on a window the series then walks away from.

Implement three forms, because the measurement used three: `level`, `log_change`, and `rolling_z` (60-bar mean and standard deviation, matching what was measured).

⚠️ **`rolling_z` needs a warm-up and must not fabricate a value before it has one.** The existing `breadth` feature returns a neutral `0.5` before `breadth_window` bars — follow that precedent deliberately, and state in the docstring which neutral value is used and why. **Do not silently emit 0.0**, which would be indistinguishable from a genuine mid-range reading.

- [ ] **Step 1** Write failing tests: each form computes what the measurement computed; the default is `level` so existing features are untouched; `rolling_z` before warm-up returns the declared neutral rather than a fabricated number.
- [ ] **Step 2** Confirm they fail.
- [ ] **Step 3** Implement.
- [ ] **Step 4** Full suite. ⚠️ **If an existing regime test changes behaviour, STOP** — `level` must be a no-op for the six current features, and anything else means the default is not being applied.
- [ ] **Step 5** Commit — `Milestone B: a declared transform per macro feature`

---

## Task 4: Admit `^AXVI`, and nothing else

**Files:**
- Modify: `src/qat/config.py`, `src/qat/domain/regime_engine/feature_matrix.py`
- Modify: the manual
- Test: `tests/domain/regime_engine/test_feature_transforms.py`

**Interfaces:**
- Produces: `FEATURE_NAMES` gains `asx_vix_z`, sourced from `^AXVI` under the `rolling_z` transform.

**ONE feature.** `AUDUSD=X` and `TIO=F` are rejected on the measurements above; `^AXJO` is redundant with `log_return` and `realized_vol`. Admitting one at a time is also what makes the ablation in Task 5 readable.

⚠️ **This changes `FEATURE_NAMES` from six entries to seven, and the matrix width with it.** Check every consumer: `_fit`'s `zip(FEATURE_NAMES, ranges, strict=True)` will raise on a mismatch — which is the good case — but `_LOG_RETURN_COL` and `_REALIZED_VOL_COL` are positional and must stay valid. Append rather than insert.

⚠️ **Behind a setting, default OFF for the first deploy.** The regime label sets the exposure scalar. A feature that can be turned on without a rebuild is how the before/after gets measured on the same binary.

- [ ] **Step 1** Failing test: with the setting on, the matrix has seven columns and the seventh is the z-scored `^AXVI`; with it off, six and unchanged.
- [ ] **Step 2** Confirm it fails.
- [ ] **Step 3** Implement, and document the setting in the manual.
- [ ] **Step 4** Full suite.
- [ ] **Step 5** Commit — `Milestone B: admit the ASX 200 VIX as a regime feature, behind a switch`

---

## Task 5: Measure before deploying, and let the ablation decide

**Files:**
- Modify: `scripts/research/compare_standardisation.py`, or a sibling script

**This is the gate, and it is the one that can still reject the feature.**

- [ ] **Step 1** Rebuild the real feature matrix both ways — six columns and seven — on the same window, the way Milestone A's Task 4 did.
- [ ] **Step 2** Run both through the **real fusion path** — `RegimeFusion.compute`, `HysteresisGate`, `exposure_scalar_for` — and print the **named label and exposure scalar** for each. ⚠️ Milestone A's first attempt compared raw posterior indices and was rejected in review for exactly this: hmmlearn numbers states arbitrarily, so an index change proves nothing. **The label is the thing consumed.**
- [ ] **Step 3** Report how often the label DIFFERS across the window, not just on the final bar. A feature that changes the label on one day in three hundred is not worth a sizing risk.
- [ ] **Step 4** ⚠️ **If the label is unchanged everywhere, say so and STOP.** That is a legitimate and valuable outcome: it means `^AXVI` adds nothing the existing features do not already carry, and the honest response is to reject it rather than ship a feature for its own sake. **Record the rejection with its numbers.**
- [ ] **Step 5** If the label does move, deploy after the close with the setting ON, read the build back, and watch a full session — comparing the regime label and the governor's aggregate against the previous session.

---

## What this plan deliberately does NOT do

- **The RBA CSV sources and the AU yield curve.** Measured as reachable on 25 August, but no candidate from them was measured against forward volatility, so admitting one would be taste rather than evidence. It belongs in a later milestone with its own measurement.
- **Replacing `BAA10Y` with `BAMLH0A0HYM2`.** Measured on 25 August: `BAA10Y` carries +0.004 against forward ASX vol and `BAMLH0A0HYM2` carries +0.160. That is a real finding and a separate change — it removes a feature as well as adding one, and it should be judged by Milestone C's ablation on the same footing as everything else, not smuggled in beside a new column.
- **Milestone C.** Task 5 uses a hand-rolled comparison because the ablation harness has no `--feature` arm yet. Building that arm is Milestone C and remains the right long-term answer.
