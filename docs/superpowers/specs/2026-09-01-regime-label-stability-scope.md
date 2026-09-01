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

### Task 2 — measure the ELIGIBILITY path, which nothing smooths

⚠️ **Task 1 RAISED this one's priority.** The label has hysteresis and is still
moved on up to 85.3% of bars by a meaningless column. Eligibility has no
smoothing at all.

Record the percentage of bars on which `mass >= 0.5` flips for the deployed
strategy (`swing`), across the same arms.

> **READING RULE.** If eligibility flips materially more than the smoothed label
> does, the exposure is in strategy admission rather than in sizing, and any
> future work belongs there. If it flips comparably, one number covers both.

### Task 3 — more than one window

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
