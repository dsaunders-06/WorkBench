"""The auto-trade strategy picker (spec M20).

It replaced a free-text comma-separated field. The point is not tidiness: a
typo there parsed cleanly, matched no strategy, and left the operator
believing a strategy had been cleared to trade unattended when it had not.
"""

from __future__ import annotations

from PySide6.QtCore import Qt

from qat.config import Settings
from qat.presentation.runtime import Runtime
from qat.presentation.settings import SettingsScreen


def _screen(qtbot, **settings_kwargs) -> SettingsScreen:
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, **settings_kwargs))
    screen = SettingsScreen(runtime)
    qtbot.addWidget(screen)
    return screen


def test_every_strategy_is_offered(qtbot):
    screen = _screen(qtbot)

    offered = {
        screen._strategy_model.item(row).text() for row in range(screen._strategy_model.rowCount())
    }

    assert offered == {s.name for s in screen.runtime.available_strategies}
    assert len(offered) == 15


def test_the_configured_strategies_start_checked(qtbot):
    screen = _screen(qtbot, autonomous_strategies="swing,value")

    assert sorted(screen.selected_strategies()) == ["swing", "value"]


def test_nothing_is_checked_by_default(qtbot):
    """Autonomy is earned per strategy; the default grants it to none."""
    screen = _screen(qtbot)

    assert screen.selected_strategies() == []
    assert "none" in screen.selected_strategies_label.text().lower()


def test_checking_a_strategy_updates_the_summary(qtbot):
    screen = _screen(qtbot)

    screen._strategy_model.item(0).setCheckState(Qt.CheckState.Checked)

    name = screen._strategy_model.item(0).text()
    assert screen.selected_strategies() == [name]
    assert name in screen.selected_strategies_label.text()


def test_save_writes_the_checked_strategies_as_a_comma_list(qtbot, monkeypatch):
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        "qat.presentation.settings.env_file.update_env_file",
        lambda updates: captured.update(updates),
    )
    screen = _screen(qtbot, autonomous_strategies="swing")
    screen._strategy_model.item(0).setCheckState(Qt.CheckState.Checked)

    screen._on_save_clicked()

    written = captured["QAT_AUTONOMOUS_STRATEGIES"].split(",")
    assert set(written) == set(screen.selected_strategies())


def test_unchecking_everything_writes_an_empty_value(qtbot, monkeypatch):
    """Empty means none, and must be expressible - otherwise autonomy could
    never be withdrawn once granted."""
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        "qat.presentation.settings.env_file.update_env_file",
        lambda updates: captured.update(updates),
    )
    screen = _screen(qtbot, autonomous_strategies="swing,value")
    for row in range(screen._strategy_model.rowCount()):
        screen._strategy_model.item(row).setCheckState(Qt.CheckState.Unchecked)

    screen._on_save_clicked()

    assert captured["QAT_AUTONOMOUS_STRATEGIES"] == ""


def test_a_name_that_matches_no_strategy_can_no_longer_be_entered(qtbot):
    """The failure the picker removes: the old free-text field accepted
    'trend-following' and silently cleared nothing."""
    screen = _screen(qtbot, autonomous_strategies="trend-following")

    assert screen.selected_strategies() == []
    assert not hasattr(screen, "autonomous_strategies_input")
