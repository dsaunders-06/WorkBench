"""A bracket's legs were left on IBKR's implicit OCA, which REDUCES.

Measured against the live account on 7 September - all ten held positions, every
protective pair:

    ocaGroup=1216552511  ocaType=3   (BOQ)
    ocaGroup=579188638   ocaType=3   (TWE)
    ... ten of ten, every one type 3

IBKR's OCA types are 1 = cancel remaining WITH block, 2 = reduce remaining with
block, 3 = reduce remaining, NO block. Type 3 is IBKR's default for the implicit
grouping a bracket's children get, and `to_ib_protective_legs` set no ocaGroup
and no ocaType at all - so it inherited it.

⚠️ THE PROJECT HAD ALREADY DECIDED, IN THE OTHER PATH. `to_ib_oca_pair` sets
type 1 and says why: "Reducing (2 and 3) would leave a partial resting against
shares already sold." Two paths create protective pairs and only one said it.

What type 3 costs: when one leg fills, the sibling is REDUCED rather than
cancelled, and "no block" means no overfill protection - both legs can be
working against the same shares while a partial fill is in flight. On a clean
full stop-out reduce-to-zero looks like cancel, which is why this survived: it
is wrong in exactly the cases nobody watches.

⚠️ NOT THE A2M ORPHAN. That was an app-sent exit leaving non-member legs
untouched, fixed separately in `OMS._release_protective_legs`. No ocaType could
have helped there - the exit was never a member of the group.
"""

from __future__ import annotations

from qat.data.broker.adapter import Order
from qat.data.broker.ib_translate import to_ib_oca_pair, to_ib_protective_legs


def _order() -> Order:
    return Order(
        order_id="app-1",
        symbol="BHP.AX",
        side="buy",
        quantity=100.0,
        status="pending_signoff",
        stop_price=90.0,
        take_profit_price=120.0,
    )


def test_the_legs_share_one_oca_group() -> None:
    legs = to_ib_protective_legs(_order(), parent_id=42)

    groups = {leg.ocaGroup for leg in legs}
    assert len(groups) == 1, "the pair must be ONE group or they are not exclusive"
    assert groups != {""} and groups != {None}, "an unset group is IBKR's implicit one"


def test_the_legs_CANCEL_rather_than_reduce() -> None:
    """⚠️ THE TEST THIS FILE EXISTS FOR. Type 3 is what the live account had on
    all ten positions."""
    legs = to_ib_protective_legs(_order(), parent_id=42)

    assert {leg.ocaType for leg in legs} == {1}


def test_both_protective_paths_agree_on_the_type() -> None:
    """⚠️ The two paths disagreeing IS the defect. Pinned as a relationship so
    changing one alone fails, rather than as two separate constants."""
    bracket = to_ib_protective_legs(_order(), parent_id=42)
    standalone = to_ib_oca_pair(_order(), oca_group="qat-app-1")

    assert {leg.ocaType for leg in bracket} == {leg.ocaType for leg in standalone}


def test_the_transmit_sequencing_is_unchanged() -> None:
    """⚠️ Load-bearing and untouched by this change: only the LAST leg carries
    transmit=True, and that is what releases the group. A bracket sent without
    it sits at IBKR untransmitted while the app believes it is protected."""
    legs = to_ib_protective_legs(_order(), parent_id=42)

    assert [leg.transmit for leg in legs] == [False, True]


def test_the_legs_still_reverse_the_entry_and_stay_GTC() -> None:
    """M31b: DAY killed every stop this system ever placed - about $36,000 sat
    unprotected through a three-day weekend."""
    legs = to_ib_protective_legs(_order(), parent_id=42)

    assert {leg.action for leg in legs} == {"SELL"}
    assert {leg.tif for leg in legs} == {"GTC"}
    assert {leg.parentId for leg in legs} == {42}
