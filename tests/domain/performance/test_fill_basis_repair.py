"""The rewrite of records whose entry price is IBKR's commission-inclusive
average (M175). Fixtures only - never the live ledger. Log lines are the REAL
formats, copied from qat.log."""

from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import subprocess  # nosec B404 - the tests replace subprocess.run; nothing is executed
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from qat.config import Settings
from qat.domain.backtester.costs import CostModel
from qat.domain.performance.fill_basis_repair import (
    SelfCheckFailed,
    evidence_for,
    parse_logged_buys,
    parse_m65_corrections,
    prior_repair,
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
    rows = [
        _row(quantity="10.0", entry_price="20.0", stop_price="18.0", exit_price="21.0"),
        _row(quantity="15.0", entry_price="20.0", stop_price="18.0", exit_price="21.0"),
    ]
    repairs = repair_closed_rows(rows, {}, [], _COSTS)

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
    assert repair.after.entry_price == 32.94925926
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


_M65_LOV = (
    "Corrected the recorded entry price for LOV.AX -> 24.2214 to what the broker charged. "
    "The record held the price the order was SIZED against."
)
_LOV_QUANTITIES = (10.0, 15.0, 26.0, 323.0, 2843.0)


def _lov_rows() -> list[dict[str, str]]:
    """The live LOV.AX shape: one 3,217-share lot, closed by ONE exit order in
    five rows, the 2,843-share row with BLANK costs (the 26 August script)."""
    rows = [
        _row(
            symbol="LOV.AX",
            quantity=str(quantity),
            entry_price="24.2214",
            exit_price="28.45",
            stop_price="21.92",
            opened_at="2026-08-25T00:30:04+00:00",
            closed_at="2026-08-26T05:10:00+00:00",
            order_id="1216552509",
            reference_price="",
            worst_price="24.2214",
            best_price="28.6",
        )
        for quantity in _LOV_QUANTITIES
    ]
    rows[-1].update(entry_cost="", exit_cost="")
    return rows


def _lov_buy() -> str:
    return _exec("l1", "LOV", 3217.0, 24.20010569, 1216552400)


def test_the_live_lov_shape_repairs_to_a_ledger_that_passes_its_own_audit(tmp_path):
    """⚠️ The single-BHP-row audit test passed while the real 12 rows failed the
    same audit with 10 findings: five rows sharing one entry charge and one exit
    charge get FRACTIONAL cost shares, and `as_row` stored them at 2 dp while
    deriving net_pnl from the unrounded values."""
    buys = parse_logged_buys([_lov_buy()], market="ASX")
    repairs = repair_closed_rows(_lov_rows(), {"LOV.AX": {"24.2214"}}, buys, _COSTS)
    assert all(r.after.entry_price == 24.20010569 for r in repairs)
    assert not any(r.fragment for r in repairs)

    path = tmp_path / "closed_trades.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_FIELDS))
        writer.writeheader()
        writer.writerows(r.after.as_row() for r in repairs)

    assert audit_closed_trades(path) == []


def test_a_traded_extreme_near_the_seed_is_not_the_seed():
    """The seed is stored at 4 dp, so it sits within HALF A 4-DP UNIT (5e-5) of
    the entry - an absolute bound. RHC.AX's 44.4523 is the seed; 44.45 is
    0.0023 away, a price that really traded, and must survive the repair."""
    row = _row(
        symbol="RHC.AX",
        quantity="1194.0",
        entry_price="44.45230503",
        stop_price="42.0",
        exit_price="44.0",
        order_id="1216558924",
        reference_price="",
        worst_price="44.4523",
        best_price="44.45",
    )
    [repair] = repair_closed_rows([row], {"RHC.AX": {"44.4523"}}, [], _COSTS)

    fill = repair.after.entry_price
    assert fill == pytest.approx(44.4132, abs=1e-4)
    assert repair.after.best_price == 44.45  # traded - kept, and above the fill
    assert repair.after.worst_price == fill  # the seed - replaced


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
    # The stamp says OBSERVED, so only a logged fill earns it (the formula-only
    # case is the next test).
    buys = parse_logged_buys([_exec("b0", "BOQ", 2000.0, 6.38, 777000100)], market="ASX")
    repaired, changes, _left = repair_open_records(records, {"BOQ.AX": {"6.38561"}}, buys, _COSTS)

    assert repaired["BOQ.AX"]["price"] == pytest.approx(6.38, abs=1e-6)
    assert repaired["BOQ.AX"]["price_source"] == "fill"
    assert repaired["XYZ.AX"] == records["XYZ.AX"]  # no evidence, untouched
    assert [c.symbol for c in changes] == ["BOQ.AX"]


def test_a_formula_only_open_record_is_left_unchanged_for_m65_and_listed():
    """WOW.AX: an M65 line, but no logged execDetails fill (a manual TWS buy is
    never logged as one). The formula's answer is DERIVED - over a quantity the
    record does not hold - and stamping it "fill" would lock it there for good.
    It is left exactly as it is; the M175 build's M65 derives it at launch from
    the broker's real quantity."""
    records = {
        "WOW.AX": {
            "opened_at": "2026-09-01T00:30:04+00:00",
            "price": 33.52948,
            "stop_price": 31.2,
            "target_price": 36.4,
            "strategy": "swing",
            "reference_price": 33.51,
        },
    }
    before = json.dumps(records["WOW.AX"])

    repaired, changes, left = repair_open_records(records, {"WOW.AX": {"33.5295"}}, [], _COSTS)

    assert json.dumps(repaired["WOW.AX"]) == before  # byte-for-byte, and no stamp
    assert changes == []
    assert [c.symbol for c in left] == ["WOW.AX"]
    assert left[0].before == 33.52948
    assert left[0].after == pytest.approx(33.52948 / 1.00088)  # what the formula alone gives
    assert left[0].evidence.order_quantity is None


def test_an_open_record_with_a_logged_fill_takes_the_logged_average():
    """6.3801 x 2,000 is within $0.20 of what the formula gives (6.38), so it
    reproduces - and the LOGGED number, not the formula's, is what is written."""
    records = {
        "BOQ.AX": {
            "opened_at": "2026-08-25T00:30:04+00:00",
            "price": 6.3856144,
            "stop_price": 6.07,
            "target_price": 7.05,
            "strategy": "swing",
            "reference_price": None,
        },
    }
    buys = parse_logged_buys([_exec("b1", "BOQ", 2000.0, 6.3801, 777000111)], market="ASX")
    repaired, [change], _left = repair_open_records(
        records, {"BOQ.AX": {"6.38561"}}, buys, _COSTS
    )

    assert repaired["BOQ.AX"]["price"] == pytest.approx(6.3801, abs=1e-12)
    assert repaired["BOQ.AX"]["price_source"] == "fill"
    assert "777000111" in change.evidence.source


def test_of_several_logged_orders_the_one_that_reproduces_is_chosen():
    """The live TNE.AX shape: orders at ~32.44 for the symbol too, and only
    509334698 (3,051 at 32.94925926) is reproduced by 32.9783 / 1.00088."""
    buys = parse_logged_buys(
        [
            _exec("a1", "TNE", 1000.0, 32.44, 509334600),
            _exec("a2", "TNE", 500.0, 32.45, 509334650),
            _exec("t1", "TNE", 3051.0, 32.94925926, 509334698),
            _exec("a3", "TNE", 800.0, 32.43, 509334720),
        ],
        market="ASX",
    )
    ev = evidence_for("TNE.AX", 32.9783, 60.0, {"TNE.AX": {"32.9783"}}, buys, _COSTS)

    assert ev is not None
    assert ev.fill == 32.94925926
    assert ev.order_quantity == 3051.0
    assert "509334698" in ev.source


def test_one_lots_entry_charge_is_split_across_its_rows():
    """One entry order, two rows (the lot left in two exits): the rows' entry
    costs add up to ONE charge on the order, split by quantity."""
    buys = parse_logged_buys([_exec("e1", "BHP", 793.0, 64.07, 750830100)], market="ASX")
    rows = [
        _row(quantity="300.0", order_id="750830217"),
        _row(quantity="493.0", order_id="750830299"),
    ]
    repairs = repair_closed_rows(rows, {"BHP.AX": {"64.1264"}}, buys, _COSTS)

    one_charge = _COSTS.charge(793 * 64.07)
    assert sum(r.after.entry_cost for r in repairs) == pytest.approx(one_charge)
    assert repairs[0].after.entry_cost == pytest.approx(one_charge * 300 / 793)
    assert not any(r.fragment for r in repairs)


def test_a_row_with_empty_costs_is_fully_recomputed():
    """The live LOV.AX 2,843-share row carries blank entry_cost and exit_cost."""
    [repair] = repair_closed_rows([_row(entry_cost="", exit_cost="")], {}, [], _COSTS)

    assert repair.before.costs == 0.0
    assert repair.after.entry_cost == pytest.approx(_COSTS.charge(793 * 64.1263816))
    assert repair.after.exit_cost == pytest.approx(_COSTS.charge(793 * 60.40))


def test_without_a_logged_buy_a_floor_branch_fallback_is_refused():
    """10 shares of BHP.AX at ~64 is ~AUD 640 of notional - under the floor.
    With no logged order to size it against, that quantity cannot be trusted
    (a fragment whose entry order rotated out of the logs looks exactly like
    this), so no fill is derived from it."""
    with pytest.raises(SelfCheckFailed, match=r"BHP\.AX.*10.*floor"):
        repair_closed_rows([_row(quantity="10.0")], {"BHP.AX": {"64.1264"}}, [], _COSTS)


def test_an_excursion_seed_stored_at_four_decimals_is_still_the_seed():
    """RHC.AX: entry 44.45230503, best AND worst stored as 44.4523. Both are
    the untouched seed, so both become the fill - not a price that never
    traded."""
    row = _row(
        symbol="RHC.AX",
        quantity="1194.0",
        entry_price="44.45230503",
        stop_price="42.0",
        exit_price="44.0",
        order_id="1216558924",
        reference_price="",
        worst_price="44.4523",
        best_price="44.4523",
    )
    [repair] = repair_closed_rows([row], {"RHC.AX": {"44.4523"}}, [], _COSTS)

    fill = repair.after.entry_price
    assert fill == pytest.approx(44.45230503 / 1.00088)
    assert repair.after.best_price == fill
    assert repair.after.worst_price == fill


def test_a_real_excursion_tick_is_kept():
    row = _row(worst_price="60.40", best_price="64.9")
    [repair] = repair_closed_rows([row], {"BHP.AX": {"64.1264"}}, [], _COSTS)

    assert repair.after.best_price == 64.9
    assert repair.after.worst_price == 60.40


def test_rows_of_one_lot_with_different_entry_prices_are_refused():
    rows = [
        _row(quantity="10.0", entry_price="20.0", stop_price="18.0", exit_price="21.0"),
        _row(quantity="15.0", entry_price="20.5", stop_price="18.0", exit_price="21.0"),
    ]
    with pytest.raises(ValueError, match="entry price"):
        repair_closed_rows(rows, {}, [], _COSTS)


def test_a_matched_order_smaller_than_the_lot_is_refused():
    """500 at 64.07 reproduces 64.1263816 exactly - but the lot is 793 shares,
    so that order cannot be the whole of its entry."""
    buys = parse_logged_buys([_exec("e1", "BHP", 500.0, 64.07, 750830100)], market="ASX")
    with pytest.raises(SelfCheckFailed, match=r"793.*500|500.*793"):
        repair_closed_rows([_row()], {"BHP.AX": {"64.1264"}}, buys, _COSTS)


def _unrepaired_data_dir(tmp_path: Path) -> Path:
    (tmp_path / "closed_trades.csv").write_text("symbol\n", encoding="utf-8")
    (tmp_path / "open_position_entries.json").write_text(
        json.dumps(
            {
                "BOQ.AX": {"price": 6.3856144, "stop_price": 6.07},
                "SUN.AX": {"price": 18.69708745, "price_source": "reference"},
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_an_unrepaired_data_dir_has_no_prior_repair(tmp_path):
    assert prior_repair(_unrepaired_data_dir(tmp_path)) is None


def test_an_empty_data_dir_has_no_prior_repair(tmp_path):
    assert prior_repair(tmp_path) is None


@pytest.mark.parametrize("name", ["closed_trades.csv", "open_position_entries.json"])
def test_a_repair_backup_means_a_repair_already_happened(tmp_path, name):
    data = _unrepaired_data_dir(tmp_path)
    (data / f"{name}.bak-fill-basis-20260911-190501").write_text("x", encoding="utf-8")

    reason = prior_repair(data)

    assert reason is not None
    assert f"{name}.bak-fill-basis-20260911-190501" in reason


def test_an_open_record_stamped_fill_means_a_repair_already_happened(tmp_path):
    data = _unrepaired_data_dir(tmp_path)
    (data / "open_position_entries.json").write_text(
        json.dumps(
            {
                "BOQ.AX": {"price": 6.38, "price_source": "fill"},
                "SUN.AX": {"price": 18.69708745},
            }
        ),
        encoding="utf-8",
    )

    reason = prior_repair(data)

    assert reason is not None
    assert "BOQ.AX" in reason


def _script_module():
    """Load `scripts/repair_fill_basis.py` by path - it is a script, not a
    package - so the test runs the code the operator runs. Importing it runs
    nothing: `main` is behind the __main__ guard."""
    path = Path(__file__).resolve().parents[3] / "scripts" / "repair_fill_basis.py"
    spec = importlib.util.spec_from_file_location("qat_repair_fill_basis_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_tasklist(monkeypatch, tmp_path, returncode: int, stdout: str) -> None:
    (tmp_path / "System32").mkdir()
    (tmp_path / "System32" / "tasklist.exe").write_bytes(b"")
    monkeypatch.setenv("SystemRoot", str(tmp_path))

    def run(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="ERROR: x")

    monkeypatch.setattr(subprocess, "run", run)


def test_a_tasklist_that_fails_counts_as_the_app_running(monkeypatch, tmp_path, capsys):
    script = _script_module()
    _fake_tasklist(monkeypatch, tmp_path, returncode=1, stdout="")

    assert script._app_is_running() is True
    assert "failed" in capsys.readouterr().out


def test_a_tasklist_that_succeeds_without_the_app_means_not_running(monkeypatch, tmp_path):
    script = _script_module()
    _fake_tasklist(
        monkeypatch,
        tmp_path,
        returncode=0,
        stdout="INFO: No tasks are running which match the specified criteria.\n",
    )

    assert script._app_is_running() is False


# --- the script end to end, on a tmp_path data dir -------------------------

_OPEN_RECORDS = {
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
    # An M65 line and no logged fill: left for the M175 build's M65 (I1).
    "WOW.AX": {
        "opened_at": "2026-09-01T00:30:04+00:00",
        "price": 33.52948,
        "stop_price": 31.2,
        "target_price": 36.4,
        "strategy": "swing",
        "reference_price": 33.51,
    },
}


def _log_line(message: str) -> str:
    return json.dumps(
        {"ts": "2026-08-25T10:30:05+10:00", "level": "INFO", "logger": "x", "message": message}
    )


def _script_data_dir(tmp_path: Path, rows: list[dict[str, str]] | None = None) -> Path:
    data = tmp_path / "data"
    (data / "logs").mkdir(parents=True)
    with (data / "closed_trades.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_FIELDS))
        writer.writeheader()
        writer.writerows(_lov_rows() if rows is None else rows)
    (data / "open_position_entries.json").write_text(
        json.dumps(_OPEN_RECORDS, indent=2), encoding="utf-8"
    )
    (data / "logs" / "qat.log").write_text(
        "\n".join(
            _log_line(m)
            for m in (
                _M65_LOV,
                _lov_buy(),
                "Corrected the recorded entry price for BOQ.AX -> 6.38561, WOW.AX -> 33.5295 "
                "to what the broker charged.",
                _exec("b0", "BOQ", 2000.0, 6.38, 777000100),
            )
        )
        + "\n",
        encoding="utf-8",
    )
    return data


def _snapshot(data: Path) -> dict[str, bytes]:
    return {str(p.relative_to(data)): p.read_bytes() for p in data.rglob("*") if p.is_file()}


def _backups(data: Path) -> list[str]:
    return sorted(p.name for p in data.glob("*.bak-fill-basis-*"))


def _pointed_at(monkeypatch, data: Path, *argv: str):
    """The script, aimed at `data` - never the live dir - with the app closed."""
    script = _script_module()
    monkeypatch.setattr(
        script, "Settings", lambda: Settings(_env_file=None, data_dir=str(data), market="ASX")
    )
    monkeypatch.setattr(script, "_app_is_running", lambda: False)
    monkeypatch.setattr(sys, "argv", ["repair_fill_basis.py", *argv])
    return script


def _run(monkeypatch, data: Path, *argv: str) -> int:
    return int(_pointed_at(monkeypatch, data, *argv).main())


def _locked(src, dst):
    raise PermissionError(13, "The process cannot access the file", str(dst))


def test_the_dry_run_audits_the_repair_and_writes_nothing(monkeypatch, tmp_path, capsys):
    data = _script_data_dir(tmp_path)
    before = _snapshot(data)

    assert _run(monkeypatch, data) == 0

    out = capsys.readouterr().out
    assert "audit: clean" in out
    assert "DRY RUN" in out
    assert _snapshot(data) == before  # byte-identical, and no file added
    assert _backups(data) == []


def test_the_dry_run_lists_corrected_and_left_for_m65_records_apart(
    monkeypatch, tmp_path, capsys
):
    data = _script_data_dir(tmp_path)

    assert _run(monkeypatch, data) == 0

    out = capsys.readouterr().out
    corrected = out.split("corrected from a logged fill", 1)[1].split("left for M65", 1)[0]
    left = out.split("left for M65", 1)[1].split("unchanged - no M65 line", 1)[0]
    assert "BOQ.AX" in corrected and "777000100" in corrected
    assert "WOW.AX" not in corrected
    assert "WOW.AX" in left and "BOQ.AX" not in left


def test_a_dry_run_whose_repair_fails_the_audit_exits_1(monkeypatch, tmp_path, capsys):
    """⚠️ The dry run used to return BEFORE the audit, so the operator's dry run
    looked clean and the refusal appeared only at --apply."""
    data = _script_data_dir(tmp_path)
    before = _snapshot(data)
    script = _pointed_at(monkeypatch, data)
    audited: list[Path] = []

    def failing_audit(path: Path) -> list[str]:
        audited.append(path)
        assert path.exists()
        return ["row 2 (LOV.AX): net_pnl stores 1.0 but computes to 2.0"]

    monkeypatch.setattr(script, "audit_closed_trades", failing_audit)

    assert script.main() == 1

    out = capsys.readouterr().out
    assert "net_pnl stores 1.0 but computes to 2.0" in out
    [probe] = audited
    assert data not in probe.parents  # the probe was OUTSIDE the data dir
    assert not probe.parent.exists()  # and its temp dir is gone
    assert _snapshot(data) == before


def test_apply_rewrites_both_files_and_a_second_run_is_refused(monkeypatch, tmp_path, capsys):
    data = _script_data_dir(tmp_path)

    assert _run(monkeypatch, data, "--apply") == 0

    assert len(_backups(data)) == 2
    assert audit_closed_trades(data / "closed_trades.csv") == []
    with (data / "closed_trades.csv").open(newline="", encoding="utf-8") as handle:
        stored = [ClosedTrade.from_row(row) for row in csv.DictReader(handle)]
    assert [t.entry_price for t in stored if t is not None] == [24.20010569] * 5
    records = json.loads((data / "open_position_entries.json").read_text(encoding="utf-8"))
    assert records["BOQ.AX"]["price_source"] == "fill"
    assert records["BOQ.AX"]["price"] == pytest.approx(6.38, abs=1e-6)
    assert records["XYZ.AX"] == _OPEN_RECORDS["XYZ.AX"]
    assert records["WOW.AX"] == _OPEN_RECORDS["WOW.AX"]  # formula-only: left for M65
    assert not list(data.glob("*.tmp-*"))
    capsys.readouterr()

    after_first = _snapshot(data)
    assert _run(monkeypatch, data, "--apply") == 1
    assert "REFUSING" in capsys.readouterr().out
    assert _run(monkeypatch, data) == 1  # the dry run refuses too
    assert _snapshot(data) == after_first


def test_an_unparseable_row_is_a_refusal_not_a_traceback(monkeypatch, tmp_path, capsys):
    rows = _lov_rows()
    rows[1]["entry_price"] = "not-a-number"
    data = _script_data_dir(tmp_path, rows)
    before = _snapshot(data)

    assert _run(monkeypatch, data, "--apply") == 1

    assert "row 3 cannot be parsed" in capsys.readouterr().out
    assert _snapshot(data) == before


def test_a_lot_with_two_entry_prices_is_a_refusal_not_a_traceback(monkeypatch, tmp_path, capsys):
    rows = _lov_rows()
    rows[1]["entry_price"] = "24.3"
    data = _script_data_dir(tmp_path, rows)
    before = _snapshot(data)

    assert _run(monkeypatch, data) == 1

    assert "different entry prices" in capsys.readouterr().out
    assert _snapshot(data) == before


def test_a_failed_first_replace_leaves_no_backup_behind(monkeypatch, tmp_path, capsys):
    """A backup is how `prior_repair` recognises a completed repair - one left
    by a run that replaced nothing would block every later run, falsely."""
    data = _script_data_dir(tmp_path)
    before = _snapshot(data)
    script = _pointed_at(monkeypatch, data, "--apply")
    monkeypatch.setattr(script.os, "replace", _locked)

    assert script.main() == 1

    assert "REPLACE FAILED" in capsys.readouterr().out
    assert _backups(data) == []
    assert _snapshot(data) == before
    assert prior_repair(data) is None


def _second_copy_raises(monkeypatch, script, error: BaseException) -> None:
    real_copy2 = shutil.copy2
    calls: list[Path] = []

    def copy2(src, dst):
        calls.append(Path(dst))
        if len(calls) == 2:
            Path(dst).write_bytes(b"half a backup")  # a partial copy is this run's too
            raise error
        return real_copy2(src, dst)

    monkeypatch.setattr(script.shutil, "copy2", copy2)


def test_a_failed_backup_leaves_no_backup_behind(monkeypatch, tmp_path, capsys):
    data = _script_data_dir(tmp_path)
    before = _snapshot(data)
    script = _pointed_at(monkeypatch, data, "--apply")
    _second_copy_raises(monkeypatch, script, OSError(28, "No space left on device"))

    assert script.main() == 1

    assert "BACKUP FAILED" in capsys.readouterr().out
    assert _backups(data) == []
    assert _snapshot(data) == before


def test_an_interrupt_before_the_first_replace_leaves_no_backup_behind(monkeypatch, tmp_path):
    data = _script_data_dir(tmp_path)
    before = _snapshot(data)
    script = _pointed_at(monkeypatch, data, "--apply")
    _second_copy_raises(monkeypatch, script, KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        script.main()

    assert _backups(data) == []
    assert _snapshot(data) == before


def test_a_backup_that_cannot_be_deleted_is_named_to_the_operator(monkeypatch, tmp_path, capsys):
    data = _script_data_dir(tmp_path)
    script = _pointed_at(monkeypatch, data, "--apply")
    real_unlink = Path.unlink

    def unlink(self, missing_ok=False):
        if ".bak-fill-basis-" in self.name:
            raise PermissionError(13, "Access is denied", str(self))
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(script.os, "replace", _locked)
    monkeypatch.setattr(Path, "unlink", unlink)

    assert script.main() == 1

    out = capsys.readouterr().out
    left = _backups(data)
    assert len(left) == 2
    instruction = out.split("delete these by hand", 1)[-1]
    assert instruction != out, "the operator must be TOLD to delete them"
    for name in left:
        assert name in instruction
