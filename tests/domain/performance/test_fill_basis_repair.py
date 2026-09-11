"""The rewrite of records whose entry price is IBKR's commission-inclusive
average (M175). Fixtures only - never the live ledger. Log lines are the REAL
formats, copied from qat.log."""

from __future__ import annotations

import csv
from datetime import UTC, datetime

import pytest

from qat.domain.backtester.costs import CostModel
from qat.domain.performance.fill_basis_repair import (
    SelfCheckFailed,
    evidence_for,
    parse_logged_buys,
    parse_m65_corrections,
    repair_closed_rows,
    repair_open_records,
)
from qat.domain.performance.trades import _FIELDS, ClosedTrade, audit_closed_trades

_COSTS = CostModel(commission_bps=8.8, slippage_bps=5.0, min_commission=6.60)

_M65 = (
    "Corrected the recorded entry price for BHP.AX -> 64.1264 to what the broker charged. "
    "The record held the price the order was SIZED against, not the price it filled at, so "
    "P&L and every R-multiple on these was wrong by that difference."
)
_M65_PAIR = (
    "Corrected the recorded entry price for RHC.AX -> 44.4523, TNE.AX -> 32.9783 to what the "
    "broker charged. The record held the price the order was SIZED against."
)


def _exec(exec_id: str, symbol: str, shares: float, price: float, perm: int, side="BOT") -> str:
    return (
        f"execDetails: Fill(contract=Stock(conId=12565187, symbol='{symbol}', exchange='SMART', "
        f"currency='AUD', localSymbol='{symbol}', tradingClass='{symbol}'), "
        f"execution=Execution(execId='{exec_id}', time=datetime.datetime(2026, 8, 24, 18, 5, 24, "
        f"tzinfo=datetime.timezone.utc), acctNumber='DUQ200898', exchange='SMART', side='{side}', "
        f"shares={shares}, price={price}, permId={perm}, clientId=1, orderId=417, liquidation=0, "
        f"cumQty={shares}, avgPrice={price}, orderRef='')"
    )


def _row(**overrides) -> dict[str, str]:
    trade = ClosedTrade(
        symbol="BHP.AX",
        strategy="swing",
        quantity=793.0,
        entry_price=64.1263816,
        exit_price=60.40,
        stop_price=60.45,
        opened_at=datetime(2026, 9, 9, 4, 5, 11, tzinfo=UTC),
        closed_at=datetime(2026, 9, 11, 0, 0, tzinfo=UTC),
        entry_cost=70.18,
        exit_cost=66.10,
        reference_price=64.08000183,
        worst_price=60.40,
        best_price=64.9,
        order_id="750830217",
        market="ASX",
        currency="AUD",
    )
    row = {k: str(v) for k, v in trade.as_row().items()}
    row.update(overrides)
    return row


def test_the_m65_line_is_parsed_into_the_strings_it_wrote():
    found = parse_m65_corrections([_M65, _M65_PAIR, "unrelated"])
    assert found == {"BHP.AX": {"64.1264"}, "RHC.AX": {"44.4523"}, "TNE.AX": {"32.9783"}}


def test_logged_buys_are_totalled_per_order_and_sells_ignored():
    buys = parse_logged_buys(
        [
            _exec("x1", "RHC", 1.0, 44.41, 1216558923),
            _exec("x2", "RHC", 100.0, 44.41, 1216558923),
            _exec("x3", "RHC", 50.0, 44.50, 1216558999, side="SLD"),
        ],
        market="ASX",
    )
    assert len(buys) == 1
    assert (buys[0].symbol, buys[0].quantity) == ("RHC.AX", 101.0)
    assert buys[0].average_price == pytest.approx(44.41)


def test_no_m65_line_means_no_evidence():
    assert evidence_for("BHP.AX", 64.1263816, 793.0, {}, [], _COSTS) is None


def test_without_a_logged_fill_the_formula_is_the_evidence():
    ev = evidence_for("BHP.AX", 64.1263816, 793.0, {"BHP.AX": {"64.1264"}}, [], _COSTS)
    assert ev is not None
    assert ev.fill == pytest.approx(64.07, abs=1e-6)
    assert ev.order_quantity is None


def test_a_logged_fill_that_reproduces_is_preferred():
    buys = parse_logged_buys([_exec("x1", "BHP", 793.0, 64.07, 1)], market="ASX")
    ev = evidence_for("BHP.AX", 64.1263816, 793.0, {"BHP.AX": {"64.1264"}}, buys, _COSTS)
    assert ev is not None
    assert ev.fill == 64.07
    assert ev.order_quantity == 793.0
    assert "logged" in ev.source


def test_the_self_check_refuses_when_no_logged_fill_reproduces():
    buys = parse_logged_buys([_exec("x1", "BHP", 793.0, 63.00, 1)], market="ASX")
    with pytest.raises(SelfCheckFailed):
        evidence_for("BHP.AX", 64.1263816, 793.0, {"BHP.AX": {"64.1264"}}, buys, _COSTS)


def test_the_bhp_row_is_restored_and_charged_commission_only():
    [repair] = repair_closed_rows([_row()], {"BHP.AX": {"64.1264"}}, [], _COSTS)

    after = repair.after
    assert after.entry_price == pytest.approx(64.07, abs=1e-6)
    assert after.entry_cost == pytest.approx(_COSTS.charge(793 * 64.07))
    assert after.exit_cost == pytest.approx(_COSTS.charge(793 * 60.40))
    assert after.entry_slippage == pytest.approx(-0.01, abs=1e-4)  # was +0.0464


def test_a_row_without_evidence_keeps_its_price_but_loses_its_slippage():
    [repair] = repair_closed_rows([_row()], {}, [], _COSTS)

    assert repair.after.entry_price == pytest.approx(64.1263816)
    assert repair.evidence is None
    assert repair.after.exit_cost == pytest.approx(_COSTS.charge(793 * 60.40))


def test_one_exit_order_across_rows_pays_one_floor():
    small = CostModel(commission_bps=8.8, slippage_bps=5.0, min_commission=6.60)
    rows = [
        _row(quantity="10.0", entry_price="20.0", stop_price="18.0", exit_price="21.0"),
        _row(quantity="15.0", entry_price="20.0", stop_price="18.0", exit_price="21.0"),
    ]
    repairs = repair_closed_rows(rows, {}, [], small)

    # 25 x 21 = 525 of notional: one 6.60 floor for the order, split 10:15.
    assert sum(r.after.exit_cost for r in repairs) == pytest.approx(6.60)


def test_a_fragment_is_charged_its_share_and_never_a_whole_floor():
    """TNE.AX: 60 shares of a 3,051-share entry; the rest left another way."""
    buys = parse_logged_buys([_exec("t1", "TNE", 3051.0, 32.94925926, 509334698)], market="ASX")
    row = _row(
        symbol="TNE.AX",
        quantity="60.0",
        entry_price="32.9783",
        stop_price="30.0",
        exit_price="30.6858",
        order_id="509334700",
        reference_price="",
        worst_price="30.6858",
        best_price="33.5",
    )
    [repair] = repair_closed_rows([row], {"TNE.AX": {"32.9783"}}, buys, _COSTS)

    assert repair.fragment
    assert repair.after.entry_cost == pytest.approx(_COSTS.charge(3051 * 32.94925926) * 60 / 3051)
    assert repair.after.exit_cost == pytest.approx(60 * 30.6858 * 8.8 / 10_000)


def test_the_repaired_rows_pass_the_ledgers_own_audit(tmp_path):
    repairs = repair_closed_rows([_row()], {"BHP.AX": {"64.1264"}}, [], _COSTS)
    path = tmp_path / "closed_trades.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_FIELDS))
        writer.writeheader()
        writer.writerows(r.after.as_row() for r in repairs)

    assert audit_closed_trades(path) == []


def test_open_records_get_the_fill_and_the_stamp():
    records = {
        "BOQ.AX": {
            "opened_at": "2026-08-25T00:30:04+00:00",
            "price": 6.3856144,
            "stop_price": 6.07,
            "target_price": 7.05,
            "strategy": "swing",
            "reference_price": None,
        },
        "XYZ.AX": {
            "opened_at": "2026-08-25T00:30:04+00:00",
            "price": 10.0,
            "stop_price": 9.0,
            "target_price": None,
            "strategy": "swing",
            "reference_price": None,
        },
    }
    repaired, changes = repair_open_records(records, {"BOQ.AX": {"6.38561"}}, [], _COSTS)

    assert repaired["BOQ.AX"]["price"] == pytest.approx(6.38, abs=1e-6)
    assert repaired["BOQ.AX"]["price_source"] == "fill"
    assert repaired["XYZ.AX"] == records["XYZ.AX"]  # no evidence, untouched
    assert [c.symbol for c in changes] == ["BOQ.AX"]
