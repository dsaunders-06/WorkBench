"""Friday's independent paper-account preflight must fail closed."""

from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest
from test_phase3_broker_inventory import FakeIB

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "phase3_unwind_preflight.py"


def _module():
    spec = importlib.util.spec_from_file_location("phase3_unwind_preflight", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_preflight_reads_only_positions_and_nonbinding_orders():
    module = _module()
    ib = FakeIB()
    await module._connect(ib)
    payload: dict[str, object] = {}
    await module._capture(ib, payload)
    assert [row["method"] for row in payload["requests"]] == [
        "reqPositionsAsync",
        "reqAllOpenOrdersAsync",
    ]
    assert ib.calls.count("du_check") >= 3
    assert "positions_callbacks" in payload
    assert "positions_cache" in payload
    assert "all_open_orders" in payload
    assert "account_summary" not in payload
    assert "executions" not in payload


def test_exact_snapshot_comparison_accepts_only_identical_position_and_order_fields():
    module = _module()
    baseline = {
        "account": "DUQ200898",
        "positions_cache": [
            {
                "account": "DUQ200898",
                "symbol": "BOQ",
                "con_id": 11470910,
                "sec_type": "STK",
                "exchange": "ASX",
                "primary_exchange": "",
                "currency": "AUD",
                "quantity": "13586.0",
            }
        ],
        "all_open_orders": [
            {
                "account": "DUQ200898",
                "symbol": "BOQ",
                "con_id": 11470910,
                "sec_type": "STK",
                "exchange": "SMART",
                "primary_exchange": "",
                "currency": "AUD",
                "order_id": 152,
                "perm_id": 1216552512,
                "client_id": 1,
                "order_ref": "",
                "action": "SELL",
                "order_type": "LMT",
                "quantity": "13586.0",
                "aux_price": "0.0",
                "limit_price": "7.05",
                "tif": "GTC",
                "oca_group": "1216552511",
                "parent_id": 0,
                "status": "Submitted",
            }
        ],
    }
    assert module._compare(baseline, deepcopy(baseline)) == []
    for section, key, changed in (
        ("positions_cache", "quantity", "13585.0"),
        ("positions_cache", "con_id", 99),
        ("all_open_orders", "order_id", 999),
        ("all_open_orders", "limit_price", "7.06"),
        ("all_open_orders", "status", "Filled"),
        ("all_open_orders", "order_type", "STP"),
    ):
        live = deepcopy(baseline)
        live[section][0][key] = changed
        assert module._compare(baseline, live)
    for section in ("positions_cache", "all_open_orders"):
        live = deepcopy(baseline)
        live[section].append(deepcopy(live[section][0]))
        assert module._compare(baseline, live)


def test_baseline_hash_and_approved_table_are_pinned(tmp_path: Path):
    module = _module()
    baseline = tmp_path / "baseline.json"
    baseline.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        module._load_baseline(baseline)
