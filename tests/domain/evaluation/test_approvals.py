"""What an approval nearly was (M51).

"Approved" is one bit and it hides everything worth knowing. An entry taken with
88% of the risk budget already spent is a different decision from the same entry
into an empty book, and the trade ledger cannot tell them apart.

The `inputs` payload here is copied from the operator's own risk_decisions.csv -
the VRTX entry of 6 August - rather than invented.
"""

from __future__ import annotations

from qat.config import Settings
from qat.domain.evaluation.approvals import (
    format_approval_section,
    pressures_for,
    summarise_approvals,
)

_SETTINGS = Settings(_env_file=None)

# Verbatim shape, written by DecisionAuditLog as a Python repr rather than JSON.
_VRTX_INPUTS = (
    "{'symbol': 'VRTX', 'side': 'buy', 'price': 487.2, 'equity': 101597.43, "
    "'regime_scalar': 1.0, 'available_cash': 54044.55, 'stop_source': 'strategy', "
    "'stop_distance': 30.93, 'governor': {'aggregate_risk_pct': 0.044055937, "
    "'position_count': 9.0, 'headroom_dollars': 603.9, 'per_share_risk': 30.93, "
    "'held_in_name_dollars': 0, 'held_in_sector_dollars': 0.0, "
    "'held_in_cluster_dollars': 0.0, 'cluster_size': 0.0, "
    "'gross_exposure_pct': 0.456, 'gap_loss_at_shock_dollars': 2779.93}, "
    "'resized_by_governor': True, 'portfolio_check': {'var_95': 0.00967, "
    "'var_99': 0.01495, 'es_975': 0.014945, 'single_name_pct': 0.09362, "
    "'sector_pct': None}, 'round_trip_cost': 22.71, 'cost_to_risk_pct': 0.0376}"
)


def _row(inputs: str = _VRTX_INPUTS, *, reason: str = "approved", shares: str = "19.5") -> dict:
    return {
        "timestamp": "2026-08-06T01:16:08+00:00",
        "symbol": "VRTX",
        "approved": "True",
        "final_shares": shares,
        "stop_price": "456.27",
        "reason": reason,
        "inputs": inputs,
    }


def test_the_inputs_column_is_a_python_repr_not_json():
    """It is written with str(dict), so single quotes, True and None. Parsing it
    as JSON alone would silently drop every approval."""
    pressures = pressures_for(
        __import__("ast").literal_eval(_VRTX_INPUTS),
        _SETTINGS,
    )

    assert pressures, "the recorded shape must parse"


def test_each_rail_is_measured_against_its_configured_limit():
    summary = summarise_approvals([_row()], _SETTINGS)
    by_rail = {p.rail: p for p in summary.decisions[0].pressures}

    # 4.41% used against a 5% cap.
    assert by_rail["Aggregate risk-at-stop"].utilisation == __import__("pytest").approx(
        0.044055937 / 0.05
    )
    # 9 of 10 slots.
    assert by_rail["Position count"].utilisation == __import__("pytest").approx(0.9)


def test_a_rail_that_was_not_measured_is_omitted_not_treated_as_zero():
    """sector_pct is None here - no sector was known. Reporting that as 0%
    would say the rail was comfortable when it was never evaluated."""
    summary = summarise_approvals([_row()], _SETTINGS)

    assert "Sector concentration" not in {p.rail for p in summary.decisions[0].pressures}


def test_dollar_rails_are_converted_to_a_share_of_equity():
    """gap_loss_at_shock_dollars is money; its cap is a percentage. Comparing
    them directly would report 2,779 against 0.05."""
    summary = summarise_approvals([_row()], _SETTINGS)
    gap = next(p for p in summary.decisions[0].pressures if p.rail == "Gap-risk budget")

    assert 0.0 < gap.utilisation < 1.0


def test_the_tightest_rail_is_the_one_reported():
    summary = summarise_approvals([_row()], _SETTINGS)

    assert summary.decisions[0].tightest is not None
    assert summary.decisions[0].tightest.rail == "Position count"  # 90%, the highest here


def test_exits_are_excluded_because_they_bypass_sizing():
    """They carry no portfolio check and were never subject to the caps, so
    counting them would dilute the figure with decisions that had no rails."""
    rows = [
        _row(reason="exit - closing existing position (entry sizing bypassed)"),
        _row(reason="delever"),
        _row(),
    ]

    assert summarise_approvals(rows, _SETTINGS).count == 1


def test_a_trimmed_order_is_counted_and_named():
    """The governor resizes rather than refusing, so a trim leaves no refusal
    behind. An order cut from 40 shares to 19 was half-refused and nothing else
    counts it."""
    summary = summarise_approvals([_row()], _SETTINGS)

    assert summary.resized_count == 1
    assert "VRTX (20)" in format_approval_section(summary)


def test_shares_come_back_as_a_number_not_a_string():
    """CSV columns are strings even when they hold numbers, which is how every
    trimmed order first reported as "(0)"."""
    assert summarise_approvals([_row(shares="19.523")], _SETTINGS).decisions[0].shares > 19


def test_an_unreadable_payload_is_counted_rather_than_dropped_silently():
    summary = summarise_approvals([_row(inputs="not parseable {{{")], _SETTINGS)

    assert summary.count == 0
    assert summary.unreadable == 1
    assert "excluded from the figures" in format_approval_section(summary)


def test_no_approvals_says_so_rather_than_implying_none_were_wanted():
    summary = summarise_approvals([], _SETTINGS)

    assert "No entry approvals recorded" in summary.headline()


def test_the_headline_uses_singular_for_one_trim():
    summary = summarise_approvals([_row()], _SETTINGS)

    assert "1 of them was TRIMMED" in summary.headline()
