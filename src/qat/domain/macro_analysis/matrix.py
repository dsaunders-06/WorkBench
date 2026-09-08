"""The 7-regime macro matrix: inputs in, one regime and one exposure target out.

Phase 3 of `docs/superpowers/specs/2026-09-08-macro-regime-matrix-design.md`.

⚠️ **DETERMINISTIC. THE MODEL WRITES PROSE, THIS DECIDES.** The source document
reads as one prompt asking a model to classify the regime AND compute
`Lift = ((HV - RV) / HV) * SB`. An LLM performing arithmetic that sets an
exposure target is the failure mode `ai_advisory/guards.py` exists for, and this
codebase already ruled on it - `MacroSignal`: *"every field is computed, never
modelled"*. Phase 4 hands the output below to the model as FACTS.

⚠️ **ADVISORY ONLY, AND THAT IS AN OPERATOR CONSTRAINT.** 8 September 2026:
*"This sits outside of the authority of autonomy, resultant action must be human
driven only for now."* Nothing here may reach `RiskEngine.regime_scalar`, the
sizer, or any order path. It computes; a person acts.

⚠️ **`SB` SCALES, IT DOES NOT CAP.** Operator definition: *"the baseline
multiplier used to scale exposure shifts. Total portfolio swings are dynamic and
can exceed this value during extreme market stress to ensure adequate downside
protection."* So NOTHING HERE CLAMPS TO `+/- SB`: a BEAR cut is unbounded above,
RECOVERY adds its 0.05 kicker on top, SHOCK is a flat 0.10 and RECESSION halves
the baseline outright. Reintroducing a clamp would be a regression, not a fix.

⚠️ **REFUSES RATHER THAN APPROXIMATES.** A regime whose inputs are absent is not
guessed at. All seven key on growth, so a session without a readable growth
series gets seven refusals rather than a default. Since 8 September the shipped
series is `CFNAIMA3`, labelled in settings as what it honestly is - a global
risk-appetite proxy, not Australian growth. The refusal NAMES what was missing,
so the reason is legible rather than a silent "sideways".
"""

from __future__ import annotations

from dataclasses import dataclass

from qat.domain.macro_analysis.growth import GrowthRead
from qat.domain.macro_analysis.signal import MacroSignal
from qat.domain.regime import Regime

# ⚠️ THE PROGRAM'S OWN `Regime`, NOT A PARALLEL ONE. The first version of this
# module declared its own seven-member Literal - "shock", "low_vol_drift" and
# five names identical to `domain/regime.py`'s. That was a second taxonomy for
# the same seven states, and it would have made every comparison against the HMM
# a string-mapping exercise: `low_vol` against `low_vol_drift` reads as
# disagreement when the two engines actually agree, and an alert that fires on
# every quiet market is ignored within a week.
#
# The document's seven ARE this program's seven. "High Volatility Shock" is
# HIGH_VOL and "Low Volatility Drift" is LOW_VOL; the rest match by name. Only
# the DISPLAY strings differ, and those are presentation.
MATRIX_REGIME_DISPLAY: dict[Regime, str] = {
    Regime.BULL: "Bull Market",
    Regime.BEAR: "Bear Market",
    Regime.HIGH_VOL: "High Volatility Shock",
    Regime.LOW_VOL: "Low Volatility Drift",
    Regime.RECESSION: "Recession",
    Regime.RECOVERY: "Recovery / Early Cycle",
    Regime.SIDEWAYS: "Sideways / Choppy",
}

# ⚠️ THE GROWTH BUCKETS LIVE WITH THE READER THAT KNOWS THE UNITS, not here.
# This module used to derive them from a year-on-year percentage with thresholds
# it invented (1.5% and 3.0%) - which works for a level series and is MEANINGLESS
# for an activity index, where zero already IS trend growth. `GrowthRead.bucket`
# now arrives decided, and choosing CFNAI-MA3 replaces those two invented
# numbers with the Chicago Fed's published bands.
#
# How far a shock's realised volatility must exceed the baseline to count as a
# SPIKE rather than merely elevated. The document writes it "RV >> HV".
_SHOCK_VOL_MULTIPLE = 1.5
# The document's own flat reductions.
_SHOCK_REDUCTION = 0.10
_RECOVERY_KICKER = 0.05
_RECESSION_MULTIPLIER = 0.50

# How old a growth reading may be and still describe the present.
#
# ⚠️ RAISED IN REVIEW, 8 September: `GrowthRead.age_days` existed and nothing
# consulted it. With quarterly GDP a RECESSION call could be computed from data
# five months old and rendered as "the economy is contracting, cut to 42.5%"
# while the market had already turned - confident advice about the last war.
#
# 200 days, and the arithmetic matters: Australian GDP for a quarter ending
# 30 June is published near the end of August, so a reading is ROUTINELY 60-155
# days old with nothing wrong. Set tighter than that and the matrix refuses
# every day of a normal quarter and never speaks at all. This catches a series
# that has genuinely stalled, not one between publications.
MAX_GROWTH_AGE_DAYS = 200


def baseline_from_risk_budget(gap_budget_pct: float, gap_shock_pct: float) -> float:
    """`BM` - the exposure the deterministic rails alone justify holding.

    ⚠️ `decide` REFUSES TO DEFAULT THIS, and its docstring says why: the default
    used to be `MacroSignal.exposure_hint`, which is the FOUR-regime read's
    answer, so the matrix could report a Bull market while lifting from a
    baseline the other classifier had set because it saw Risk-Off. Two
    taxonomies stacked, silently. The caller must therefore state `BM`, and this
    is where it comes from: the account's own gap-risk budget, which owes
    nothing to any regime classifier.

    The arithmetic is already spelled out in `config.py` beside
    `max_gap_risk_at_shock_pct` - a 5% gap budget against a 6% gap shock
    "implies a gross-exposure ceiling of about 83% of equity". Derived rather
    than typed in, so an operator who halves the budget has halved what the
    matrix lifts from.

    ⚠️ THE CLAMP IS ON `BM` AND ONLY ON `BM`. The matrix's TARGET is unclamped
    by deliberate design - a lift may carry it past 100% and `implies_leverage`
    surfaces that rather than trimming it. But the thing being lifted FROM is
    fully invested at most: a budget implying a 167% normal state is not a
    baseline.
    """
    if gap_shock_pct <= 0.0:
        raise ValueError("gap shock must be positive - a baseline cannot divide by it otherwise")
    if gap_budget_pct < 0.0:
        raise ValueError("gap budget cannot be negative")
    return min(1.0, gap_budget_pct / gap_shock_pct)


@dataclass(frozen=True, slots=True)
class RegimeDecision:
    """One regime, and the arithmetic that produced its target."""

    regime: Regime
    baseline: float
    """`BM` - the exposure the deterministic read alone justifies."""
    scaling_unit: float
    """`SB` - the risk scaling unit from the account's mandate."""
    change: float
    """Signed. Positive lifts, negative cuts, zero holds."""
    target_weight: float
    reasons: tuple[str, ...]

    @property
    def display_regime(self) -> str:
        return MATRIX_REGIME_DISPLAY[self.regime]

    @property
    def implies_leverage(self) -> bool:
        """⚠️ Surfaced, not clamped. A lift can carry the target above 100%, and
        for a mandate that permits leverage that is the intended answer. The
        operator should see it rather than have it quietly trimmed."""
        return self.target_weight > 1.0


@dataclass(frozen=True, slots=True)
class MatrixRefusal:
    """No regime, and exactly why.

    ⚠️ A refusal is an ANSWER, not a failure. "We cannot tell" is different from
    "sideways", and collapsing the first into the second is how a matrix reports
    calm it never measured.
    """

    missing: tuple[str, ...]

    @property
    def detail(self) -> str:
        return (
            "No regime could be identified: "
            + ", ".join(self.missing)
            + ". Refused rather than approximated - an unmeasured input is not a "
            "neutral one."
        )


def decide(
    signal: MacroSignal,
    growth: GrowthRead | None,
    *,
    scaling_unit: float,
    baseline: float,
) -> RegimeDecision | MatrixRefusal:
    """The single dominant active regime, and its exposure target.

    ⚠️ `baseline` IS REQUIRED, and used to default to `MacroSignal.exposure_hint`.
    That figure is the FOUR-regime read's answer, so defaulting to it stacked two
    taxonomies silently: this matrix could report a Bull market while lifting
    from a 0.30 baseline the other classifier set because it saw Risk-Off. The
    caller now states what `BM` is, and the decision reports it back.

    ⚠️ ORDER IS PRECEDENCE, and the most severe wins. A market can satisfy
    several rows at once - a recession is also a bear market - and the document
    asks for "the single dominant active regime". Reporting the milder of two
    true readings would understate exactly when it matters.
    """
    # ⚠️ ONE COMBINED GUARD, so the types NARROW without an `assert`. The first
    # version used two asserts to satisfy mypy, and bandit was right to refuse
    # them (B101): `assert` is stripped under `python -O`, and these two guard
    # the values every formula below DIVIDES BY. A guard that disappears under
    # an optimisation flag is not a guard.
    stale = growth is not None and growth.age_days > MAX_GROWTH_AGE_DAYS
    if growth is None or signal.baseline_vol_annualized_pct is None or stale:
        missing: list[str] = []
        if growth is None:
            missing.append(
                "no growth reading (set QAT_MACRO_GROWTH_SERIES - every regime keys on growth)"
            )
        elif stale:
            # ⚠️ Named with the measured age, so the operator can tell a stalled
            # series from one merely between publications.
            missing.append(
                f"the growth reading is {growth.age_days} days old, past the "
                f"{MAX_GROWTH_AGE_DAYS}-day limit - too stale to describe the present"
            )
        if signal.baseline_vol_annualized_pct is None:
            missing.append("no baseline volatility HV (not enough history)")
        return MatrixRefusal(missing=tuple(missing))

    hv = signal.baseline_vol_annualized_pct
    rv = signal.realized_vol_annualized_pct
    bm = baseline
    bucket = growth.bucket
    reasons = [
        # ⚠️ The reading in ITS OWN units. This module cannot format a number
        # whose units it does not know, and must not try.
        f"growth {growth.summary} ({bucket})",
        f"RV {rv:.1f}% vs HV {hv:.1f}%",
    ]

    # 5. RECESSION - the most severe row, so it is tested first.
    if bucket == "negative" and signal.spreads == "distressed" and rv >= hv:
        reasons.append("credit spreads distressed")
        target = bm * _RECESSION_MULTIPLIER
        return RegimeDecision(
            regime=Regime.RECESSION,
            baseline=bm,
            scaling_unit=scaling_unit,
            change=target - bm,
            target_weight=target,
            reasons=tuple(reasons),
        )

    # 3. HIGH VOLATILITY SHOCK - a flat de-risk on a spike.
    #
    # ⚠️ REQUIRES NON-NEGATIVE GROWTH, and the tests found that this was missed.
    # The document's row reads "Normal Growth + Sudden Vol Spike": a spike
    # arriving on top of a CONTRACTING economy is a bear market or a recession,
    # and those rows respond far harder than a flat 10%. Firing shock on any
    # spike regardless of growth quietly downgraded both - RV at three times HV
    # with negative growth returned a 10% trim where the bear row asks for 40%.
    if bucket != "negative" and (signal.vix_shock or rv >= hv * _SHOCK_VOL_MULTIPLE):
        reasons.append("VIX above the shock level" if signal.vix_shock else "RV far above HV")
        target = bm - _SHOCK_REDUCTION
        return RegimeDecision(
            regime=Regime.HIGH_VOL,
            baseline=bm,
            scaling_unit=scaling_unit,
            change=-_SHOCK_REDUCTION,
            target_weight=max(0.0, target),
            reasons=tuple(reasons),
        )

    # 2. BEAR.
    if bucket == "negative" and rv >= hv:
        cut = ((rv - hv) / hv) * scaling_unit
        return RegimeDecision(
            regime=Regime.BEAR,
            baseline=bm,
            scaling_unit=scaling_unit,
            change=-cut,
            # ⚠️ Floored at zero per the document, and NOT capped at SB - the
            # cut is unbounded above by design.
            target_weight=max(0.0, bm - cut),
            reasons=tuple(reasons),
        )

    # 6. RECOVERY - accelerating growth as volatility subsides.
    if growth.direction == "accelerating" and signal.vol_direction == "falling" and rv < hv:
        reasons.append("growth accelerating as volatility subsides")
        lift = ((hv - rv) / hv) * scaling_unit + _RECOVERY_KICKER
        return RegimeDecision(
            regime=Regime.RECOVERY,
            baseline=bm,
            scaling_unit=scaling_unit,
            change=lift,
            target_weight=bm + lift,
            reasons=tuple(reasons),
        )

    # 1. BULL.
    if bucket == "high" and rv < hv:
        lift = ((hv - rv) / hv) * scaling_unit
        return RegimeDecision(
            regime=Regime.BULL,
            baseline=bm,
            scaling_unit=scaling_unit,
            change=lift,
            target_weight=bm + lift,
            reasons=tuple(reasons),
        )

    # 4. LOW VOLATILITY DRIFT - half the lift, for quiet but unexciting growth.
    if bucket in ("low", "normal") and rv < hv:
        lift = ((hv - rv) / hv) * scaling_unit * 0.5
        return RegimeDecision(
            regime=Regime.LOW_VOL,
            baseline=bm,
            scaling_unit=scaling_unit,
            change=lift,
            target_weight=bm + lift,
            reasons=tuple(reasons),
        )

    # 7. SIDEWAYS - the remainder, and it holds. ⚠️ Reached only when the rows
    # above did not match, never as a stand-in for an input nobody measured;
    # that case returned a refusal at the top.
    return RegimeDecision(
        regime=Regime.SIDEWAYS,
        baseline=bm,
        scaling_unit=scaling_unit,
        change=0.0,
        target_weight=bm,
        reasons=tuple(reasons),
    )


class RegimeHysteresis:
    """Holds the reported regime until a challenger persists.

    ⚠️ RAISED IN REVIEW, 8 September: the matrix selects a discrete regime from
    CONTINUOUS inputs, so a value sitting on a boundary flips it every reading.
    RV oscillating either side of HV alternates BULL and BEAR; spreads at 3.49
    against 3.51 alternates BEAR and RECESSION, which is a scaled cut against
    HALVING THE BOOK. Day-to-day flapping would produce contradictory advice out
    of noise alone.

    ⚠️ `RegimeEngine` already solved this - `fusion.HysteresisGate` - and that
    one cannot be reused: it compares PROBABILITIES with a margin, and this
    matrix emits a discrete label with none. Persistence is the equivalent that
    fits a hard classifier.

    ⚠️ STATEFUL BY NECESSITY, AND SEPARATE ON PURPOSE. `decide` stays a pure
    function - same inputs, same answer, always - which is what makes it
    testable and auditable. Smoothing is a presentation concern and lives here.

    ⚠️ A REFUSAL IS NOT A CHALLENGER. Missing inputs must surface immediately;
    holding the last good regime over them would report a market nobody
    measured, which is the fabricated-all-clear shape this codebase keeps
    finding.
    """

    def __init__(self, min_persistence: int = 3) -> None:
        self.min_persistence = min_persistence
        self._current: Regime | None = None
        self._challenger: Regime | None = None
        self._streak = 0

    @property
    def current(self) -> Regime | None:
        return self._current

    def settle(self, result: RegimeDecision | MatrixRefusal) -> RegimeDecision | MatrixRefusal:
        """The decision to report, with its regime smoothed.

        A held decision keeps the CURRENT regime's name but the LATEST
        arithmetic, so the figures on screen still describe today's market.
        """
        if isinstance(result, MatrixRefusal):
            # Passed straight through, and the streak is dropped: a gap in the
            # inputs is not evidence for the challenger.
            self._challenger, self._streak = None, 0
            return result

        if self._current is None or result.regime == self._current:
            self._current = result.regime
            self._challenger, self._streak = None, 0
            return result

        if result.regime == self._challenger:
            self._streak += 1
        else:
            self._challenger, self._streak = result.regime, 1

        if self._streak >= self.min_persistence:
            self._current = result.regime
            self._challenger, self._streak = None, 0
            return result

        held = self._current
        return RegimeDecision(
            regime=held,
            baseline=result.baseline,
            scaling_unit=result.scaling_unit,
            change=result.change,
            target_weight=result.target_weight,
            reasons=result.reasons
            + (
                f"holding {MATRIX_REGIME_DISPLAY[held]} - "
                f"{MATRIX_REGIME_DISPLAY[result.regime]} has persisted "
                f"{self._streak} of {self.min_persistence} readings",
            ),
        )
