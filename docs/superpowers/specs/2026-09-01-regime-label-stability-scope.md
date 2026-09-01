# Scope — the HMM's sensitivity to a seventh column

**1 September 2026. SCOPE ONLY. Nothing here is a fix, and no production code
changes.**

The 31 August Milestone B rejection left a second finding behind it, recorded
rather than chased:

> The controls span 0% to 85.3% with a DETERMINISTIC fit, so a four-state
> Gaussian HMM under diagonal covariance has no stable answer to "add one
> column".

This scopes that. It was scoped by READING THE CODE first, which is where the
useful part came from.

---

## ⚠️ THE INSTRUMENT MEASURES A LABEL PATH PRODUCTION NEVER TAKES

Found before any measurement, by reading `_label_and_scalar`:

    # scripts/research/compare_standardisation.py:114-125
    probs = RegimeFusion().compute(...)
    label = HysteresisGate().update(probs)

**A fresh `HysteresisGate` on every call.** And `axvi_control._labels_for`
calls it once per bar:

    for i in range(len(matrix)):
        label, _ = _label_and_scalar(posteriors[i], sigs, six[: i + 1])

`HysteresisGate.update` on a new gate takes the `_current_label is None` branch
and returns the argmax immediately (`fusion.py:204-207`). **`margin=0.15` and
`min_persistence=3` never engage.**

The live engine builds ONE gate and keeps it:

    engine.py:97    self._hysteresis = HysteresisGate()
    engine.py:386   label = self._hysteresis.update(probs)

So **23.0% / 17.3% / 85.3% are percentages of bars on which the UNSMOOTHED
argmax moved.** Production's published label only moves when a challenger beats
the incumbent by 0.15 for three consecutive bars.

### ⚠️ THIS DOES NOT REOPEN MILESTONE B

Every arm received identical treatment, so the between-arm comparison — the
thing that produced p = 0.30 — is untouched. **Milestone B stays rejected.**
`compare_standardisation`'s own docstring already says why: *"Both arms receive
identical treatment here, so none of this can be the source of any difference
between them."* That claim is correct and remains correct.

What it changes is the **magnitude of the second finding**, which is the only
thing this scope is about. "The HMM has no stable answer to one more column" may
be a statement about a per-bar gate rather than about the HMM.

---

## THE LABEL IS NOT THE ONLY CONSUMER, AND THE OTHER ONE HAS NO SMOOTHING

| Consumer | Reads | Smoothed? | Cost of a wrong reading |
|---|---|---|---|
| Position **SIZE** | the sticky LABEL → `exposure_scalar_for` | ✅ hysteresis | `LOW_VOL` 1.0 → `HIGH_VOL` 0.4 is a **60% cut** |
| Strategy **ELIGIBILITY** | probability **MASS** ≥ 0.5 | ❌ nothing | the strategy stops trading at all |

`HysteresisGate`'s own docstring: *"probs are still reported honestly every
time; only the sticky label is smoothed."* `StrategyEngine._eligible_mass`
(`strategies/engine.py:232`) reads the mass, thresholded at
`regime_eligibility_mass = 0.5`, and its comment says why: *"Probability mass
rather than the argmax label. The label is one draw."*

⚠️ **So the unsmoothed instability the control measured maps onto the ELIGIBILITY
path, not the size path** — and eligibility is the more consequential of the two,
because it is binary. A strategy that becomes ineligible does not trade smaller;
it does not trade.

Exposure scalars, for the record: BULL 1.0, LOW_VOL 1.0, RECOVERY 0.9,
SIDEWAYS 0.7, BEAR 0.5, HIGH_VOL 0.4, RECESSION 0.3.

---

## WHAT WOULD ANSWER IT — three tasks, all on the existing harness

⚠️ **Reading rules fixed HERE, before any number exists.** That is what rejected
Milestone B and item 33, and it only works written down in advance.

### ✅ Task 1 — DONE, 1 September. THE FINDING SURVIVES.

Build the gate once in `_labels_for` instead of per bar. Change nothing else.
Re-run `axvi_control.py` unchanged otherwise.

> **READING RULE.** If the control spread collapses to a narrow band, the "no
> stable answer to one more column" finding is an artefact of a per-bar gate and
> must be **re-recorded at its true size**, not quietly dropped. If the spread
> survives hysteresis, the finding stands as written and bears directly on
> position sizing.

`axvi_control.py` now runs BOTH disciplines in one pass, so **the old numbers
are the control on the change**:

    ==== FRESH gate per bar (every figure before 1 Sep 2026) ====
    baseline label transitions : 29 over 300 bars
    real ^AXVI z-score                 23.0%
    shuffled (same values, no time)    17.3%   [0.0 - 85.3]
    gaussian noise (same moments)      17.3%   [0.0 - 43.7]
    controls reaching the real arm : 18 of 60 (30%)

    ==== ONE GATE across bars (what RegimeEngine does) ====
    baseline label transitions : 8 over 300 bars
    real ^AXVI z-score                 24.3%
    shuffled (same values, no time)    11.8%   [0.0 - 85.3]
    gaussian noise (same moments)      11.0%   [0.0 - 42.3]
    controls reaching the real arm : 23 of 60 (38%)

✅ **THE INSTRUMENT IS INTACT.** The fresh-gate block reproduces 31 August to
the decimal — 23.0%, 17.3%, 17.3%, 18 of 60. Nothing in the one-gate block is
resting on a broken edit.

✅ **THE GATE IS ENGAGING.** Baseline transitions fall **29 → 8** over the same
300 bars. Hysteresis is doing real work, so this is not the same measurement
under two names — the check that would have caught it was printed, not assumed.

❌ **AND THE SPREAD DOES NOT COLLAPSE.** `shuffled` still spans
**[0.0 – 85.3]**, an identical maximum; `noise` [0.0 – 42.3] against
[0.0 – 43.7]. **By the rule written before the run, the finding STANDS.** A
meaningless seventh column can still move the published label on five bars in
six.

⚠️ **WHAT HYSTERESIS ACTUALLY BOUGHT: the median, not the tail.** Control
medians fall 17.3% → 11.8% / 11.0%, so a *typical* meaningless column now moves
far fewer bars. The worst case is untouched. **Smoothing damps flip-flopping
around a boundary; it cannot damp a systematically different posterior path** —
and an added column changes the HMM fit itself, not just the noise around a
stable fit. That mechanism is an inference from the shape of the result, not
something this run measured.

⚠️ **AND IT MAKES MILESTONE B's REJECTION STRONGER, NOT WEAKER.** Controls
reaching the real arm go **18 of 60 (30%) → 23 of 60 (38%)**. On production's own
label path ^AXVI is *less* distinguishable from noise, not more. Do not read the
fall in control medians as "real now separates cleanly": `real` barely moved
(23.0 → 24.3) while the control distribution became more skewed, and the p-value
is the comparison that matters.

⚠️ **A REMAINING UN-FAITHFULNESS, stated rather than papered over.** Production
**refits every 20 bars** (`refit_interval_bars=20`); this harness fits ONCE over
the whole window and predicts across it. So the posterior path still is not
production's. That property is pre-existing and identical in both blocks, so it
cannot be the source of the difference between them — but it does mean neither
block is production, and Task 3 should carry the refit cadence if it is going to
claim anything about live stability.

### ✅ Task 2 — DONE, 1 September. **THE PREDICTION IN THIS DOCUMENT WAS WRONG.**

Record the percentage of bars on which `mass >= 0.5` flips for the deployed
strategy (`swing`), across the same arms.

> **READING RULE.** If eligibility flips materially more than the smoothed label
> does, the exposure is in strategy admission rather than in sizing, and any
> future work belongs there. If it flips comparably, one number covers both.

    ==== ELIGIBILITY of `swing` (mass >= 0.5, NO smoothing) ====
    baseline eligible on         : 89.7% of bars
    baseline admission flips     : 4 over 300 bars

    real ^AXVI z-score                  1.0%
    shuffled (same values, no time)     0.3%   [0.0 - 11.3]
    gaussian noise (same moments)       0.3%   [0.0 -  4.0]
    controls reaching the real arm : 19 of 60 (32%)

Against the ONE-GATE label block on the identical window, seed and arms:

| | control median | control max | baseline churn |
|---|---|---|---|
| LABEL (hysteresis) | 11.8% | **85.3%** | 8 transitions / 300 |
| ADMISSION (no smoothing) | **0.3%** | **11.3%** | **4 flips / 300** |

❌ **ADMISSION IS ~40× MORE STABLE THAN THE LABEL, not less.** The scope argued
the opposite above — that because nothing smooths the mass path, that is where
the exposure would be. **That reasoning was wrong**, and it was wrong for an
interesting reason.

### ⚠️ THE REAL STABILISER IS AGGREGATION, NOT HYSTERESIS

`swing.suitable_regimes()` is `{SIDEWAYS, BULL, LOW_VOL, RECOVERY}` — **four of
the seven regimes.** `_eligible_mass` SUMS the distribution over that set, so the
label can move freely *among* those four without the sum going anywhere near
0.5. The label distinguishes bull from low_vol from sideways; admission does not
care which, only that it is one of the risk-on four.

**Summing over a set is a far stronger stabiliser than a 0.15 margin and a
three-bar streak.** Hysteresis smooths a sequence; set-membership collapses a
whole dimension of the disagreement before the threshold ever sees it.

### ⚠️ SO THE EXPOSURE IS IN SIZING, AND ONLY IN SIZING

The added-column fragility from Task 1 lands on the **exposure scalar**, not on
whether the strategy trades. That is operationally better news — admission is
robust — and it means **Task 1's numbers are the whole story**, with the cost
denominated in position size (LOW_VOL 1.0 → HIGH_VOL 0.4) rather than in
missed trading.

### ⚠️ RECORDED, NOT CHASED: admission is far more permissive than the label

`swing` is admitted on **89.7% of bars** on this window. The 30 July measurement
behind `suitable_regimes()`'s widening recorded label frequencies of bull 32.0%,
bear 26.6%, high-vol 24.9%, low-vol 10.4%, sideways 6.2% — which would put
label-based eligibility near 48.6%.

⚠️ **Those two are NOT comparable and must not be quoted as a gap**: different
windows (300 sessions to 29 July against 300 bars to 26 August) and different
criteria (set membership of the argmax against a summed mass at 0.5). But the
direction is large enough to be worth one apples-to-apples run some day —
label-based against mass-based eligibility on the SAME window. Not run, not
claimed.

### ✅ Task 3a — DONE. THE FINDING IS GENERAL, and single-window p-values are not.

    window                    real  shuffled                noise                     p
    bars   0-300 (n=300)     24.3%     11.8% [ 0.0- 85.3]    11.0% [ 0.0- 42.3]  23 of 60
    bars   0-150 (n=150)     14.0%     11.3% [ 0.0- 65.3]     0.7% [ 0.0- 23.3]  21 of 60
    bars  75-225 (n=150)     76.0%     28.0% [ 0.0- 86.7]    14.7% [ 0.0- 89.3]   6 of 60
    bars 150-300 (n=150)     40.7%     60.0% [ 0.0- 77.3]    50.3% [ 0.0- 86.7]  38 of 60

✅ **By the rule written before the run, the finding HOLDS.** Control maxima are
**65.3, 86.7, 89.3, 85.3, 77.3, 86.7** — high on *every* window. A meaningless
seventh column moving the label on most bars is not an artefact of one alignment.

⚠️⚠️ **AND A SECOND RESULT THAT IS ARGUABLY BIGGER: A SINGLE-WINDOW p IS NOT
TRUSTWORTHY.** `real` swings **14.0% → 24.3% → 40.7% → 76.0%** across windows,
and the empirical p with it: **6 of 60 (10%)** on bars 75–225 against **38 of 60
(63%)** on bars 150–300.

**On bars 75–225, ^AXVI would have PASSED.** Had Milestone B been measured on
that window, the control would have endorsed it.

⚠️ **This does NOT overturn Milestone B's rejection**, and must not be quoted as
if it did: the full window carries the most data, three of four windows show
nothing, and 150–300 runs strongly the other way. What it establishes is that
**one window's p-value is close to worthless on this model** — which is exactly
what `axvi_control`'s own "ONE WINDOW ONLY" caveat said, now with numbers behind
it.

### ✅ Task 3b — DONE. **PRODUCTION'S REFIT CADENCE CHANGES THE ANSWER MATERIALLY.**

240 bars classified, `min_fit_bars=60` withheld, denominators matched:

    arm                       real  shuffled                noise                     p
    single fit (control)     30.4%     14.8% [ 0.0- 87.1]    13.8% [ 0.0- 52.9]  23 of 60
    refit every 20           33.3%     30.2% [14.2- 55.0]    33.5% [12.9- 50.8]  28 of 60

❌ **They differ materially, so by the rule written before the run, figures taken
on the single-fit harness must be RE-TAKEN — Milestone C's ablation percentages
included.**

⚠️ **THE SHAPE OF THE DIFFERENCE MATTERS MORE THAN ITS SIZE. The floor comes off
the floor.** Control minima go **0.0 → 14.2 and 0.0 → 12.9**. Under a single fit,
some meaningless columns changed *nothing at all*; under production's cadence,
**every meaningless column moves the label on at least ~13% of bars.** The
"harmless column" case does not exist in production.

The ceiling falls at the same time (87.1 → 55.0, 52.9 → 50.8), and the medians
roughly double (14.8 → 30.2, 13.8 → 33.5). **Refitting compresses the range and
raises the whole distribution** — a plausible mechanism is that each refit is a
fresh chance to reorganise the states, so the perturbation is re-rolled fifteen
times instead of once. That is an inference from the shape, not measured here.

✅ **Milestone B is untouched again**: p moves only 23/60 → 28/60, still nowhere
near significance.

⚠️ **hmmlearn logged 23 non-convergence warnings during this run**, concentrated
in the refit arm, which fits on expanding windows as short as 60 bars.
`HMMRegimeModel._decreasing_loglik_warnings` exists to count exactly this. Not
investigated; recorded because it is a property of the path production actually
takes and the single-fit harness never exercises.

### Task 3 — more than one window (original scoping note)

Milestone C established that every column except `vix_level` swings three- to
fourfold with the window, and `axvi_control` says so itself: *"ONE WINDOW ONLY …
a single window settles the SIGNAL-vs-ARTEFACT question and nothing about
stability."* The 31 August run was one window. Stability is the whole question
here, so a single window cannot answer it.

---

## WHAT THIS SCOPE EXPLICITLY EXCLUDES

* **No change to the regime engine.** Not a fix, not a design for one.
* **Not a re-run of Milestone B.** Rejected on 31 August; this does not reopen it.
* **Not Milestone C's ablation re-measurement** — but ⚠️ **flag it**: every
  ablation percentage was produced through the same per-bar gate and inherits
  whatever Task 1 finds. Recorded, not chased, exactly as the 31 August note
  recorded this one.

## COST

Task 1 is a few lines in a research script and one run. Tasks 2 and 3 are extra
arms on the same harness. **No production code, no build, no deploy.** The whole
scope is research-script work against a saved matrix and yfinance history.

## ⚠️ THE PRECEDENT THAT MAKES THIS WORTH CHECKING FIRST

This model has already had one column-sensitivity crisis, and it was the
instrument's fault rather than the model's: KMeans initialisation on the raw
matrix let `vix_level`'s scale decide where the states went, **measured at 87.8%
on 26 August**, fixed by standardising before hmmlearn sees the matrix
(`hmm_core.py:113-117`).

**85.3% and 87.8% are the same order of magnitude.** That is not proof of
anything, and it is a reason to check the instrument before concluding the model
is fragile — which is what reading `_label_and_scalar` turned out to be worth.
