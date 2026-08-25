"""The equity chart's x-axis must describe what it is actually plotting (item 39).

Observed 25 August: ticks reading `00.550, 00.600 ... 01.450` under an axis
labelled "Date (synthetic daily bars)".

The cause is a half-done fallback. `equity_plot` is always built with a
`pg.DateAxisItem`, and when `_epoch_seconds` returns None - no usable date
index - the code correctly falls back to plotting against the BAR INDEX, but
leaves the date axis and the "Date" label in place. A date axis handed the
integers 0 and 1 renders them as fractional decimals.

The fallback itself is right and deliberate: "a chart that cannot be dated
should say less, not fail". It just has to say less on the AXIS too.
"""

from __future__ import annotations

from qat.presentation.workbench import equity_axis_mode


def test_a_dated_result_keeps_a_date_axis():
    dated, label = equity_axis_mode(has_dates=True)
    assert dated is True
    assert "Date" in label


def test_an_undated_result_does_NOT_claim_to_be_dates():
    """The defect. Small integers on a date axis render as 01.150 under the
    word "Date", which teaches the reader to distrust the chart."""
    dated, label = equity_axis_mode(has_dates=False)
    assert dated is False
    assert "Date" not in label


def test_the_undated_label_says_what_it_IS():
    """Not merely the absence of a lie - the reader needs to know these are
    bar positions, and why there are no dates."""
    _, label = equity_axis_mode(has_dates=False)
    assert "bar" in label.lower()
