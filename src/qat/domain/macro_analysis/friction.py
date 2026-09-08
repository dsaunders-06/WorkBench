"""Where the two regime readings disagree, measured rather than noticed.

Two engines now classify the market and they will not always agree:

* the **HMM `RegimeEngine`** - probabilistic, six daily features, and the one
  that owns `RiskEngine.regime_scalar`. It is the only reading that moves money.
* the **7-regime matrix** - an explicit rule table over volatility and growth.
  Advisory by operator instruction, and slower by construction: its growth axis
  is quarterly and published in arrears.

⚠️ **THE DISAGREEMENT IS COMPUTED HERE, NOT OBSERVED BY THE MODEL.** The obvious
alternative is to hand both readings to the LLM and instruct it to flag any
mismatch. That is a request honoured probabilistically, and this codebase has
already ruled on the pattern - `data/news.py`: *"a model asked to be sceptical is
not a control"*. Detecting a mismatch is a comparison; comparisons belong in
code. The narrative is then handed a FACT it cannot fail to notice.

⚠️ **NOT AN ALPHA SIGNAL.** It is tempting to read divergence as an edge, and
that framing would quietly contradict the authority split: the matrix has no
mandate to move capital, so a signal worth trading could not be acted on through
it anyway. What divergence actually measures is CONFIDENCE. When a probabilistic
fit and a rule table disagree, the honest reading is that neither should be
leaned on hard, and a human should look closer.

⚠️ **BOTH SIDES SPEAK `domain.regime.Regime`**, so agreement is equality and
there is no mapping table to drift. That is deliberate: the matrix originally
carried its own seven-name taxonomy - "shock", "low_vol_drift" - and comparing
those to `high_vol` and `low_vol` by string would have reported disagreement
every time the two engines agreed. An alert that fires on a quiet market is
ignored within a week, and then the real divergence passes unread. This project
has removed two alarms with exactly that profile.
"""

from __future__ import annotations

from dataclasses import dataclass

from qat.domain.macro_analysis.matrix import (
    MATRIX_REGIME_DISPLAY,
    MatrixRefusal,
    RegimeDecision,
)
from qat.domain.regime import Regime


@dataclass(frozen=True, slots=True)
class RegimeFriction:
    """What the two engines each said, and whether they agree."""

    execution_regime: Regime
    """The HMM's label - the reading with monetary authority."""
    explanatory_regime: Regime
    """The matrix's label - auditable, rule-based, and lagging."""
    execution_scalar: float
    explanatory_target: float

    @property
    def agree(self) -> bool:
        return self.execution_regime == self.explanatory_regime

    @property
    def headline(self) -> str:
        """One line, front-loadable, naming both sides.

        ⚠️ Names the LAGGING side explicitly. The matrix explains itself and the
        HMM does not, and a reader given a clear story beside an opaque number
        will trust the story - which is backwards here, since the explained one
        is the slower and less validated of the two.
        """
        if self.agree:
            return f"Both readings agree: {MATRIX_REGIME_DISPLAY[self.execution_regime]}."
        return (
            f"FRICTION: the execution engine reads "
            f"{MATRIX_REGIME_DISPLAY[self.execution_regime]} (exposure scalar "
            f"{self.execution_scalar:.2f}) while the lagging rule-based explainer "
            f"reads {MATRIX_REGIME_DISPLAY[self.explanatory_regime]} (target "
            f"{self.explanatory_target:.1%}). They disagree, so neither reading "
            f"should be leaned on hard."
        )


def compare(
    execution_regime: Regime | None,
    execution_scalar: float | None,
    explanatory: RegimeDecision | MatrixRefusal | None,
) -> RegimeFriction | None:
    """The two readings side by side, or `None` when there is no comparison.

    ⚠️ `None` when EITHER side is absent, and that is not a failure. The HMM
    reports nothing until it has fitted; the matrix refuses whenever an input is
    missing, which today is always. Manufacturing an agreement out of one
    reading would be the fabricated-all-clear shape - a screen saying "the
    engines agree" when only one of them spoke.
    """
    if execution_regime is None or execution_scalar is None:
        return None
    if explanatory is None or isinstance(explanatory, MatrixRefusal):
        return None
    return RegimeFriction(
        execution_regime=execution_regime,
        explanatory_regime=explanatory.regime,
        execution_scalar=execution_scalar,
        explanatory_target=explanatory.target_weight,
    )
