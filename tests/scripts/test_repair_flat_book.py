"""A copied-store repair is gated by an independent, flat broker inventory."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime

import pytest

from qat.domain.performance.trades import _FIELDS, ClosedTrade
from scripts.repair_flat_book import apply_repair, plan_repair


def _json(path, value):
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def _fixture(tmp_path):
    data = tmp_path / "stores"
    data.mkdir()
    _json(
        data / "open_position_entries.json",
        {
            "AAA.AX": {
                "opened_at": "2026-09-01T00:00:00+00:00",
                "price": 10.0,
                "stop_price": 9.0,
                "strategy": "swing",
                "quantity": 10.0,
                "reference_price": 9.95,
            }
        },
    )
    _json(
        data / "exit_recovery.json",
        {
            "AAA.AX": {
                "symbol": "AAA.AX",
                "quantity": 10.0,
                "stop_price": 9.0,
                "stage": "prepared",
                "other_orders_present": False,
            }
        },
    )
    _json(
        data / "inflight_orders.json",
        {
            "orders": {
                "stale": {
                    "stage": "accepted",
                    "order": {
                        "symbol": "BBB.AX",
                        "side": "sell",
                        "quantity": 5.0,
                        "order_type": "stop",
                        "status": "transmitted",
                    },
                }
            }
        },
    )
    _json(
        data / "ib_pending_legs.json",
        {
            "legs": [
                {
                    "app_order_id": "stale",
                    "symbol": "BBB.AX",
                    "broker_order_id": 123,
                    "perm_id": 456,
                    "resolved": True,
                }
            ]
        },
    )
    existing = ClosedTrade(
        symbol="BBB.AX",
        strategy="swing",
        quantity=5,
        entry_price=20,
        exit_price=21,
        stop_price=19,
        opened_at=datetime(2026, 9, 1, tzinfo=UTC),
        closed_at=datetime(2026, 10, 20, tzinfo=UTC),
        market="ASX",
        currency="AUD",
        order_id="bbb-sell",
    )
    with (data / "closed_trades.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_FIELDS)
        writer.writeheader()
        writer.writerow(existing.as_row())
    (data / "unchanged.txt").write_text("keep", encoding="utf-8")
    inventory = {
        "read_only": True,
        "account": "DU_TEST",
        "positions_callbacks": [{"account": "DU_TEST", "symbol": "AAA", "quantity": "0.0"}],
        "positions_cache": [],
        "all_open_orders": [],
        "requests": [
            {"method": "reqPositionsAsync"},
            {"method": "reqAllOpenOrdersAsync"},
            {"method": "reqExecutionsAsync"},
        ],
        "executions": [
            {
                "account": "DU_TEST",
                "symbol": "AAA",
                "side": "SLD",
                "quantity": "10",
                "price": "11",
                "perm_id": 789,
                "exec_id": "E1",
                "execution_time_utc": "2026-10-21T00:10:00+00:00",
                "commission": (
                    "CommissionReport(execId='E1', commission=1.23, "
                    "currency='AUD', realizedPNL=7.77)"
                ),
            }
        ],
    }
    names = (
        "open_position_entries.json",
        "exit_recovery.json",
        "inflight_orders.json",
        "closed_trades.csv",
        "ib_pending_legs.json",
    )
    spec = {
        "account": "DU_TEST",
        "close_symbol": "AAA.AX",
        "existing_closed_symbol": "BBB.AX",
        "existing_close_order_id": "bbb-sell",
        "stale_inflight_app_order_id": "stale",
        "stale_broker_order_id": 123,
        "stale_perm_id": 456,
        "manual_sell_perm_id": 789,
        "session_date": "2026-10-21",
        "execution_ids": ["E1"],
        "entry_cost": 1.0,
        "expected_sha256": {
            name: hashlib.sha256((data / name).read_bytes()).hexdigest() for name in names
        },
    }
    return data, inventory, spec


def test_repair_changes_only_the_four_intended_records(tmp_path):
    data, inventory, spec = _fixture(tmp_path)
    before = {path.name: path.read_bytes() for path in data.iterdir()}
    planned = plan_repair(data, inventory, spec)
    assert set(planned.updates) == {
        "open_position_entries.json",
        "exit_recovery.json",
        "inflight_orders.json",
        "closed_trades.csv",
    }
    assert {path.name: path.read_bytes() for path in data.iterdir()} == before

    apply_repair(data, planned)

    assert json.loads((data / "open_position_entries.json").read_text()) == {}
    assert json.loads((data / "exit_recovery.json").read_text()) == {}
    assert json.loads((data / "inflight_orders.json").read_text()) == {"orders": {}}
    assert (data / "ib_pending_legs.json").read_bytes() == before["ib_pending_legs.json"]
    assert (data / "unchanged.txt").read_bytes() == before["unchanged.txt"]
    with (data / "closed_trades.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert rows[0]["symbol"] == "BBB.AX" and rows[0]["order_id"] == "bbb-sell"
    assert rows[1]["symbol"] == "AAA.AX"
    assert rows[1]["quantity"] == "10.0"
    assert rows[1]["exit_price"] == "11.0"
    assert rows[1]["exit_cost"] == "1.23"
    assert rows[1]["exit_reason"] == "manual sale outside QAT"
    assert planned.before_hashes != planned.after_hashes


@pytest.mark.parametrize(
    "field,row", [("positions_callbacks", {"symbol": "AAA"}), ("all_open_orders", {"order_id": 1})]
)
def test_repair_refuses_a_nonflat_book_without_writing(tmp_path, field, row):
    data, inventory, spec = _fixture(tmp_path)
    before = {path.name: path.read_bytes() for path in data.iterdir()}
    inventory[field] = [row]

    with pytest.raises(ValueError, match="flat"):
        plan_repair(data, inventory, spec)

    assert {path.name: path.read_bytes() for path in data.iterdir()} == before


def test_repair_refuses_a_stale_source_hash(tmp_path):
    data, inventory, spec = _fixture(tmp_path)
    (data / "inflight_orders.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        plan_repair(data, inventory, spec)


def test_repair_refuses_an_entry_cost_that_disagrees_with_broker_pnl(tmp_path):
    data, inventory, spec = _fixture(tmp_path)
    spec["entry_cost"] = 0.0
    with pytest.raises(ValueError, match="entry cost"):
        plan_repair(data, inventory, spec)
