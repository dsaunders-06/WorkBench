"""Protective-stop expiry is derived from QAT placement, never the API date."""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest
from ib_async import OrderStatus, Stock, StopOrder, Trade

from qat.data.broker import gtc_expiry
from qat.data.broker.adapter import RestingStopOrder
from qat.data.broker.gtc_expiry import GtcExpiryStore
from qat.data.broker.ib_translate import from_ib_resting_stop


def _trade(auto_cancel_date: str) -> Trade:
    contract = Stock("BHP", "SMART", "AUD")
    order = StopOrder("SELL", 10, 58.0, tif="GTC")
    order.permId = 999
    order.autoCancelDate = auto_cancel_date
    return Trade(contract, order, OrderStatus(status="Submitted", remaining=10))


@pytest.mark.parametrize("raw", ["20261231", "2026-12-31", "not a date"])
def test_broker_auto_cancel_date_is_ignored_even_when_malformed(raw: str) -> None:
    stop = from_ib_resting_stop(_trade(raw))
    assert stop is not None
    assert stop.auto_cancel_date is None


def test_missing_auto_cancel_date_is_explicitly_unknown() -> None:
    stop = from_ib_resting_stop(_trade(""))
    assert stop is not None
    assert stop.auto_cancel_date is None


def test_every_duplicate_protective_stop_keeps_its_own_expiry(tmp_path) -> None:
    store = GtcExpiryStore(tmp_path / "gtc_expiry.json")
    store.record(
        [
            RestingStopOrder("BHP.AX", "999", 58.0, 10, auto_cancel_date=date(2026, 12, 31)),
            RestingStopOrder("BHP.AX", "1000", 58.0, 10, auto_cancel_date=date(2027, 3, 31)),
        ]
    )
    saved = json.loads(store.path.read_text(encoding="utf-8"))
    assert set(saved["stops"]) == {"999", "1000"}


@pytest.mark.parametrize(
    ("placed", "expected"),
    [
        (datetime.fromisoformat("2026-10-20T10:30:00+11:00"), date(2027, 3, 31)),
        (datetime.fromisoformat("2026-12-31T14:00:00+11:00"), date(2027, 3, 31)),
        (datetime.fromisoformat("2027-01-01T10:30:00+11:00"), date(2027, 6, 30)),
        (datetime.fromisoformat("2028-04-01T10:30:00+11:00"), date(2028, 9, 29)),
    ],
)
def test_expected_gtc_auto_cancel_uses_following_quarter_last_asx_session(
    placed: datetime, expected: date
) -> None:
    assert gtc_expiry.expected_gtc_auto_cancel_date(placed) == expected


def test_placed_stop_keeps_its_own_timestamp_and_repeats_expiry_alert_daily(tmp_path) -> None:
    store = GtcExpiryStore(tmp_path / "gtc_expiry.json")
    store.mark_placed("qat-stop-ref", datetime.fromisoformat("2026-10-20T10:30:00+11:00"))
    store.record(
        [RestingStopOrder("BHP.AX", "999", 51.5, 9, order_ref="qat-stop-ref")],
        observed_at=datetime.fromisoformat("2026-10-22T17:30:00+11:00"),
    )
    saved = json.loads(store.path.read_text(encoding="utf-8"))["stops"]["999"]
    assert saved["placed_at"] == "2026-10-20T10:30:00+11:00"
    assert saved["first_seen_at"] == "2026-10-22T17:30:00+11:00"
    assert saved["expected_auto_cancel_date"] == "2027-03-31"
    assert store.due_alerts(date(2027, 2, 28)) == []
    assert len(store.due_alerts(date(2027, 3, 1))) == 1
    assert store.due_alerts(date(2027, 3, 1)) == []
    assert len(store.due_alerts(date(2027, 3, 2))) == 1


def test_manually_placed_stop_with_unknown_placement_age_alerts_immediately(tmp_path) -> None:
    store = GtcExpiryStore(tmp_path / "gtc_expiry.json")
    store.record(
        [RestingStopOrder("BHP.AX", "999", 51.5, 9)],
        observed_at=datetime.fromisoformat("2026-10-22T17:30:00+11:00"),
    )
    saved = json.loads(store.path.read_text(encoding="utf-8"))["stops"]["999"]
    assert saved["placed_at"] is None
    assert saved["first_seen_at"] == "2026-10-22T17:30:00+11:00"
    # First seen is not placement: IBKR may have accepted this stop months ago.
    assert len(store.due_alerts(date(2026, 10, 22))) == 1
    assert store.due_alerts(date(2026, 10, 22)) == []
    assert len(store.due_alerts(date(2026, 10, 23))) == 1


def test_last_owned_stop_survives_broker_disappearance_without_a_looser_rewrite(tmp_path) -> None:
    store = GtcExpiryStore(tmp_path / "gtc_expiry.json")
    owned = RestingStopOrder("BHP.AX", "999", 55.0, 10, order_ref="qat-stop-ref")
    store.record([owned], owned_stops=[owned])
    store.record([])
    last = store.last_owned_stop("BHP.AX")
    assert last is not None
    assert (last["order_id"], last["order_ref"], last["stop_price"], last["quantity"]) == (
        "999",
        "qat-stop-ref",
        55.0,
        10,
    )


def test_each_card_stop_retains_separate_owned_identity_after_disappearance(tmp_path) -> None:
    store = GtcExpiryStore(tmp_path / "gtc_expiry.json")
    banked = RestingStopOrder("BHP.AX", "1000", 50, 5, order_ref="banked-ref")
    runner = RestingStopOrder("BHP.AX", "1001", 50, 5, order_ref="runner-ref")
    store.record([banked, runner], owned_stops=[banked, runner])
    store.record([], owned_stops=[])
    assert store.last_owned_stop("BHP.AX", "banked-ref")["order_id"] == "1000"
    assert store.last_owned_stop("BHP.AX", "runner-ref")["order_id"] == "1001"


def test_confirmed_price_modification_resets_expected_quarter_but_rejection_does_not(
    tmp_path,
) -> None:
    store = GtcExpiryStore(tmp_path / "gtc_expiry.json")
    old = RestingStopOrder("BHP.AX", "999", 50.0, 10, order_ref="qat-stop-ref")
    store.mark_placed("qat-stop-ref", datetime.fromisoformat("2026-12-30T10:30:00+11:00"))
    store.record([old])
    store.mark_modification_submitted(
        "qat-stop-ref", 55.0, 10, datetime.fromisoformat("2027-01-04T11:00:00+11:00")
    )
    store.record([old])  # Broker still shows the old terms: no reset.
    saved = json.loads(store.path.read_text(encoding="utf-8"))["stops"]["999"]
    assert saved["expected_auto_cancel_date"] == "2027-03-31"

    changed = RestingStopOrder("BHP.AX", "999", 55.0, 10, order_ref="qat-stop-ref")
    store.record([changed])
    saved = json.loads(store.path.read_text(encoding="utf-8"))["stops"]["999"]
    assert saved["placed_at"] == "2027-01-04T11:00:00+11:00"
    assert saved["expected_auto_cancel_date"] == "2027-06-30"
