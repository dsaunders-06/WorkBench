"""Why orders did not happen (M51).

Every reason string here is copied from `risk_decisions.csv` or
`decision_journal.csv` as actually written by the running application, not
invented. A classifier tested against strings someone made up classifies made-up
strings.
"""

from __future__ import annotations

from qat.domain.evaluation.refusals import (
    RefusalFamily,
    classify,
    format_refusal_section,
    load_risk_decisions,
    rail_of,
    summarise_refusals,
)

# Verbatim from the operator's files, 26 July - 6 August.
_POSITION_LIMIT = "already at the 10-position limit (10 held or pending)"
_RISK_CAP = "aggregate risk-at-stop 5.08% is at or above the 5.00% cap"
_COST_RAIL = (
    "Round-trip cost $18.24 is 13.2% of the $138.38 at risk, above the 10.0% limit - "
    "the trade is too small to carry its fees"
)
_BROKER = 'broker refused: {"available":"0","code":40310000,"message":"insufficient qty available"}'
_SESSION = "session phase 'Opening Volatility' is not eligible for unattended execution"
_KILL = "kill-switch active: Broker reconciliation mismatch"


def _row(reason: str = "", *, symbol: str = "AAA", approved: bool = False) -> dict[str, str]:
    return {
        "timestamp": "2026-08-05T14:00",
        "symbol": symbol,
        "approved": str(approved),
        "reason": reason,
    }


def test_capacity_says_nothing_about_the_trade():
    assert classify(_POSITION_LIMIT) is RefusalFamily.CAPACITY
    assert classify(_RISK_CAP) is RefusalFamily.CAPACITY


def test_the_cost_rail_is_about_the_candidate_not_the_book():
    """The distinction the whole module exists for. 269 of these are recorded,
    and counting them as capacity would say "raise the limits" when the truth is
    "the strategy is producing trades too small to carry their own commission"."""
    assert classify(_COST_RAIL) is RefusalFamily.CANDIDATE


def test_state_and_execution_are_separated():
    assert classify(_SESSION) is RefusalFamily.STATE
    assert classify(_KILL) is RefusalFamily.STATE
    # The broker disagreeing with the app is a defect signal, not a rail signal.
    assert classify(_BROKER) is RefusalFamily.EXECUTION


def test_an_unknown_rail_is_flagged_not_absorbed():
    """A rail added later must not vanish into the largest bucket - that would
    be this module committing the failure it exists to prevent."""
    assert classify("some brand new rail nobody has written yet") is RefusalFamily.UNCLASSIFIED


def test_one_rail_is_one_row_whatever_the_numbers():
    """Grouping by reason text fragmented the cost rail across every price it
    mentioned: the largest row read 14 against a true total of 269."""
    a = "Round-trip cost $18.24 is 13.2% of the $138.38 at risk, above the 10.0% limit - too small"
    b = "Round-trip cost $19.01 is 14.8% of the $128.10 at risk, above the 10.0% limit - too small"

    assert rail_of(a) == rail_of(b)

    summary = summarise_refusals([_row(a), _row(b), _row(a)])

    assert summary.by_reason == {"Cost-to-risk (trade too small)": 3}


def test_the_headline_leads_with_the_split_that_decides_what_to_do():
    rows = [_row(_POSITION_LIMIT) for _ in range(8)] + [_row(_COST_RAIL), _row("", approved=True)]

    headline = summarise_refusals(rows).headline()

    assert "10 candidate(s) considered, 1 approved" in headline
    assert "8 were capacity" in headline
    assert "1 were the candidate failing a test" in headline


def test_symbols_asked_for_and_never_taken_are_named():
    """These are what a capacity cap actually costs - a symbol the strategy kept
    asking for and never once got."""
    rows = [
        _row(_POSITION_LIMIT, symbol="MU"),
        _row(_POSITION_LIMIT, symbol="MU"),
        _row(symbol="VRTX", approved=True),
        _row(_POSITION_LIMIT, symbol="VRTX"),
    ]

    summary = summarise_refusals(rows)

    assert summary.never_approved == ("MU",)
    assert summary.by_symbol["MU"] == 2


def test_an_empty_record_does_not_pretend_to_know_anything():
    summary = summarise_refusals([])

    assert summary.considered == 0
    assert summary.approval_rate is None
    assert "No sizing decisions recorded" in summary.headline()


def test_a_missing_file_reads_as_no_decisions(tmp_path):
    """An analysis layer must never be able to stop a report being produced."""
    assert load_risk_decisions(tmp_path) == []


def test_the_window_filter_is_inclusive_of_its_start(tmp_path):
    (tmp_path / "risk_decisions.csv").write_text(
        "timestamp,symbol,approved,reason\n"
        "2026-08-04T10:00,AAA,False,x\n"
        "2026-08-05T10:00,BBB,False,y\n",
        encoding="utf-8",
    )

    rows = load_risk_decisions(tmp_path, since="2026-08-05")

    assert [row["symbol"] for row in rows] == ["BBB"]


def test_the_report_section_states_what_each_family_means():
    """A count with no interpretation is what this replaced."""
    section = format_refusal_section(summarise_refusals([_row(_POSITION_LIMIT), _row(_COST_RAIL)]))

    assert "Why orders did not happen" in section
    assert "the book was full" in section
    assert "says something about the strategy" in section
    assert "Position limit" in section
    assert "Cost-to-risk (trade too small)" in section


def test_a_period_with_no_refusals_says_so_briefly():
    section = format_refusal_section(summarise_refusals([_row(approved=True)]))

    assert "none refused" in section
    assert "| Family |" not in section
