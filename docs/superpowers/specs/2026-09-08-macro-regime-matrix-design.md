# Macro Regime Matrix — adopting `AI Guidance.md`

**Source:** `C:\ShareTrader\AI Guidance.md`, reviewed 8 September 2026.
**Status:** design only. No code has been written against this.

The document specifies a 7-regime macro matrix, an exact exposure calculation
per regime, and an If/Then/Justification narrative format for the output. This
records how it maps onto what QAT already computes, what it needs that does not
exist, and the decisions that must be made before any of it is built.

⚠️ **The document's sample values appear to be QAT's own.** `BM 0.85` is exactly
`MACRO_REGIME_EXPOSURE_HINT["neutral"]`, and the RV and drawdown fields match
`MacroSignal`'s shape. The fit is real; the gaps below are the honest part.

---

## 1. The governing decision: the math is deterministic, the model writes prose

The document reads as a single prompt asking the model to classify the regime
AND compute `Lift = ((HV - RV) / HV) * SB`. **That is the wrong division of
labour here, and this codebase has already ruled on it.**

`MacroSignal`'s own docstring: *"Every field is computed, never modelled - this
object is the same for the same bars, always."* And `data/news.py`: *"a model
asked to be sceptical is not a control"*.

**So:** the deterministic layer produces `active_regime`, `lift_or_cut` and
`target_weight`. Those are handed to the model as FACTS. The model does only
what it is good at - constraints 1 to 5, the If/Then/Justification prose - and
is explicitly forbidden from recalculating.

⚠️ An LLM performing arithmetic that sets an exposure target is the failure mode
`ai_advisory/guards.py` exists for. The same output is achievable with none of
that risk.

---

## 2. What already exists

| Document variable | QAT source | State |
|---|---|---|
| Realized Volatility `RV` | `MacroSignal.realized_vol_annualized_pct` - 20d, annualised | OK |
| Baseline Model `BM` | `MacroSignal.exposure_hint` - 1.0 / 0.85 / 0.6 / 0.3 | OK |
| Drawdown | `MacroSignal.drawdown_from_recent_high_pct` - 20d high | OK |
| VIX | `macro_series["VIXCLS"]` | fetched, unused for regime |
| Yield spreads | `T10Y3M`, `BAA10Y`, `DGS3MO`, `DGS10` | fetched, unused for regime |
| Trend | `MacroSignal.pct_above_trend` - vs 50d SMA | ⚠️ PRICE trend, not growth |

The plumbing to reach the model already exists too: `AdvisoryContext` carries
`macro_signal` and `macro_series` as plain dicts, and `MacroAssessment` already
models a proposal-only exposure scalar.

---

## 3. What is missing and must be developed

**3.1 `HV` - historical baseline volatility. BLOCKING.**
There is no baseline anywhere. `_VOL_HIGH_ANNUALIZED_PCT = 25.0` is a
THRESHOLD, not a baseline, and every formula in the document divides by `HV`.
Needs the same realised-vol computation over a long window (1-2 years), per
market. ⚠️ Must follow `compute_macro_signal`'s existing habit of returning
`None` rather than a degraded figure when history is short - a volatility number
from too few bars is a different number, not a less precise one.

**3.2 `SB` - safety buffer. BLOCKING, but trivial.**
Does not exist in any form. Pure configuration. The work is not the code, it is
deciding the value and writing down why. The document proposes 0.20.

**3.3 The GROWTH axis. BLOCKING, and the largest piece.**
Every regime keys on growth: high, negative, normal, low, accelerating, flat.
QAT has PRICE TREND against a 50-day average. ⚠️ **These are not the same thing
and must not be substituted for one another** - that is precisely the silent
category error this project keeps finding. Needs a real growth series and a
classifier over it.

**3.4 Rate of change for two series. BLOCKING for regime 6 and part of 3.**
"Accelerating growth" and "subsiding volatility" are DERIVATIVES. Nothing
computes the direction of either; only levels exist.

**3.5 A spreads-distress threshold.**
BEAR and RECESSION differ only by "distressed spreads". `BAA10Y` is fetched and
never classified, so as things stand **those two regimes are indistinguishable**
and the matrix cannot choose between them.

**3.6 Term-structure state.**
The document names "Flat / Inverted" as an input. `T10Y3M` supplies the number;
nothing turns it into a state.

**3.7 A mean-reversion measure.**
SIDEWAYS requires "constant mean-reverting volatility". No such statistic exists.

**3.8 The VIX > 25 shock trigger.**
`VIXCLS` is fetched. Nothing applies a threshold to it, so regime 3's second
trigger condition is currently unreachable.

---

## 4. The taxonomies do not map, and the gap must be visible

QAT classifies **4** regimes on two binary axes (`below_trend` x
`elevated_volatility`). The document defines **7** on growth x volatility.

⚠️ **Four of the seven are not computable from anything QAT holds today** -
RECESSION, RECOVERY, SIDEWAYS, and the BEAR/RECESSION split.

**The matrix must REFUSE a regime whose inputs are absent rather than
approximate it**, and the narrative must say which inputs were missing. This
mirrors `compute_macro_signal` returning `None`, and it is the difference
between "we do not know" and a confident wrong answer.

---

## 5. Structural issues to settle before building

**5.1 The FRED series are US; the book is ASX.**
`VIXCLS`, `DGS10` and `BAA10Y` describe US conditions. This is already true
today, but the document leans far harder on macro to SET EXPOSURE, so a
US-derived regime driving an ASX exposure target is a claim to make deliberately
rather than inherit by accident.

**5.2 The `[Target]` weight must not auto-apply.**
`MACRO_REGIME_EXPOSURE_HINT` is deliberately NOT wired to
`RiskEngine.regime_scalar`, and the comment says why: *"having two independent
things write the same scalar would make the applied exposure impossible to
attribute to either."* The document's `[Target]` is exactly such a scalar.
`MacroAssessment.suggested_exposure_scalar` already models the right boundary -
proposal only, the operator decides.

**5.3 The disclaimer mandate collides with a decision already made.**
Constraints 6 and 7 require a compliance footnote on every output.
`workbench.py:649` records the opposite: *"a disclaimer printed on every result
stops being read."*

⚠️ **A resolution exists and should be preferred to picking a side.** The
Workbench pattern is a SELF-SUPPRESSING caveat: name the specific condition,
suppress when it does not apply. `ai_advisor.py` already carries a standing
framing label - *"Research only; not financial advice"* - so the screen is
covered once, permanently, and the per-output footnote can carry what is
specific to THIS reading instead of repeating boilerplate.

---

## 6. Phasing

**Phase 1 - deterministic inputs.** `HV`, `SB`, volatility rate-of-change,
spreads-distress and term-structure classifiers, VIX threshold. All pure
functions over existing data, unit-testable offline, no LLM involved.

**Phase 2 - the growth axis.** The genuine research task (section 3.3). Until it
lands, only the volatility-driven regimes are honestly computable: HIGH
VOLATILITY SHOCK, LOW VOLATILITY DRIFT, and degraded forms of BULL and BEAR.

**Phase 3 - the matrix and the arithmetic.** A pure function: inputs -> active
regime -> lift/cut -> target. Exact, testable, sabotage-checkable. Refuses
rather than approximates when an input is absent.

**Phase 4 - the narrative.** Replace `build_regime_narrative_prompt` with the
If/Then/Justification structure, handing the computed regime and target as facts
and forbidding recalculation. Extend the output schema to carry the regime, the
lift/cut and the target as structured fields, so the operator can see the
figures without parsing prose.

⚠️ Phases 1 and 3 are worth doing even if Phase 2 never happens: they replace
"unused FRED series" with a classified market state, which the existing
4-regime signal would also benefit from.

---

## 7. Open questions for the operator

1. **`SB = 0.20`** - accept, or derive it from something?
2. **`HV`** - measured over a long window, or a configured constant per market?
3. **The growth series** - which one, and for which economy? This decides 5.1.
4. **US macro driving ASX exposure** - deliberate, or a reason to seek AU series?
5. **Disclaimer** - adopt the self-suppressing pattern above, or follow the
   document's literal every-output footnote?
7. **Should `SB` actually CAP the change?** The mandate descriptions say it
   does; the source arithmetic says otherwise for four of the seven regimes (see
   section 8). Either clamp every regime to `+/- SB` - which changes the
   document's stated maths - or reword the mandates to describe what they
   really do. Doing neither leaves a setting whose description is wrong.

6. ~~**Does the target ever apply automatically?**~~ **ANSWERED 8 September:
   NO.** Operator decision: *"This sits outside of the authority of autonomy,
   resultant action must be human driven only for now."* The matrix computes and
   the operator acts; nothing this produces may reach `RiskEngine.regime_scalar`
   or any order path. This is now a constraint on the build, not a preference.

---

## 8. Progress

**Phase 1, `HV` - DONE, 8 September.** `MacroSignal.baseline_vol_annualized_pct`,
measured over 252 trading days, `None` when the history cannot support it and
never `0.0`.

⚠️ **The baseline EXCLUDES the realised window, and a test found that.** The
first version ended the baseline at the last bar, so the 20 days `RV` measures
sat inside `HV` too. A fixture of one calm year plus thirty violent days read
`HV = 24.67%` against a calm year of about 6%. The bias always runs one way -
RV rises and HV rises with it - so `((RV - HV) / HV)` understates the cut
exactly when a shock is under way and the matrix should be de-risking hardest.
`MIN_BARS_FOR_BASELINE_VOL` is therefore 273, not 253.

**Phase 1, `SB` - DONE, 8 September.** `Settings.macro_risk_mandate`, a named
mandate rather than a free float at the operator's direction:
conservative 0.10, moderate 0.20 (default), aggressive 0.35. An unrecognised
value is a startup error, never a silent fallback.

⚠️ **THE MANDATE DESCRIPTIONS PROMISE A CAP THE DOCUMENT'S MATH DOES NOT KEEP,
and Phase 3 must decide what to do about it.** Each mandate is described as
"caps the maximum exposure change at +/- SB". That holds only for the two LIFT
regimes, where `(HV - RV) / HV` cannot exceed 1 while RV is positive:

| Regime | Formula | Bounded by SB? |
|---|---|---|
| BULL, LOW VOL DRIFT | `((HV - RV) / HV) * SB` | yes |
| BEAR | `((RV - HV) / HV) * SB` | **NO - unbounded above.** RV at 3x HV gives 2 * SB |
| RECOVERY | `... * SB + 0.05` | **NO - exceeds SB by the kicker** |
| SHOCK | flat `0.10` | **NO - ignores SB** |
| RECESSION | `BM * 0.50` | **NO - ignores SB** |
| SIDEWAYS | `BM` | n/a, no change |

⚠️ On a moderate mandate a bear market with RV at three times HV computes a
**40% cut** where the setting's own description says 20%. Nothing clamps today.
**Phase 3 open question 7 (below) is whether it should.**

Remaining in Phase 1: volatility rate-of-change, the spreads-distress and
term-structure classifiers, and the VIX threshold.
