"""The invariant, checked against the numbers that produced it (M39).

The asymmetry is the design. A wrong ratio that leaves the stop too FAR away
costs more if the position runs against us. A wrong ratio that leaves it too
CLOSE liquidates on contact. One is a worse loss, the other is a guaranteed one,
so both guards fail in the same direction: refuse, and say why.

A guard that refused the CORRECT adjustment would be worse than no guard, so
the MNST numbers are asserted to pass it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from qat.domain.corporate_actions.adjuster import ACT, SHADOW, StopAdjuster
from qat.domain.corporate_actions.announcements import Announcement
from qat.domain.corporate_actions.detector import PendingAction


def _action(ratio: float = 2.0, stop: float | None = 72.68) -> PendingAction:
    return PendingAction(
        announcement=Announcement(
            symbol="MNST",
            ex_date=date(2026, 8, 11),
            ratio=ratio,
            action_id="ca-1",
            payable_date=None,
            fetched_at=datetime(2026, 8, 12, tzinfo=UTC),
        ),
        position_opened_at=datetime(2026, 8, 10, tzinfo=UTC),
        current_stop=stop,
    )


def test_the_mnst_stop_is_halved():
    """72.68 / 2 = 36.34. This is the adjustment that was never made, and the
    $375.23 is what not making it cost."""
    assessed = StopAdjuster(ACT).assess(_action(), price=46.30, pre_action_price=91.18)

    assert assessed.adjusted_stop == 36.34
    assert assessed.state == "applied"


def test_the_mnst_adjustment_satisfies_the_invariant():
    """Before: (91.18 - 72.68)/91.18 = 20.3%. After: (46.30 - 36.34)/46.30 =
    21.5%. The CORRECT adjustment must be admitted, or the guard is useless."""
    assessed = StopAdjuster(ACT).assess(_action(), price=46.30, pre_action_price=91.18)

    assert assessed.refusal is None


def test_a_stop_that_would_sit_above_the_market_is_refused():
    """An inverted ratio: 0.5 given for a forward split puts the stop at 145.36
    against a 46.30 market. That is a market order wearing a stop's clothing,
    and it is exactly the MNST failure."""
    assessed = StopAdjuster(ACT).assess(_action(ratio=0.5), price=46.30, pre_action_price=91.18)

    assert assessed.state == "refused"
    assert assessed.refusal is not None
    assert "above" in assessed.refusal


def test_an_adjustment_that_tightens_the_stop_is_refused():
    """The ratio is right and the market has fallen further than it explains.

    MNST's stop halves correctly to 36.34, but against a 38.00 market that is
    4.4% away where it was 20.3% before. The division is valid arithmetic and
    the result would liquidate on the next tick, which is precisely what this
    guard is for.
    """
    assessed = StopAdjuster(ACT).assess(
        _action(ratio=2.0, stop=72.68), price=38.00, pre_action_price=91.18
    )

    assert assessed.state == "refused"
    assert assessed.refusal is not None
    assert "tighten" in assessed.refusal


def test_a_reverse_split_raises_the_stop_in_price_terms():
    """1-for-10: ratio 0.1, price ten times higher, stop ten times higher."""
    assessed = StopAdjuster(ACT).assess(
        _action(ratio=0.1, stop=72.68), price=911.80, pre_action_price=91.18
    )

    assert assessed.adjusted_stop == 726.80
    assert assessed.state == "applied"


def test_shadow_mode_reaches_the_same_verdict():
    assessed = StopAdjuster(SHADOW).assess(_action(), price=46.30, pre_action_price=91.18)

    assert assessed.adjusted_stop == 36.34
    assert assessed.state == "shadowed"


def test_shadow_mode_still_refuses_what_act_mode_would_refuse():
    """Otherwise the shadow period teaches nothing about the guard, which is the
    main thing the shadow period exists to test."""
    assessed = StopAdjuster(SHADOW).assess(_action(ratio=0.5), price=46.30, pre_action_price=91.18)

    assert assessed.state == "refused"


def test_an_action_with_no_current_stop_is_refused_not_crashed():
    assessed = StopAdjuster(ACT).assess(_action(stop=None), price=46.30, pre_action_price=91.18)

    assert assessed.state == "refused"


def test_a_zero_price_is_refused():
    """A feed that returns nothing must not become an adjustment computed
    against zero."""
    assessed = StopAdjuster(ACT).assess(_action(), price=0.0, pre_action_price=91.18)

    assert assessed.state == "refused"


def test_a_zero_pre_action_price_is_refused():
    assessed = StopAdjuster(ACT).assess(_action(), price=46.30, pre_action_price=0.0)

    assert assessed.state == "refused"


def test_the_original_action_is_not_mutated():
    """PendingAction is frozen, and assess returns a copy. A caller holding the
    original must still see the un-assessed state."""
    action = _action()

    StopAdjuster(ACT).assess(action, price=46.30, pre_action_price=91.18)

    assert action.state == "pending"
    assert action.adjusted_stop is None


def test_a_refusal_still_reports_what_it_would_have_placed():
    """So an operator can see the number that was rejected rather than only
    that something was."""
    assessed = StopAdjuster(ACT).assess(_action(ratio=0.5), price=46.30, pre_action_price=91.18)

    assert assessed.adjusted_stop == 145.36


def test_the_price_drifting_a_little_does_not_read_as_tightening():
    """Between the pre-action price and the current one the market moves. The
    tolerance absorbs that; without it, an ordinary tick would refuse a correct
    adjustment."""
    assessed = StopAdjuster(ACT).assess(_action(), price=46.20, pre_action_price=91.18)

    assert assessed.state == "applied"
