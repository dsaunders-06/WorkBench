"""The G1 comparator, on synthetic rows (W2 step 5).

Tested independently of any real window: the gate's verdict rests on this, so
it must be right before it is ever pointed at evidence that could be blamed for
a disagreement it did not cause.
"""

from __future__ import annotations

from datetime import date

from qat.domain.evaluation.replay_agreement import APPROVED_RAIL, compare, rails_by_symbol_day

POSITION_LIMIT = "already at the 10-position limit (10 held or pending)"
CAP = "aggregate risk-at-stop 5.08% is at or above the 5.00% cap"
COST_A = "Round-trip cost $18.24 is 13.2% of the $138.38 at risk, above the 10.0% limit"
COST_B = "Round-trip cost $18.24 is 13.2% of the $138.37 at risk, above the 10.0% limit"


def _row(symbol: str, day: str, reason: str, approved: bool = False) -> dict[str, str]:
    return {
        "symbol": symbol,
        "timestamp": f"{day}T14:31:02+00:00",
        "approved": "True" if approved else "False",
        "reason": "approved" if approved else reason,
    }


def test_reason_text_that_differs_only_in_cents_is_one_rail():
    """The whole reason the key is the rail. Grouping by text would make these
    two rows two different causes."""
    rails = rails_by_symbol_day(
        [_row("MS", "2026-08-05", COST_A), _row("MS", "2026-08-05", COST_B)]
    )

    assert rails == {("MS", date(2026, 8, 5)): {"Cost-to-risk (trade too small)"}}


def test_seventy_refusals_in_a_day_collapse_to_one_fact():
    """Live polls all day; the replay evaluates once. A symbol refused all day
    by one rail is one fact, not seventy."""
    rows = [_row("GS", "2026-08-06", POSITION_LIMIT) for _ in range(70)]

    verdict = compare(rows, [_row("GS", "2026-08-06", POSITION_LIMIT)])

    assert verdict.exact_days == 1
    assert [(r.rail, r.agreed) for r in verdict.rails] == [("Position limit", 1)]


def test_a_different_rail_on_the_same_day_is_a_disagreement():
    verdict = compare([_row("MS", "2026-08-05", CAP)], [_row("MS", "2026-08-05", POSITION_LIMIT)])

    assert verdict.disjoint_days == 1
    assert verdict.exact_days == 0
    by_rail = {r.rail: r for r in verdict.rails}
    assert by_rail["Aggregate risk-at-stop cap"].live_only == 1
    assert by_rail["Position limit"].harness_only == 1


def test_rails_differing_within_a_day_are_PARTIAL_not_a_miss():
    """The cap binds in the morning, the position limit in the afternoon. The
    replay cannot see intraday, and scoring that as failure would tune the gate
    toward a resolution the daily data does not have."""
    live = [_row("MS", "2026-08-06", CAP), _row("MS", "2026-08-06", POSITION_LIMIT)]

    verdict = compare(live, [_row("MS", "2026-08-06", POSITION_LIMIT)])

    assert verdict.partial_days == 1
    assert verdict.disjoint_days == 0
    by_rail = {r.rail: r for r in verdict.rails}
    assert by_rail["Position limit"].agreed == 1
    assert by_rail["Aggregate risk-at-stop cap"].live_only == 1


def test_an_approval_is_a_rail_too():
    """ "The live book let this through and the replay refused it" is exactly as
    much a disagreement as the reverse."""
    verdict = compare(
        [_row("MS", "2026-08-05", "", approved=True)],
        [_row("MS", "2026-08-05", POSITION_LIMIT)],
    )

    assert verdict.disjoint_days == 1
    by_rail = {r.rail: r for r in verdict.rails}
    assert by_rail[APPROVED_RAIL].live_only == 1


def test_a_symbol_day_present_on_one_side_only_is_its_own_category():
    """Never silently dropped: a day the harness never considered is a
    different failure from one it considered and got wrong."""
    verdict = compare([_row("MS", "2026-08-05", CAP)], [])

    assert verdict.live_only_days == 1
    assert verdict.harness_only_days == 0
    assert verdict.days_considered == 1


def test_excluded_symbols_are_dropped_from_both_sides_and_named():
    """AAA is a test fixture symbol that reached the live record; WES.AX is an
    ASX ticker in a US book. Both are excluded by name, not by silence."""
    verdict = compare(
        [_row("AAA", "2026-08-12", "", approved=True), _row("MS", "2026-08-05", CAP)],
        [_row("MS", "2026-08-05", CAP)],
        exclude=frozenset({"AAA", "WES.AX"}),
    )

    assert verdict.exact_days == 1
    assert verdict.days_considered == 1
    assert verdict.excluded == ("AAA", "WES.AX")


def test_agreement_rate_is_per_rail_not_pooled():
    """2,511 of 2,886 live refusals are one rail. A pooled rate would be that
    rail's rate wearing everything else's name."""
    live = [_row("A", "2026-08-05", POSITION_LIMIT), _row("B", "2026-08-05", CAP)]
    harness = [_row("A", "2026-08-05", POSITION_LIMIT), _row("B", "2026-08-05", POSITION_LIMIT)]

    verdict = compare(live, harness)

    by_rail = {r.rail: r for r in verdict.rails}
    assert by_rail["Position limit"].agreement_rate == 0.5
    assert by_rail["Aggregate risk-at-stop cap"].agreement_rate == 0.0
