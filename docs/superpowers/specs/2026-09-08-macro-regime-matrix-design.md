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
3. ~~**The growth series**~~ **ANSWERED 8 September: `CFNAIMA3`**, the Chicago
   Fed National Activity Index (three-month average), read by
   `classify_activity_index` against the Chicago Fed's OWN bands - which retires
   two thresholds this project had invented rather than adding a third. A
   quarterly print was rejected: the matrix sits beside a daily engine and a
   figure published a quarter in arrears is blind to a turn.
4. ~~**US macro driving ASX exposure**~~ **ANSWERED 8 September: DELIBERATE,
   AND LABELLED.** The growth axis is a GLOBAL RISK-APPETITE proxy, not
   Australian growth, and every surface says so. Measured before choosing:
   AU real GDP (`NGDPRSAXDCAUQ`) is quarterly and was 160 days old; `AUSRECDM`
   has not updated since July 2022; ABS and Melbourne Institute releases are not
   on FRED. A timely global proxy named as one beats a domestic figure too stale
   to describe the present.
   ⚠️ **The localisation that IS worth doing is `^AXVI`** - the S&P/ASX 200 VIX,
   129 daily closes and free. `RegimeFeatureBuilder.vix_series` is configurable
   for it now; the bridge from the daily-bar source into `MacroEvent` is the
   remaining work, because the macro feed publishes FRED only.
   ⚠️ **Not worth doing: localising the curve and credit inputs.** The AU
   equivalents on FRED are MONTHLY and were stale to 1 June, against the daily
   US series they would replace - the swap would make the execution engine
   slower, not more local.
5. **Disclaimer** - adopt the self-suppressing pattern above, or follow the
   document's literal every-output footnote?
8. ~~**Are the Phase 1 thresholds right?**~~ **ANSWERED 8 September: two were
   wrong, three were fine, and one was a hidden switch.** Measured against FRED
   and ^AXJO history rather than argued about:

   | threshold | was | measured | now |
   |---|---|---|---|
   | flat-curve ceiling | 0.5 | 14.2nd pct of upward-sloping US curves; calls 22.3% of AU history flat vs 12.0% of US | **caller's argument**; US 0.50, AU 0.215 recorded |
   | spreads widening | 2.5 | 68.5th pct - true on 31.5% of all days since 1986 | **3.0** (87.4th, 12.6%) |
   | spreads distressed | 3.5 | 97.1st pct; 2.9% of days, 28.5% of GFC, 6.8% of COVID, 0.0% of 2024-26 | unchanged - it earns it |
   | RV/HV shock multiple | 1.5 | 90.5th pct of ^AXJO RV20/HV252 (9.5% of days) | unchanged |
   | VIX shock level | 25.0 | 82.7nd pct of VIXCLS (17.3% of days) | unchanged, now **per-series** |
   | vol-direction tolerance | 0.15 | median move is 0.219, so it called 64.5% of days a TREND | **0.25** (54.9% steady) |
   | index-direction tolerance | 0.10 | median monthly CFNAI move is 0.110 | unchanged |

   The spread bands do decide BEAR versus RECESSION, and the measurement
   vindicated the one that matters: `distressed` at 3.5 is rare and present in
   genuine credit crises. `widening` was the weather.

   ⚠️ **THE HIDDEN SWITCH.** `compute_macro_signal` looked up `"VIXCLS"` by a
   hardcoded literal while `RegimeFeatureBuilder.vix_series` had been made
   configurable. Pointing this application's VIX at `^AXVI` would have moved
   the regime engine's column and stranded this reading on a series nobody
   published - `vix_shock` `None` for the session, which removes the SHOCK row
   rather than reporting a calm market. Both the series and its level are now
   settings, and pre-flight warns when one moves without the other.

   ⚠️ **NO AUSTRALIAN SHOCK LEVEL IS OFFERED.** ^AXVI reaches 25.0 on 0.2% of
   ASX days, so the American figure cannot travel - but the percentile
   translation (13.13) comes from two years containing no crisis, and a stress
   threshold calibrated on a sample with no stress in it is worse than none.
   What is needed is a longer ^AXVI history than Yahoo serves.

7. ~~**Should `SB` actually CAP the change?**~~ **ANSWERED 8 September: NO.**
   `SB` is redefined as the Risk Scaling Unit - responsiveness, not a
   boundary - and swings may exceed it under stress by design. The maths stands
   as the source document writes it; the description and the constant names
   changed instead.

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

⚠️ **`SB` IS A SCALING UNIT, NOT A CAP - RESOLVED 8 September.** The mandates
were first described as "caps the maximum exposure change at +/- SB", and the
arithmetic never kept that promise. The operator's correction redefines the
variable rather than changing the maths:

> *"Risk Scaling Unit: the baseline multiplier used to scale exposure
> shifts. Total portfolio swings are dynamic and can exceed this value during
> extreme market stress to ensure adequate downside protection."*

So exceeding `SB` is INTENDED, not a defect - a downside response that stopped at
the unit would under-protect in exactly the conditions it exists for. The table
below records where that happens, and it is behaviour to preserve rather than
clamp:

| Regime | Formula | Bounded by SB? |
|---|---|---|
| BULL, LOW VOL DRIFT | `((HV - RV) / HV) * SB` | yes |
| BEAR | `((RV - HV) / HV) * SB` | **NO - unbounded above.** RV at 3x HV gives 2 * SB |
| RECOVERY | `... * SB + 0.05` | **NO - exceeds SB by the kicker** |
| SHOCK | flat `0.10` | **NO - ignores SB** |
| RECESSION | `BM * 0.50` | **NO - ignores SB** |
| SIDEWAYS | `BM` | n/a, no change |

On a moderate mandate a bear market with RV at three times HV computes a **40%
cut**. That is the intended dynamic response. ⚠️ **Phase 3 must NOT clamp**, and
must not reintroduce the word "cap" anywhere near `SB`: the constants were
renamed from `MANDATE_SAFETY_BUFFER` / `safety_buffer_for` to
`MANDATE_SCALING_UNIT` / `scaling_unit_for` precisely because a name carrying
"buffer" re-teaches the misconception to every later reader.

**Phase 1 COMPLETE, 8 September.** The remaining four landed together, all on
`MacroSignal`:

| Field | Source | Serves |
|---|---|---|
| `vol_direction` | RV this window vs the one before | RECOVERY's "subsiding volatility" |
| `vix_shock` | `VIXCLS > 25` | SHOCK's second trigger |
| `term_structure` | `T10Y3M` -> normal / flat / inverted | the document's named input |
| `spreads` | `BAA10Y` -> normal / widening / distressed | **the BEAR/RECESSION split** |

`VIXCLS`, `T10Y3M` and `BAA10Y` had been fetched every session and read by
nothing. Volatility DIRECTION was never computed at all - and a level alone
cannot tell a market coming out of a shock from one going into it.

⚠️ **ABSENT IS `None`, NEVER A DEFAULT, in all four.** A missing series must not
read as a normal curve, calm spreads or a quiet market - `vix_shock` is `None`
rather than `False` because `False` claims the market was checked. This is what
lets Phase 3 REFUSE a regime instead of approximating it.

⚠️ **THE THRESHOLDS ARE CONVENTIONAL, NOT MEASURED, and this is open.** An
inverted curve below zero is definitional. The flat ceiling (0.5), the spread
bands (2.5 widening, 3.5 distressed) and the direction tolerance (15%) are
judgement calls from common usage, NOT validated against this account's history.
They are named constants so they can be argued with. **Open question 8 below.**

**Phase 2, the growth axis - MACHINERY DONE, SERIES UNCHOSEN, 8 September.**
`domain/macro_analysis/growth.py`: `classify_growth(observations)` over any FRED
history, returning year-on-year growth, its direction (accelerating / flattening
/ decelerating) and how old the reading is.

⚠️ **FROM A LEVEL, NOT A RATE.** `GDPC1` and `INDPRO` are index levels. Reading
one straight off would report "growth" of 22,000; the year-on-year change is what
the matrix's growth axis means.

⚠️ **`Settings.macro_growth_series` SHIPS EMPTY, AND THAT IS THE POINT.** Naming
a default would silently answer open question 3 - and with it question 4, since
choosing a series chooses an economy and every FRED series polled today is US
while the book is ASX. Until one is named there is no growth axis and Phase 3
refuses the regimes that need one. **The remaining work of Phase 2 is a decision,
not code.**

⚠️ **EVERY CANDIDATE IS LAGGED.** Real GDP is quarterly and published a month or
more after the quarter closes; Australian GDP later still - five months stale is
achievable. `GrowthRead.age_days` carries that so Phase 3 can judge it. The
module deliberately does NOT refuse on age: what counts as too stale depends on
the series, and inventing a limit before the series exists is guessing twice.

Candidates, with the trade-off that matters:

| Series | Economy | Frequency | Practical lag |
|---|---|---|---|
| `GDPC1` | US | quarterly | ~1 month after quarter end |
| `INDPRO` | US | monthly | ~2 weeks - timelier, narrower |
| `GDPNOW` | US | ~weekly | current, but a model estimate |
| AU real GDP | Australia | quarterly | ~2 months after quarter end |

⚠️ Note that `T10Y3M` - already polled, already classified in Phase 1 - is itself
a conventional recession signal. Using it as the growth axis too would make one
input drive two axes of the matrix, which is double-counting rather than
corroboration. Recorded so it is not done by accident.

**Phase 3, the matrix - DONE, 8 September.**
`domain/macro_analysis/matrix.py`: `decide(signal, growth, scaling_unit,
baseline)` returns either a `RegimeDecision` - one regime, the signed change,
the target and the figures behind it - or a `MatrixRefusal` naming what was
missing.

⚠️ **ALL SEVEN ROWS ARE BUILT, AND ALL SEVEN REFUSE TODAY.** An earlier note
here said the volatility-driven regimes could be built without the growth
series. That was wrong: EVERY row in the document carries a growth condition,
including SHOCK ("Normal Growth + Sudden Vol Spike"). So the matrix is complete
and returns a refusal until `QAT_MACRO_GROWTH_SERIES` is set. The tests supply
growth directly, so every row is exercised.

⚠️ **A REFUSAL IS AN ANSWER.** "We cannot tell" is not "sideways", and
collapsing the first into the second is how a matrix reports calm it never
measured. The refusal names each missing input.

⚠️ **THE TESTS FOUND A PRECEDENCE ERROR.** SHOCK was firing on any volatility
spike regardless of growth, so a spike on a CONTRACTING economy returned a flat
10% trim where the BEAR row asks for 40% and RECESSION for 50%. SHOCK now
requires non-negative growth, matching the document's own "Normal Growth"
condition. Precedence is severity-first: recession, shock, bear, recovery, bull,
low-vol drift, sideways.

⚠️ **NOTHING CLAMPS TO `+/- SB`**, and a test asserts the bear cut exceeds it.
Re-imposing a clamp would be a regression, not a fix - see the `SB` redefinition
above. A target above 100% is surfaced via `implies_leverage` rather than
trimmed.

More conventional-not-measured thresholds, added to open question 8: the growth
buckets (low 1.5%, high 3.0%) and the shock multiple (RV >= 1.5x HV).

**Phase 4, the narrative - DONE, 8 September.** `build_macro_matrix_prompt`
plus `MacroMatrixNarrative`. The model receives the regime, the change and the
target as FACTS and is told in terms that the arithmetic is "NOT YOURS TO REDO"
and must be copied "EXACTLY as given". `change_pct` and `target_pct` are
structured fields so the caller can compare what came back against what it
sent - a model that quietly disagreed is caught, not believed.

A REFUSAL renders as a refusal: the prompt says do not guess, do not describe
the market as calm or sideways, and do not suggest an exposure change.

Condition-specific caveats only. Following `workbench.py`'s "a disclaimer
printed on every result stops being read", the standing "research only, not
financial advice" framing stays on the screen and the per-reading caveats carry
what is true of THIS reading - a stale growth series, a held regime, a target
implying leverage.

⚠️ **NOT YET WIRED TO A SCREEN.** Nothing calls `build_macro_matrix_prompt`
yet, so none of this has run against a live model. That is the remaining work,
and it is small - but "tested" here means unit-tested, not exercised.

**All four phases are built. What remains is a DECISION (the growth series) and
one integration (a screen).**
