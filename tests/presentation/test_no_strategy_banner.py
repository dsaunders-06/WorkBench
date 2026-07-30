"""An app with nothing deployed must not claim it is trading (M27b).

The overnight session of 30 July ran to a flat account under AUTO-TRADE
ACTIVE. Afterwards the record could not distinguish "every strategy ran and
found no setup" from "no strategy was ever deployed" - nothing logged the
deployed set, nothing displayed it, and it does not survive a restart.
"""

from __future__ import annotations

import logging

from qat.config import Settings
from qat.domain.strategies.swing import SwingStrategy
from qat.presentation.main_window import MainWindow
from qat.presentation.runtime import Runtime


def _runtime(**overrides) -> Runtime:
    base = {"_env_file": None, "execution_mode": "auto", "autonomous_strategies": "swing"}
    base.update(overrides)
    return Runtime.build_demo(settings=Settings(**base))  # type: ignore[arg-type]


def test_the_banner_says_nothing_can_trade_when_nothing_is_deployed(qtbot):
    """Autonomy being enabled is moot with an empty deployed set: no signal can
    be produced by any code path, so promising that orders self-sign is
    promising something that cannot happen."""
    window = MainWindow(_runtime())
    qtbot.addWidget(window)

    text = window.execution_banner.text()

    assert "NO STRATEGY DEPLOYED" in text
    assert "AUTO-TRADE ACTIVE" not in text
    assert "Workbench" in text


def test_deploying_clears_the_banner_immediately(qtbot):
    runtime = _runtime()
    window = MainWindow(runtime)
    qtbot.addWidget(window)
    assert "NO STRATEGY DEPLOYED" in window.execution_banner.text()

    runtime.strategy_engine.deploy(SwingStrategy())

    assert "AUTO-TRADE ACTIVE" in window.execution_banner.text()


def test_undeploying_the_last_strategy_brings_the_banner_back(qtbot):
    runtime = _runtime()
    swing = SwingStrategy()
    runtime.strategy_engine.deploy(swing)
    window = MainWindow(runtime)
    qtbot.addWidget(window)
    assert "AUTO-TRADE ACTIVE" in window.execution_banner.text()

    runtime.strategy_engine.undeploy(swing)

    assert "NO STRATEGY DEPLOYED" in window.execution_banner.text()


def test_a_halt_still_outranks_an_empty_deployed_set(qtbot):
    """A halt is a decision needing a human. An empty deployed set is a
    configuration state - true, but not the thing to say first."""
    runtime = _runtime()
    window = MainWindow(runtime)
    qtbot.addWidget(window)

    runtime.kill_switch.trigger_manual("operator")

    assert "EXECUTION HALTED" in window.execution_banner.text()


async def test_the_engine_warns_at_startup_when_nothing_is_deployed(caplog):
    """The log has to answer this on its own: an unattended session is
    reviewed from the log, not from a screen nobody was watching."""
    runtime = _runtime()

    with caplog.at_level(logging.WARNING, logger="qat.domain.strategies.engine"):
        await runtime.strategy_engine.start()
        await runtime.strategy_engine.stop()

    assert "NO STRATEGY IS DEPLOYED" in caplog.text
    assert "not persisted" in caplog.text


async def test_the_engine_names_the_deployed_set_at_startup(caplog):
    runtime = _runtime()
    runtime.strategy_engine.deploy(SwingStrategy())

    with caplog.at_level(logging.INFO, logger="qat.domain.strategies.engine"):
        await runtime.strategy_engine.start()
        await runtime.strategy_engine.stop()

    assert "Deployed strategies: swing" in caplog.text


def test_deploying_is_logged_with_the_resulting_set(caplog):
    runtime = _runtime()

    with caplog.at_level(logging.INFO, logger="qat.domain.strategies.engine"):
        runtime.strategy_engine.deploy(SwingStrategy())

    assert "DEPLOYED swing" in caplog.text


def test_deploying_twice_is_a_no_op(caplog):
    runtime = _runtime()
    swing = SwingStrategy()
    runtime.strategy_engine.deploy(swing)

    with caplog.at_level(logging.INFO, logger="qat.domain.strategies.engine"):
        runtime.strategy_engine.deploy(swing)

    assert runtime.strategy_engine.strategies == [swing]
    assert "DEPLOYED" not in caplog.text
