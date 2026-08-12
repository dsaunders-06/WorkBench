"""The announcement record, and why it is deduped the way it is (M39).

Alpaca returned the same MNST announcement once on the Saturday and twice on the
Monday, byte-identical. A store keyed on a record COUNT would read that as a
second corporate action and adjust the same position twice.

Persisted because the query can fail on exactly the morning it matters. A stop
that needs halving before the open cannot wait for the next successful poll.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

from qat.domain.corporate_actions.announcements import Announcement, AnnouncementStore


def _announcement(**kwargs) -> Announcement:
    defaults = dict(
        symbol="SFBS",
        ex_date=date(2026, 8, 21),
        ratio=2.0,
        action_id="ca-1",
        payable_date=date(2026, 8, 20),
        fetched_at=datetime(2026, 8, 12, tzinfo=UTC),
    )
    defaults.update(kwargs)
    return Announcement(**defaults)


def test_the_same_action_returned_twice_is_stored_once(tmp_path):
    store = AnnouncementStore(tmp_path)

    store.remember([_announcement()])
    store.remember([_announcement(), _announcement()])

    assert len(store.for_symbol("SFBS")) == 1


def test_dedupe_is_on_symbol_and_ex_date_not_action_id(tmp_path):
    """Same event, different record id. The id is stable per Alpaca record, not
    per corporate action, so two records for one event must not become two."""
    store = AnnouncementStore(tmp_path)

    store.remember([_announcement(action_id="ca-1")])
    store.remember([_announcement(action_id="ca-2")])

    assert len(store.for_symbol("SFBS")) == 1


def test_a_second_split_on_the_same_symbol_is_a_separate_action(tmp_path):
    store = AnnouncementStore(tmp_path)

    store.remember([_announcement(ex_date=date(2026, 8, 21))])
    store.remember([_announcement(ex_date=date(2026, 11, 2))])

    assert len(store.for_symbol("SFBS")) == 2


def test_it_survives_a_restart(tmp_path):
    """The whole point. A query that fails on ex-date morning must not mean
    acting blind on the one day it matters."""
    AnnouncementStore(tmp_path).remember([_announcement()])

    restored = AnnouncementStore(tmp_path).for_symbol("SFBS")

    assert len(restored) == 1
    assert restored[0].ratio == 2.0
    assert restored[0].ex_date == date(2026, 8, 21)


def test_remember_returns_only_what_was_new(tmp_path):
    """So a caller can log "first seen" without re-announcing every sweep."""
    store = AnnouncementStore(tmp_path)

    first = store.remember([_announcement()])
    second = store.remember([_announcement()])

    assert [a.symbol for a in first] == ["SFBS"]
    assert second == []


def test_an_unreadable_file_reads_as_empty_not_as_a_crash(tmp_path):
    (tmp_path / "corporate_announcements.json").write_text("{not json", encoding="utf-8")

    assert AnnouncementStore(tmp_path).all() == []


def test_no_data_dir_keeps_everything_in_memory(tmp_path):
    store = AnnouncementStore(None)

    store.remember([_announcement()])

    assert len(store.for_symbol("SFBS")) == 1
    assert not list(tmp_path.iterdir())


def test_the_file_is_json_a_human_can_read(tmp_path):
    AnnouncementStore(tmp_path).remember([_announcement()])

    payload = json.loads((tmp_path / "corporate_announcements.json").read_text(encoding="utf-8"))

    assert payload["announcements"][0]["symbol"] == "SFBS"
    assert payload["announcements"][0]["ex_date"] == "2026-08-21"


def test_a_payable_date_before_the_ex_date_round_trips(tmp_path):
    """CRWD's are 1 and 2 July, in that order. It is carried for the record and
    nothing keys on it, but it must survive being written and read."""
    AnnouncementStore(tmp_path).remember(
        [_announcement(ex_date=date(2026, 7, 2), payable_date=date(2026, 7, 1))]
    )

    restored = AnnouncementStore(tmp_path).for_symbol("SFBS")[0]

    assert restored.ex_date == date(2026, 7, 2)
    assert restored.payable_date == date(2026, 7, 1)


def test_a_missing_payable_date_is_allowed(tmp_path):
    AnnouncementStore(tmp_path).remember([_announcement(payable_date=None)])

    assert AnnouncementStore(tmp_path).for_symbol("SFBS")[0].payable_date is None
