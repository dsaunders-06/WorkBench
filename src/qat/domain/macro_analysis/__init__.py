"""Macro market-conditions analysis (spec M13).

Two layers, deliberately separated:

* signal.py computes a *deterministic* read on market conditions from the
  benchmark's own bars - realized volatility, position relative to trend,
  drawdown from a recent high. Pure arithmetic, no LLM, always available.
* The AI layer (domain/ai_advisory) synthesises on top of that number, adding
  the qualitative reading a formula genuinely cannot do.

The split is the point: a formula either fires or it does not, so the
quantitative part of the regime read can never depend on a model's mood. See
AIAdvisoryService.get_macro_assessment.
"""

from qat.domain.macro_analysis.signal import (
    MACRO_REGIMES,
    MacroSignal,
    compute_macro_signal,
)

__all__ = ["MACRO_REGIMES", "MacroSignal", "compute_macro_signal"]
