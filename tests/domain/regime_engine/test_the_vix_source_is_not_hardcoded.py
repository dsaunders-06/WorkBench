"""Which VIX fills `vix_level` is a choice, and it used to be a constant.

`RegimeFeatureBuilder.update_macro` matched the literal string "VIXCLS" - the
CBOE VIX, a US measure - to fill the volatility column of the engine that sizes
an ASX book. `^AXVI`, the S&P/ASX 200 VIX, is the local equivalent and is free:
measured 8 September 2026, 129 daily closes with a last of 11.97. The proposed
`^AJOVIX` returns a 404; `^AXVI` is the ticker that exists.

⚠️ THIS IS THE EXECUTION LAYER, not the advisory one. `vix_level` led the raw
feature spread at 85.1% in today's live fit. The matrix is standardised before
hmmlearn sees it so that is not the bias it appears to be - but this column is
no minor input, and what fills it ends up sizing the book. The default therefore
does NOT move: naming the series is now possible, and choosing it is deliberate.

⚠️ AND NAMING IT IS NOT FEEDING IT. The column is filled from `MacroEvent`,
which the macro feed publishes from FRED alone; `^AXVI` is a Yahoo ticker. Until
a bridge exists, pointing this at it would leave the column at its default
forever - silently, which is the shape this project keeps finding. The test
below pins that the builder ignores a series it was not told to watch, so the
failure would at least be visible to anyone who looks.
"""

from __future__ import annotations

from qat.domain.regime_engine.feature_matrix import RegimeFeatureBuilder


def test_the_default_is_still_the_cboe_vix() -> None:
    """⚠️ Unchanged on purpose. A swap in the engine that sizes the book is the
    operator's call, not a side effect of making it possible."""
    builder = RegimeFeatureBuilder()

    assert builder.vix_series == "VIXCLS"

    builder.update_macro("VIXCLS", 14.3)
    assert builder._vix == 14.3


def test_the_source_can_be_pointed_at_the_asx_vix() -> None:
    builder = RegimeFeatureBuilder(vix_series="^AXVI")

    builder.update_macro("^AXVI", 11.97)

    assert builder._vix == 11.97


def test_the_previous_series_is_ignored_once_swapped() -> None:
    """⚠️ THE TEST THIS FILE EXISTS FOR. Accepting BOTH would let a US reading
    overwrite an Australian one depending on which arrived last - two feeds
    fighting over one column, with the winner decided by timing."""
    builder = RegimeFeatureBuilder(vix_series="^AXVI")

    builder.update_macro("^AXVI", 11.97)
    builder.update_macro("VIXCLS", 31.0)

    assert builder._vix == 11.97, "the old US series still wrote to the column"


def test_an_unfed_column_holds_its_default_rather_than_guessing() -> None:
    """⚠️ Pointing the setting at a series nothing publishes leaves this at
    zero. That is the failure mode of naming a Yahoo ticker before a bridge
    exists, and it is silent - the engine fits happily on a flat column."""
    builder = RegimeFeatureBuilder(vix_series="^AXVI")

    builder.update_macro("VIXCLS", 31.0)

    assert builder._vix == 0.0


def test_the_other_macro_columns_are_untouched_by_the_change() -> None:
    """The curve and credit columns keep their own series names."""
    builder = RegimeFeatureBuilder(vix_series="^AXVI")

    builder.update_macro("T10Y3M", 0.87)
    builder.update_macro("BAA10Y", 1.57)

    assert builder._yield_curve_slope == 0.87
    assert builder._credit_spread == 1.57
