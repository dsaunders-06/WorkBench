"""Offline guards for the one-session ASX GTD auction probe."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import phase3_gtd_auction_paper_probe as probe  # noqa: E402

SYDNEY = ZoneInfo("Australia/Sydney")


def test_date_gate_refuses_other_day_and_late_start() -> None:
    probe._session_window(date(2026, 10, 26), datetime(2026, 10, 26, 9, 45, tzinfo=SYDNEY))
    with pytest.raises(ValueError):
        probe._session_window(date(2026, 10, 27), datetime(2026, 10, 27, 9, 45, tzinfo=SYDNEY))
    with pytest.raises(ValueError):
        probe._session_window(date(2026, 10, 26), datetime(2026, 10, 26, 10, 0, tzinfo=SYDNEY))


def test_two_limits_and_each_parcel_have_separate_800_cap() -> None:
    limits = probe._orders_from_close(Decimal("40.00"))
    assert limits == ((Decimal("40.80"), 19), (Decimal("38.00"), 21))
    assert all(limit * quantity <= 800 for limit, quantity in limits)
    assert sum(limit * quantity for limit, quantity in limits) > 800


def test_gtd_order_is_explicit_utc_expiry_without_day_fallback() -> None:
    order = probe._buy_order(19, Decimal("40.80"), "DUFAKE", "probe-A")
    assert order.orderType == "LMT"
    assert order.tif == "GTD"
    assert order.goodTillDate == "20261025-23:15:00"
    assert order.action == "BUY"
    assert order.outsideRth is False


def test_prior_close_must_be_previous_session_not_current_or_stale() -> None:
    bars = [
        SimpleNamespace(date=date(2026, 10, 22), close=39),
        SimpleNamespace(date=date(2026, 10, 23), close=40),
    ]
    assert probe._prior_close(bars) == Decimal("40")
    with pytest.raises(ValueError):
        probe._prior_close(bars[:1])
    with pytest.raises(ValueError):
        probe._prior_close([SimpleNamespace(date=date(2026, 10, 26), close=40)])


class FakeIB:
    def __init__(self) -> None:
        self.accounts = ["DUFAKE"]
        self.requests = 0

    def managedAccounts(self) -> list[str]:
        return self.accounts

    def reqPositionsAsync(self) -> list[object]:
        self.requests += 1
        return []

    def placeOrder(self, contract: object, order: object) -> object:
        self.requests += 1
        return order

    def cancelOrder(self, order: object) -> object:
        self.requests += 1
        return order


def test_account_rechecked_before_every_request_and_order() -> None:
    raw = FakeIB()
    client = probe._ExactAccountGateway(raw, "DUFAKE")
    client.reqPositionsAsync()
    client.placeOrder(None, None)
    client.cancelOrder(None)
    assert raw.requests == 3
    raw.accounts = ["DUFAKE", "DUOTHER"]
    with pytest.raises(ValueError):
        client.reqPositionsAsync()
    with pytest.raises(ValueError):
        client.placeOrder(None, None)
    with pytest.raises(ValueError):
        client.cancelOrder(None)
    assert raw.requests == 3


def test_cancel_only_live_remainder_and_never_retry() -> None:
    assert probe._cancel_required("Submitted", 1) is True
    assert probe._cancel_required("PreSubmitted", 1) is True
    assert probe._cancel_required("Filled", 0) is False
    assert probe._cancel_required("Cancelled", 1) is False
    with pytest.raises(RuntimeError):
        probe._cancel_required("PendingCancel", 1)
    with pytest.raises(RuntimeError):
        probe._cancel_required("Inactive", 1)


def test_early_cancellation_and_preopen_fill_halt() -> None:
    cancelled = SimpleNamespace(orderStatus=SimpleNamespace(status="Cancelled"))
    filled = SimpleNamespace(orderStatus=SimpleNamespace(status="Filled"))
    with pytest.raises(RuntimeError, match="before GTD expiry"):
        probe._check_pre_expiry([cancelled], datetime(2026, 10, 26, 10, 5, tzinfo=SYDNEY))
    with pytest.raises(RuntimeError, match="before the ASX opening auction"):
        probe._check_pre_expiry([filled], datetime(2026, 10, 26, 9, 55, tzinfo=SYDNEY))
    probe._check_pre_expiry([cancelled], datetime(2026, 10, 26, 10, 16, tzinfo=SYDNEY))


def test_exit_rejects_unattributed_or_extra_shares() -> None:
    assert probe._exit_quantity(19, 2, 21) == 21
    with pytest.raises(RuntimeError):
        probe._exit_quantity(19, 2, 22)
    with pytest.raises(RuntimeError):
        probe._exit_quantity(19, 2, 20)


def test_session_attempt_cannot_be_repeated(tmp_path: Path) -> None:
    probe._claim_attempt(tmp_path)
    with pytest.raises(FileExistsError):
        probe._claim_attempt(tmp_path)


def test_unrelated_working_order_blocks_exit() -> None:
    own = SimpleNamespace(order=SimpleNamespace(orderRef="gtd-20261026-A"))
    foreign = SimpleNamespace(order=SimpleNamespace(orderRef="other-client"))
    probe._owned_orders_only([own], {"gtd-20261026-A"})
    with pytest.raises(RuntimeError, match="unrelated working order"):
        probe._owned_orders_only([own, foreign], {"gtd-20261026-A"})


def test_fill_details_must_match_broker_filled_status() -> None:
    fill = SimpleNamespace(execution=SimpleNamespace(shares=2))
    trade = SimpleNamespace(orderStatus=SimpleNamespace(filled=3), fills=[fill])
    assert probe._fills_match_status(trade) is False
    trade.orderStatus.filled = 2
    assert probe._fills_match_status(trade) is True


def test_exact_private_approval_terms_and_hash(tmp_path: Path) -> None:
    path = tmp_path / "approval.json"
    terms = {
        "account": "DUFAKE",
        "approved_by": "DS",
        "approval_date": "2026-10-23",
        "session": "2026-10-26",
        "symbol": "BHP.AX",
        "operator": "DS",
        "cap_per_order_aud": "800",
    }
    path.write_text(json.dumps(terms), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert probe._load_approval(path, digest) == "DUFAKE"
    terms["cap_per_order_aud"] = "1600"
    path.write_text(json.dumps(terms), encoding="utf-8")
    with pytest.raises(ValueError):
        probe._load_approval(path, digest)
