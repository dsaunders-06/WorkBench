"""The gates, each written against the case that demands it (M39).

The CRWD test is the one that matters. M60 deliberately deferred automatic
detection because of it: CRWD split 4-for-1 with ex-date 2 July, we hold 16
bought on 31 July, correctly sized post-split, with a correct resting OCO. A
detector matching symbol and ratio over a recent window flags that position and
is wrong, and the false positive is in the live book rather than in a thought
experiment.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from qat.data.broker.adapter import Position
from qat.domain.corporate_actions.announcements import Announcement, AnnouncementStore
from qat.domain.corporate_actions.detector import SplitDetector


def _store(*announcements: Announcement) -> AnnouncementStore:
    store = AnnouncementStore(None)
    store.remember(announcements)
    return store


def _split(symbol: str, ex_date: date, ratio: float = 2.0) -> Announcement:
    return Announcement(
        symbol=symbol,
        ex_date=ex_date,
        ratio=ratio,
        action_id=f"ca-{symbol}",
        payable_date=None,
        fetched_at=datetime(2026, 8, 12, tzinfo=UTC),
    )


def _detect(
    store,
    symbol="MNST",
    opened=datetime(2026, 8, 10, tzinfo=UTC),
    stop=72.68,
    next_session=date(2026, 8, 11),
    quantity=8.0,
):
    detector = SplitDetector(store)
    return detector.pending(
        positions=[Position(symbol=symbol, quantity=quantity, avg_price=91.18)],
        stops={symbol: stop} if stop is not None else {},
        opened_at={symbol: opened},
        next_session=next_session,
    )


def test_the_mnst_case_is_detected():
    """The event that cost $375.23. 2-for-1, ex-date 11 August, bought the 10th,
    stop resting at 72.68."""
    found = _detect(_store(_split("MNST", date(2026, 8, 11))))

    assert [p.symbol for p in found] == ["MNST"]
    assert found[0].ratio == 2.0
    assert found[0].current_stop == 72.68


def test_crwd_is_not_detected():
    """THE gate. Without it, a position that is already correctly sized gets its
    stop divided by four and liquidates at the next open."""
    found = _detect(
        _store(_split("CRWD", date(2026, 7, 2), ratio=4.0)),
        symbol="CRWD",
        opened=datetime(2026, 7, 31, tzinfo=UTC),
        stop=163.32,
        next_session=date(2026, 8, 13),
        quantity=16.0,
    )

    assert found == []


def test_a_split_on_the_open_date_itself_is_not_treated_as_prior():
    """Bought ON the ex-date: the position is already post-split, so this is the
    CRWD case with no days between. The gate is strict, not inclusive."""
    found = _detect(
        _store(_split("MNST", date(2026, 8, 11))),
        opened=datetime(2026, 8, 11, tzinfo=UTC),
    )

    assert found == []


def test_a_split_further_out_than_the_next_session_waits():
    found = _detect(
        _store(_split("MNST", date(2026, 11, 2))),
        next_session=date(2026, 8, 13),
    )

    assert found == []


def test_a_split_on_the_next_session_is_acted_on():
    found = _detect(
        _store(_split("MNST", date(2026, 8, 13))),
        next_session=date(2026, 8, 13),
    )

    assert len(found) == 1


def test_a_split_already_past_is_still_acted_on():
    """An ex-date behind the next session has already applied. The stop still
    needs adjusting, and refusing here would leave it stale forever."""
    found = _detect(
        _store(_split("MNST", date(2026, 8, 11))),
        next_session=date(2026, 8, 13),
    )

    assert len(found) == 1


def test_a_reverse_split_of_one_for_a_thousand_is_kept():
    """ratio 0.001. An earlier draft bounded this at 0.01 and would have thrown
    it away - the ROADMAP records old_rate=1000.0, new_rate=1.0 as real."""
    found = _detect(_store(_split("MNST", date(2026, 8, 11), ratio=0.001)))

    assert len(found) == 1
    assert found[0].ratio == 0.001


def test_a_ratio_of_one_is_not_a_split():
    assert _detect(_store(_split("MNST", date(2026, 8, 11), ratio=1.0))) == []


def test_an_absurd_ratio_is_refused():
    assert _detect(_store(_split("MNST", date(2026, 8, 11), ratio=1e9))) == []


def test_a_negative_ratio_is_refused():
    assert _detect(_store(_split("MNST", date(2026, 8, 11), ratio=-2.0))) == []


def test_a_position_with_no_resting_stop_has_nothing_to_adjust():
    assert _detect(_store(_split("MNST", date(2026, 8, 11))), stop=None) == []


def test_a_symbol_that_is_not_held_is_ignored():
    detector = SplitDetector(_store(_split("SFBS", date(2026, 8, 21))))

    found = detector.pending(
        positions=[Position(symbol="MNST", quantity=8.0, avg_price=91.18)],
        stops={"MNST": 72.68},
        opened_at={"MNST": datetime(2026, 8, 10, tzinfo=UTC)},
        next_session=date(2026, 8, 21),
    )

    assert found == []


def test_a_position_with_no_known_open_date_is_skipped_not_guessed():
    """Without an open date the CRWD gate cannot be applied at all, and applying
    no gate is how CRWD gets adjusted wrongly."""
    detector = SplitDetector(_store(_split("MNST", date(2026, 8, 11))))

    found = detector.pending(
        positions=[Position(symbol="MNST", quantity=8.0, avg_price=91.18)],
        stops={"MNST": 72.68},
        opened_at={},
        next_session=date(2026, 8, 11),
    )

    assert found == []


def test_a_flat_position_is_ignored():
    detector = SplitDetector(_store(_split("MNST", date(2026, 8, 11))))

    found = detector.pending(
        positions=[Position(symbol="MNST", quantity=0.0, avg_price=91.18)],
        stops={"MNST": 72.68},
        opened_at={"MNST": datetime(2026, 8, 10, tzinfo=UTC)},
        next_session=date(2026, 8, 11),
    )

    assert found == []


def test_two_holdings_with_splits_both_come_back():
    detector = SplitDetector(
        _store(
            _split("MNST", date(2026, 8, 11)),
            _split("SFBS", date(2026, 8, 11), ratio=2.0),
        )
    )

    found = detector.pending(
        positions=[
            Position(symbol="MNST", quantity=8.0, avg_price=91.18),
            Position(symbol="SFBS", quantity=10.0, avg_price=50.0),
        ],
        stops={"MNST": 72.68, "SFBS": 40.0},
        opened_at={
            "MNST": datetime(2026, 8, 10, tzinfo=UTC),
            "SFBS": datetime(2026, 8, 10, tzinfo=UTC),
        },
        next_session=date(2026, 8, 11),
    )

    assert sorted(p.symbol for p in found) == ["MNST", "SFBS"]


# --- what every screen says about it (R1) -------------------------------------


def test_a_forward_split_reads_as_two_for_one():
    action = _detect(_store(_split("MNST", date(2026, 8, 11), ratio=2.0)))[0]

    assert action.describe() == "MNST 2-for-1 split, ex-date 2026-08-11"


def test_a_reverse_split_reads_as_one_for_ten_not_as_a_fraction():
    """'MNST 0.1-for-1' is arithmetically true and unreadable. The wording is
    the operator's, not the API's."""
    action = _detect(_store(_split("MNST", date(2026, 8, 11), ratio=0.1)))[0]

    assert action.describe() == "MNST 1-for-10 split, ex-date 2026-08-11"


def test_a_four_for_one_reads_as_four_for_one():
    action = _detect(
        _store(_split("MNST", date(2026, 8, 11), ratio=4.0)),
    )[0]

    assert "4-for-1" in action.describe()
