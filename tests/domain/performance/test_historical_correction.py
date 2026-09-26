from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from qat.application_lock import ApplicationLock, ApplicationLockUnavailable
from qat.domain.performance import historical_correction
from qat.domain.performance.historical_correction import (
    CorrectionRefused,
    apply_correction,
    prepare_correction,
)
from qat.domain.performance.trades import audit_closed_trades

_ORIGINAL = {
    "opened_at": "2026-08-24T05:19:36+00:00",
    "closed_at": "2026-09-03T02:32:31+00:00",
    "symbol": "TNE.AX",
    "strategy": "swing",
    "quantity": "60.0",
    "entry_price": "32.94925926",
    "exit_price": "30.6858",
    "stop_price": "30.69",
    "gross_pnl": "-135.81",
    "entry_cost": "1.74",
    "exit_cost": "1.62",
    "net_pnl": "-139.17",
    "pnl_pct": "-0.070395",
    "r_multiple": "-1.0266",
    "gross_r_multiple": "-1.0019",
    "regime_at_entry": "",
    "regime_probability": "",
    "exposure_scalar": "",
    "exit_reason": "target",
    "holding_days": "9.884",
    "entry_slippage": "",
    "mae_r": "-1.002",
    "mfe_r": "0.0",
    "risk_per_share": "2.25925926",
    "reference_price": "",
    "worst_price": "30.6858",
    "best_price": "32.94925926",
    "earnings_at_entry": "",
    "held_through_earnings": "",
    "market": "ASX",
    "currency": "AUD",
    "order_id": "509334700",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare(proposal: Path, statement: Path, ledger: Path):
    return prepare_correction(proposal, statement, ledger, _sha(proposal))


def _evidence(tmp_path: Path, rows: list[dict[str, str]] | None = None):
    statement = tmp_path / "statement.pdf"
    statement.write_bytes(b"broker statement fixture")
    ledger = tmp_path / "closed_trades.csv"
    with ledger.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_ORIGINAL))
        writer.writeheader()
        writer.writerows(rows or [_ORIGINAL])
    proposal = tmp_path / "proposal.json"
    proposal.write_text(
        json.dumps(
            {
                "status": "PROPOSED_ONLY_NOT_APPLIED",
                "statement_sha256": _sha(statement),
                "ledger_sha256": _sha(ledger),
                "match": {
                    "symbol": "TNE.AX",
                    "ledger_order_id": "509334700",
                    "opened_at": "2026-08-24T05:19:36+00:00",
                },
                "original_ledger_row": _ORIGINAL,
                "broker_statement_values": {
                    "quantity": "3051",
                    "entry_price": "32.949259259",
                    "exit_price": "30.685817765",
                    "entry_commission": "88.46",
                    "exit_commission": "82.39",
                    "realised_net_pnl": "-7076.61",
                },
            }
        ),
        encoding="utf-8",
    )
    return proposal, statement, ledger


def test_prepares_one_broker_supported_correction_and_recalculates_the_row(tmp_path):
    proposal, statement, ledger = _evidence(tmp_path)

    plan = _prepare(proposal, statement, ledger)

    assert plan.original_row == _ORIGINAL
    assert plan.corrected_row["quantity"] == 3051.0
    assert plan.corrected_row["entry_price"] == 32.94925926
    assert plan.corrected_row["exit_price"] == 30.68581776
    assert plan.corrected_row["entry_cost"] == 88.46
    assert plan.corrected_row["exit_cost"] == 82.39
    assert plan.corrected_row["gross_pnl"] == -6905.76
    assert plan.corrected_row["net_pnl"] == -7076.61
    assert plan.corrected_row["pnl_pct"] == -0.070394
    assert plan.corrected_row["r_multiple"] == -1.0266
    assert plan.corrected_row["gross_r_multiple"] == -1.0019
    assert plan.corrected_row["strategy"] == "swing"
    assert plan.corrected_row["exit_reason"] == ""
    assert plan.provenance["strategy"] == "preserved from original ledger; not statement-verified"
    assert plan.provenance["exit_reason"] == "cleared because the statement does not verify it"


@pytest.mark.parametrize("changed", ["statement", "ledger"])
def test_refuses_any_evidence_hash_mismatch(tmp_path, changed):
    proposal, statement, ledger = _evidence(tmp_path)
    target = statement if changed == "statement" else ledger
    target.write_bytes(target.read_bytes() + b"changed")

    with pytest.raises(CorrectionRefused, match=f"{changed} SHA-256"):
        _prepare(proposal, statement, ledger)


def test_refuses_a_proposal_other_than_the_explicitly_approved_hash(tmp_path):
    proposal, statement, ledger = _evidence(tmp_path)

    with pytest.raises(CorrectionRefused, match="approved proposal SHA-256"):
        prepare_correction(proposal, statement, ledger, "0" * 64)


def test_refuses_an_ambiguous_target_even_when_the_ledger_hash_is_authorised(tmp_path):
    proposal, statement, ledger = _evidence(tmp_path, [_ORIGINAL, _ORIGINAL])

    with pytest.raises(CorrectionRefused, match="exactly one original row"):
        _prepare(proposal, statement, ledger)


def test_apply_backs_up_exact_bytes_writes_a_journal_and_refuses_repetition(tmp_path):
    proposal, statement, ledger = _evidence(tmp_path)
    before = ledger.read_bytes()
    plan = _prepare(proposal, statement, ledger)

    result = apply_correction(plan)

    assert result.backup_path.read_bytes() == before
    journal = json.loads(result.journal_path.read_text(encoding="utf-8"))
    assert journal["correction_id"] == plan.correction_id
    assert journal["before_sha256"] == plan.ledger_sha256
    assert journal["after_sha256"] == _sha(ledger)
    assert journal["provenance"] == plan.provenance
    assert audit_closed_trades(ledger) == []
    with ledger.open(newline="", encoding="utf-8") as handle:
        [corrected] = list(csv.DictReader(handle))
    assert corrected["quantity"] == "3051.0"
    assert corrected["net_pnl"] == "-7076.61"
    assert corrected["exit_reason"] == ""

    with pytest.raises(CorrectionRefused, match="already exists"):
        apply_correction(plan)


def test_apply_refuses_if_the_ledger_changed_after_validation(tmp_path):
    proposal, statement, ledger = _evidence(tmp_path)
    plan = _prepare(proposal, statement, ledger)
    ledger.write_bytes(ledger.read_bytes() + b"\n")

    with pytest.raises(CorrectionRefused, match="changed after validation"):
        apply_correction(plan)


def test_apply_restores_original_if_post_write_verification_fails(tmp_path, monkeypatch):
    proposal, statement, ledger = _evidence(tmp_path)
    before = ledger.read_bytes()
    plan = _prepare(proposal, statement, ledger)
    audits = 0

    def fail_only_after_replace(path: Path) -> list[str]:
        nonlocal audits
        audits += 1
        return [] if audits == 1 else ["simulated post-write failure"]

    monkeypatch.setattr(historical_correction, "audit_closed_trades", fail_only_after_replace)

    with pytest.raises(CorrectionRefused, match="post-write ledger verification failed"):
        apply_correction(plan)

    assert ledger.read_bytes() == before
    assert not list(tmp_path.glob("*.bak-pre-*"))
    assert not list(tmp_path.glob("*.correction-*.json"))


def test_cli_defaults_to_a_read_only_dry_run(tmp_path, monkeypatch, capsys):
    proposal, statement, ledger = _evidence(tmp_path)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    script_path = Path(__file__).parents[3] / "scripts" / "apply_historical_correction.py"
    spec = importlib.util.spec_from_file_location("qat_historical_correction_script", script_path)
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(script, "APPROVED_PROPOSAL_SHA256", _sha(proposal))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script_path),
            "--proposal",
            str(proposal),
            "--statement",
            str(statement),
            "--ledger",
            str(ledger),
        ],
    )

    assert script.main() == 0

    output = capsys.readouterr().out
    assert "DRY RUN" in output
    assert "60.0 -> 3051.0" in output
    assert "-139.17 -> -7076.61" in output
    assert "nothing written" in output
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_cli_apply_requires_the_id_printed_by_the_reviewed_dry_run(tmp_path, monkeypatch, capsys):
    proposal, statement, ledger = _evidence(tmp_path)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    script_path = Path(__file__).parents[3] / "scripts" / "apply_historical_correction.py"
    spec = importlib.util.spec_from_file_location("qat_historical_apply_guard_script", script_path)
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(script, "APPROVED_PROPOSAL_SHA256", _sha(proposal))
    monkeypatch.setattr(
        script,
        "ApplicationLock",
        lambda *args: pytest.fail("lock must not be acquired before confirmation"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script_path),
            "--proposal",
            str(proposal),
            "--statement",
            str(statement),
            "--ledger",
            str(ledger),
            "--apply",
        ],
    )

    assert script.main() == 1

    assert "requires --confirm-correction-id" in capsys.readouterr().out
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def _cli(tmp_path, monkeypatch, *, apply=True):
    proposal, statement, ledger = _evidence(tmp_path)
    script_path = Path(__file__).parents[3] / "scripts" / "apply_historical_correction.py"
    spec = importlib.util.spec_from_file_location("qat_correction_lock_script", script_path)
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(script, "APPROVED_PROPOSAL_SHA256", _sha(proposal))
    lock_path = tmp_path / "application.lock"
    argv = [
        str(script_path),
        "--proposal",
        str(proposal),
        "--statement",
        str(statement),
        "--ledger",
        str(ledger),
        "--application-lock",
        str(lock_path),
    ]
    if apply:
        argv += [
            "--apply",
            "--confirm-correction-id",
            _prepare(proposal, statement, ledger).correction_id,
        ]
    monkeypatch.setattr(sys, "argv", argv)
    return script, proposal, statement, ledger, lock_path


def test_cli_dry_run_does_not_acquire_lock(tmp_path, monkeypatch, capsys):
    script, _, _, ledger, lock_path = _cli(tmp_path, monkeypatch, apply=False)
    before = ledger.read_bytes()
    monkeypatch.setattr(script, "ApplicationLock", lambda *args: pytest.fail("dry run locked"))
    with ApplicationLock(lock_path):
        assert script.main() == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert ledger.read_bytes() == before


def test_cli_apply_refuses_child_owner_before_backup_or_staging(tmp_path, monkeypatch, capsys):
    script, _, _, ledger, lock_path = _cli(tmp_path, monkeypatch)
    before = ledger.read_bytes()
    ready = tmp_path / "owner.ready"
    code = """
import sys
from pathlib import Path
from qat.application_lock import ApplicationLock
with ApplicationLock(Path(sys.argv[1])):
    Path(sys.argv[2]).write_text('ready')
    sys.stdin.read()
"""
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(lock_path), str(ready)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "child did not acquire lock"
        snapshot = {
            path.name: path.read_bytes() for path in tmp_path.iterdir() if path != lock_path
        }
        monkeypatch.setattr(
            script, "write_candidate_for_audit", lambda *args: pytest.fail("staged")
        )
        monkeypatch.setattr(script, "apply_correction", lambda *args: pytest.fail("applied"))
        assert script.main() == 1
        assert "operational-data lock" in capsys.readouterr().out
        assert {
            path.name: path.read_bytes() for path in tmp_path.iterdir() if path != lock_path
        } == snapshot
        assert ledger.read_bytes() == before
    finally:
        try:
            child.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill()
            child.communicate(timeout=15)
    assert child.returncode == 0
    with ApplicationLock(lock_path):
        pass


@pytest.mark.parametrize("changed", ["proposal", "statement", "ledger"])
def test_cli_apply_revalidates_all_evidence_after_acquiring_lock(
    tmp_path, monkeypatch, capsys, changed
):
    script, proposal, statement, ledger, lock_path = _cli(tmp_path, monkeypatch)
    target = {"proposal": proposal, "statement": statement, "ledger": ledger}[changed]

    class ChangedWhileAcquiring(ApplicationLock):
        def acquire(self):
            super().acquire()
            target.write_bytes(target.read_bytes() + b" ")

    monkeypatch.setattr(script, "ApplicationLock", ChangedWhileAcquiring)
    assert script.main() == 1
    assert "SHA-256" in capsys.readouterr().out
    assert not list(tmp_path.glob("*.bak-pre-*"))
    assert not list(tmp_path.glob("*.tmp*"))
    assert not list(tmp_path.glob("*.correction-*.json"))
    with ApplicationLock(lock_path):
        pass


def test_cli_apply_holds_lock_through_staging_backup_replace_and_audit(tmp_path, monkeypatch):
    script, _, _, ledger, lock_path = _cli(tmp_path, monkeypatch)
    events = []

    def guard(function, name):
        def wrapped(*args, **kwargs):
            with pytest.raises(ApplicationLockUnavailable), ApplicationLock(lock_path):
                pass
            events.append(name)
            return function(*args, **kwargs)

        return wrapped

    monkeypatch.setattr(
        historical_correction, "_write_synced", guard(historical_correction._write_synced, "write")
    )
    monkeypatch.setattr(
        historical_correction.os, "replace", guard(historical_correction.os.replace, "replace")
    )
    monkeypatch.setattr(
        historical_correction,
        "audit_closed_trades",
        guard(historical_correction.audit_closed_trades, "audit"),
    )
    assert script.main() == 0
    assert events == ["write", "audit", "write", "write", "replace", "audit", "replace"]
    assert audit_closed_trades(ledger) == []
    with ApplicationLock(lock_path):
        pass
