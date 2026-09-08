"""Disagreement between the two engines, computed rather than noticed.

⚠️ THE COMPARISON IS CODE, NOT A PROMPT INSTRUCTION. The obvious alternative -
hand both readings to the model and tell it to flag a mismatch - is a request
honoured probabilistically. `data/news.py` already recorded the rule: *"a model
asked to be sceptical is not a control"*. So the mismatch is a computed fact the
narrative cannot fail to notice.

⚠️ NOT AN ALPHA SIGNAL, and the naming matters. Divergence reads as an edge only
if you forget that the explanatory engine has no mandate to move capital - a
signal worth trading could not be acted on through it. What it measures is
CONFIDENCE: when a probabilistic fit and a rule table disagree, lean on neither.

⚠️ AND BOTH SIDES SPEAK THE SAME `Regime`. The matrix first carried its own
taxonomy - "shock", "low_vol_drift" - and comparing those against `high_vol` and
`low_vol` by string would have reported friction every time the engines AGREED.
An alert that fires on a quiet market is ignored within a week; this project has
removed two alarms with exactly that profile.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qat.domain.macro_analysis.friction import compare
from qat.domain.macro_analysis.growth import GrowthRead
from qat.domain.macro_analysis.matrix import decide
from qat.domain.macro_analysis.signal import MacroSignal
from qat.domain.regime import Regime

_SB = 0.20


def _signal(rv: float = 8.74, hv: float | None = 15.0, vix_shock: bool | None = False):
    return MacroSignal(
        realized_vol_annualized_pct=rv,
        vol_direction="steady",
        vix_shock=vix_shock,
        term_structure="normal",
        spreads="normal",
        baseline_vol_annualized_pct=hv,
        pct_above_trend=1.0,
        drawdown_from_recent_high_pct=1.0,
        suggested_regime="neutral",
        elevated_volatility=False,
        below_trend=False,
    )


def _bucket(yoy: float) -> str:
    """Mirrors `classify_growth`'s own bucketing, so a fixture's yoy value still
    implies the regime the test is reasoning about."""
    if yoy < 0.0:
        return "negative"
    if yoy < 1.5:
        return "low"
    if yoy < 3.0:
        return "normal"
    return "high"


def _growth(yoy: float = 4.0):
    return GrowthRead(
        series="GDPC1",
        bucket=_bucket(yoy),  # type: ignore[arg-type]
        summary=f"{yoy:+.1f}% y/y",
        yoy_pct=yoy,
        direction="flattening",
        as_of=datetime(2026, 6, 30, tzinfo=UTC),
        age_days=70,
    )


def _matrix(rv: float = 8.74, yoy: float = 4.0, vix_shock: bool | None = False):
    return decide(
        _signal(rv=rv, vix_shock=vix_shock), _growth(yoy), scaling_unit=_SB, baseline=0.85
    )


def test_matching_regimes_report_agreement() -> None:
    friction = compare(Regime.BULL, 1.0, _matrix())

    assert friction is not None
    assert friction.agree is True
    assert "agree" in friction.headline


def test_the_same_market_state_under_two_names_is_NOT_friction() -> None:
    """⚠️ THE FALSE-ALARM THIS FILE EXISTS TO PREVENT. The matrix calls it
    "Low Volatility Drift" and the HMM calls it `low_vol`. They are the SAME
    regime, and a string comparison of the display names would have reported
    disagreement on every quiet day."""
    quiet = _matrix(rv=8.74, yoy=1.0)

    friction = compare(Regime.LOW_VOL, 1.0, quiet)

    assert friction is not None
    assert friction.agree is True, "one market state read as two disagreeing regimes"


def test_a_volatility_shock_matches_the_engines_high_vol() -> None:
    """The other renamed pair: "High Volatility Shock" is `high_vol`."""
    shocked = _matrix(rv=12.0, yoy=2.0, vix_shock=True)

    friction = compare(Regime.HIGH_VOL, 0.4, shocked)

    assert friction is not None
    assert friction.agree is True


def test_a_genuine_divergence_is_reported() -> None:
    """The case the alert exists for: the fast engine has turned and the
    lagging one has not."""
    friction = compare(Regime.BEAR, 0.5, _matrix(rv=8.74, yoy=4.0))

    assert friction is not None
    assert friction.agree is False
    assert "FRICTION" in friction.headline


def test_the_headline_names_which_side_lags_and_which_moves_money() -> None:
    """⚠️ The matrix explains itself and the HMM does not. A reader given a
    clear story beside an opaque number trusts the story - backwards here, since
    the explained one is the slower and less validated of the two."""
    friction = compare(Regime.BEAR, 0.5, _matrix())

    assert friction is not None
    assert "execution engine" in friction.headline
    assert "lagging rule-based explainer" in friction.headline
    assert "0.50" in friction.headline


def test_a_refused_matrix_yields_no_comparison() -> None:
    """⚠️ Today's actual state. Manufacturing an agreement out of ONE reading
    would put "the engines agree" on screen when only one of them spoke."""
    refusal = decide(_signal(), None, scaling_unit=_SB, baseline=0.85)

    assert compare(Regime.BULL, 1.0, refusal) is None


def test_an_unfitted_execution_engine_yields_no_comparison() -> None:
    """The HMM reports nothing until it has fitted, and silence is not a vote."""
    assert compare(None, None, _matrix()) is None
    assert compare(Regime.BULL, None, _matrix()) is None
