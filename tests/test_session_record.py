"""Everything a post-mortem needs must survive the process (spec M20).

Before M20 a recommend-mode session left behind fills, an equity curve and a
report: enough to answer "what did I make", nothing to answer "why did it do
that". These tests pin the three records that were being lost - the
application log, the decision journal and the risk audit trail - plus the
bundle that gathers them.
"""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from qat.config import Settings
from qat.data.broker.mock_broker import MockBroker
from qat.domain.bus import EventBus
from qat.domain.decision_journal import JOURNAL_FILENAME, DecisionJournal
from qat.domain.oms.oms import OMS
from qat.domain.performance.session_export import export_session
from qat.domain.risk_engine.audit import AUDIT_FILENAME, AuditLog, RiskDecision
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch
from qat.logging import LOG_DIRNAME, LOG_FILENAME, configure_logging


@pytest.fixture(autouse=True)
def _restore_logging():
    yield
    logging.getLogger().handlers.clear()


# --- the application log -----------------------------------------------------


def test_logs_are_written_to_a_file_not_only_stdout(tmp_path):
    """The packaged build is --windowed, so it has no console: a stdout-only
    configuration discarded every line in the build actually shipped."""
    configure_logging("INFO", tmp_path)
    logging.getLogger("demo").warning("kill-switch tripped: %s", "daily loss")
    logging.shutdown()

    log_file = tmp_path / LOG_DIRNAME / LOG_FILENAME
    assert log_file.is_file()
    assert "kill-switch tripped: daily loss" in log_file.read_text(encoding="utf-8")


def test_log_lines_are_json_so_a_post_mortem_can_filter_them(tmp_path):
    configure_logging("INFO", tmp_path)
    logging.getLogger("demo").error("something went wrong")
    logging.shutdown()

    lines = (tmp_path / LOG_DIRNAME / LOG_FILENAME).read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[-1])
    assert record["level"] == "ERROR"
    assert record["message"] == "something went wrong"


def test_an_unwritable_log_directory_does_not_stop_the_application(tmp_path):
    """Degrading to stdout is acceptable; refusing to start is not."""
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")

    configure_logging("INFO", blocker)  # must not raise

    assert logging.getLogger().handlers  # stdout handler still installed


def test_no_data_dir_means_stdout_only(tmp_path):
    configure_logging("INFO", None)

    assert len(logging.getLogger().handlers) == 1


# --- the decision journal ----------------------------------------------------


def _oms(tmp_path, journal: DecisionJournal | None = None) -> OMS:
    settings = Settings(_env_file=None, data_dir=str(tmp_path))
    bus = EventBus()
    kill_switch = KillSwitch()
    risk_engine = RiskEngine(bus, kill_switch, settings=settings, audit_log=AuditLog())
    return OMS(MockBroker(seed=1), risk_engine, kill_switch, journal=journal)


def _candidate(symbol: str = "AAPL", side: str = "buy") -> OrderCandidate:
    return OrderCandidate(
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        price=100.0,
        atr=2.0,
        win_rate=0.55,
        win_loss_ratio=1.4,
        candidate_returns=pd.Series([0.01, -0.01, 0.02, -0.005, 0.01, 0.004, -0.002, 0.008]),
        strategy="trend_following",
    )


async def _submit(oms: OMS, candidate: OrderCandidate):
    return await oms.submit_order(
        candidate, equity=100_000.0, existing_weights={}, existing_returns={}
    )


def _journal_rows(tmp_path) -> list[dict[str, str]]:
    path = tmp_path / JOURNAL_FILENAME
    if not path.is_file():
        return []
    return list(pd.read_csv(path).fillna("").to_dict("records"))


async def test_a_proposed_order_is_journalled_in_recommend_mode(tmp_path):
    """The gap this closes: only the autonomous executor wrote here, so the
    default mode - the one an operator actually runs first - recorded nothing."""
    journal = DecisionJournal(tmp_path)
    oms = _oms(tmp_path, journal)

    await _submit(oms, _candidate())

    rows = _journal_rows(tmp_path)
    assert [r["outcome"] for r in rows] == ["proposed"]
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["strategy"] == "trend_following"


async def test_sign_off_is_journalled_with_the_operator(tmp_path):
    journal = DecisionJournal(tmp_path)
    oms = _oms(tmp_path, journal)
    order = await _submit(oms, _candidate())

    await oms.sign_off(order.order_id, "operator (blotter)")

    outcomes = {r["outcome"]: r for r in _journal_rows(tmp_path)}
    assert "signed_off" in outcomes
    assert outcomes["signed_off"]["entity_name"] == "operator (blotter)"


async def test_an_operator_rejection_is_journalled_with_its_reason(tmp_path):
    journal = DecisionJournal(tmp_path)
    oms = _oms(tmp_path, journal)
    order = await _submit(oms, _candidate())

    await oms.reject_order(order.order_id, "operator", "looks overextended")

    rejected = [r for r in _journal_rows(tmp_path) if r["outcome"] == "rejected_by_operator"]
    assert rejected and rejected[0]["reason"] == "looks overextended"


async def test_a_kill_switch_rejection_names_the_kill_switch(tmp_path):
    """A day with no orders and a day where the kill-switch blocked eleven are
    completely different states of the world."""
    journal = DecisionJournal(tmp_path)
    oms = _oms(tmp_path, journal)
    oms.kill_switch.trip("Manual trigger by test")

    await _submit(oms, _candidate())

    rows = _journal_rows(tmp_path)
    assert rows[0]["outcome"] == "rejected"
    assert "kill-switch" in rows[0]["reason"]


async def test_an_oms_without_a_journal_still_works(tmp_path):
    """Every pre-M20 caller builds one this way."""
    oms = _oms(tmp_path, journal=None)

    order = await _submit(oms, _candidate())

    assert order.status == "pending_signoff"
    assert not (tmp_path / JOURNAL_FILENAME).exists()


# --- the risk audit trail ----------------------------------------------------


def _decision(symbol: str = "AAPL", approved: bool = True) -> RiskDecision:
    return RiskDecision(
        symbol=symbol,
        approved=approved,
        final_shares=12.0 if approved else 0.0,
        reason="approved" if approved else "cash floor",
        inputs={"price": 100.0, "equity": 100_000.0},
        stop_price=95.0,
    )


def test_risk_decisions_are_appended_to_csv(tmp_path):
    log = AuditLog(tmp_path)

    log.record(_decision())
    log.record(_decision("MSFT", approved=False))

    frame = pd.read_csv(tmp_path / AUDIT_FILENAME)
    assert list(frame["symbol"]) == ["AAPL", "MSFT"]
    assert list(frame["approved"]) == [True, False]
    assert frame.loc[1, "reason"] == "cash floor"


def test_the_inputs_are_stored_as_json_so_new_rails_do_not_break_old_files(tmp_path):
    log = AuditLog(tmp_path)
    log.record(_decision())

    frame = pd.read_csv(tmp_path / AUDIT_FILENAME)
    assert json.loads(frame.loc[0, "inputs"])["equity"] == 100_000.0


def test_the_in_memory_read_path_is_unchanged(tmp_path):
    """The Risk Console and the AI context query this on a timer; neither
    should be re-parsing a file to do it."""
    log = AuditLog(tmp_path)
    log.record(_decision())
    log.record(_decision("MSFT", approved=False))

    assert len(log.entries()) == 2
    assert [d.symbol for d in log.rejections()] == ["MSFT"]


def test_an_audit_log_without_a_directory_stays_in_memory(tmp_path):
    log = AuditLog()

    log.record(_decision())

    assert len(log.entries()) == 1
    assert not list(tmp_path.iterdir())


# --- the export bundle -------------------------------------------------------


def _seed_artefacts(tmp_path: Path) -> None:
    (tmp_path / "closed_trades.csv").write_text("symbol,pnl\nAAPL,12.5\n", encoding="utf-8")
    (tmp_path / "equity_curve.csv").write_text("ts,equity\n2026-07-27,100000\n", encoding="utf-8")
    (tmp_path / JOURNAL_FILENAME).write_text("order_id,outcome\n1,proposed\n", encoding="utf-8")
    logs = tmp_path / LOG_DIRNAME
    logs.mkdir()
    (logs / LOG_FILENAME).write_text('{"message": "started"}\n', encoding="utf-8")
    (logs / f"{LOG_FILENAME}.1").write_text('{"message": "older"}\n', encoding="utf-8")


def test_the_export_gathers_the_artefacts_that_exist(tmp_path):
    _seed_artefacts(tmp_path)

    result = export_session(tmp_path)

    with zipfile.ZipFile(result.path) as bundle:
        names = set(bundle.namelist())
    assert "closed_trades.csv" in names
    assert "equity_curve.csv" in names
    assert f"{LOG_DIRNAME}/{LOG_FILENAME}" in names
    assert result.log_files == 2


def test_absent_artefacts_are_reported_not_treated_as_failures(tmp_path):
    """No autonomous decisions means no journal; that is normal."""
    _seed_artefacts(tmp_path)

    result = export_session(tmp_path)

    assert "risk_decisions.csv" in result.missing
    assert "closed_trades.csv" in result.included


def test_the_bundle_explains_itself(tmp_path):
    _seed_artefacts(tmp_path)

    result = export_session(tmp_path)

    with zipfile.ZipFile(result.path) as bundle:
        manifest = bundle.read("MANIFEST.txt").decode("utf-8")
    assert "closed_trades.csv - what was traded" in manifest
    assert "Not present" in manifest


def test_the_export_copies_rather_than_moves(tmp_path):
    """The session keeps writing to these files; an export that took them away
    would break the thing it was trying to explain."""
    _seed_artefacts(tmp_path)

    export_session(tmp_path)

    assert (tmp_path / "closed_trades.csv").is_file()
    assert (tmp_path / LOG_DIRNAME / LOG_FILENAME).is_file()


def test_exporting_an_empty_directory_still_produces_a_bundle(tmp_path):
    result = export_session(tmp_path)

    assert result.path.is_file()
    assert result.included == ()
    assert len(result.missing) > 0
