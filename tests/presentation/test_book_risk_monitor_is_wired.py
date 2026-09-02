"""An engine that is written but never registered measures nothing.

M119 is the precedent: deployed, correct, and untested by anything for three
days because nothing exercised it. A monitor absent from the orchestrator's
register list would leave every reader on `None` forever while every unit test
passed.
"""

from __future__ import annotations

from qat.config import Settings
from qat.presentation.runtime import Runtime


def test_the_book_risk_monitor_is_built_and_registered(tmp_path):
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, data_dir=str(tmp_path)))

    assert runtime.book_risk_monitor is not None
    assert runtime.book_risk_monitor.name == "book-risk-monitor"

    names = [engine.name for engine in runtime.orchestrator._engines]
    assert "book-risk-monitor" in names, f"registered engines: {names}"


def test_it_shares_the_account_poller_rather_than_holding_a_broker(tmp_path):
    """⚠️ A second poller would double broker traffic to record the same
    number - EquityMonitor's own comment says so."""
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, data_dir=str(tmp_path)))

    assert runtime.book_risk_monitor.account_poller is runtime.account_poller
