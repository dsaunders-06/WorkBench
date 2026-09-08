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
guessed at. Today that means EVERY regime is refused, because
`Settings.macro_growth_series` ships empty and all seven key on growth - see the
spec's section 4. The refusal NAMES what was missing, so the reason is legible
rather than a silent "sideways".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from qat.domain.macro_analysis.growth import GrowthRead
from qat.domain.macro_analysis.signal import MacroSignal

MatrixRegime = Literal[
    "bull",
    "bear",
    "shock",
    "low_vol_drift",
    "recession",
    "recovery",
    "sideways",
]

MATRIX_REGIME_DISPLAY: dict[str, str] = {
    "bull": "Bull Market",
    "bear": "Bear Market",
    "shock": "High Volatility Shock",
    "low_vol_drift": "Low Volatility Drift",
    "recession": "Recession",
    "recovery": "Recovery / Early Cycle",
    "sideways": "Sideways / Choppy",
}

# ⚠️ CONVENTIONAL, NOT MEASURED - the same caveat Phase 1 and 2's thresholds
# carry, and the same reason they are named: so they can be argued with. Year-on
# -year real growth, in per cent.
_GROWTH_LOW_PCT = 1.5
_GROWTH_HIGH_PCT = 3.0
# How far a shock's realised volatility must exceed the baseline to count as a
# SPIKE rather than merely elevated. The document writes it "RV >> HV".
_SHOCK_VOL_MULTIPLE = 1.5
# The document's own flat reductions.
_SHOCK_REDUCTION = 0.10
_RECOVERY_KICKER = 0.05
_RECESSION_MULTIPLIER = 0.50


@dataclass(frozen=True, slots=True)
class RegimeDecision:
    """One regime, and the arithmetic that produced its target."""

    regime: MatrixRegime
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


def _growth_bucket(yoy_pct: float) -> Literal["negative", "low", "normal", "high"]:
    if yoy_pct < 0.0:
        return "negative"
    if yoy_pct < _GROWTH_LOW_PCT:
        return "low"
    if yoy_pct < _GROWTH_HIGH_PCT:
        return "normal"
    return "high"


def decide(
    signal: MacroSignal,
    growth: GrowthRead | None,
    *,
    scaling_unit: float,
    baseline: float | None = None,
) -> RegimeDecision | MatrixRefusal:
    """The single dominant active regime, and its exposure target.

    `baseline` defaults to the deterministic read's own exposure hint (`BM`).

    ⚠️ ORDER IS PRECEDENCE, and the most severe wins. A market can satisfy
    several rows at once - a recession is also a bear market - and the document
    asks for "the single dominant active regime". Reporting the milder of two
    true readings would understate exactly when it matters.
    """
    missing: list[str] = []
    if growth is None:
        missing.append(
            "no growth reading (set QAT_MACRO_GROWTH_SERIES - every regime keys on growth)"
        )
    if signal.baseline_vol_annualized_pct is None:
        missing.append("no baseline volatility HV (not enough history)")
    if missing:
        return MatrixRefusal(missing=tuple(missing))

    assert growth is not None
    hv = signal.baseline_vol_annualized_pct
    assert hv is not None
    rv = signal.realized_vol_annualized_pct
    bm = signal.exposure_hint if baseline is None else baseline
    bucket = _growth_bucket(growth.yoy_pct)
    reasons = [
        f"growth {growth.yoy_pct:+.1f}% y/y ({bucket})",
        f"RV {rv:.1f}% vs HV {hv:.1f}%",
    ]

    # 5. RECESSION - the most severe row, so it is tested first.
    if bucket == "negative" and signal.spreads == "distressed" and rv >= hv:
        reasons.append("credit spreads distressed")
        target = bm * _RECESSION_MULTIPLIER
        return RegimeDecision(
            regime="recession",
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
            regime="shock",
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
            regime="bear",
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
            regime="recovery",
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
            regime="bull",
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
            regime="low_vol_drift",
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
        regime="sideways",
        baseline=bm,
        scaling_unit=scaling_unit,
        change=0.0,
        target_weight=bm,
        reasons=tuple(reasons),
    )
