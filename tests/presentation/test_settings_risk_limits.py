"""The risk limits are visible and editable on the Settings screen (M36).

Every cap that governs which trades happen and how large they are was
configurable only by hand-editing the environment file, and shown on no screen
at all. An operator could not answer "what is my single-name limit" without
leaving the application.

The failure mode this file guards is arithmetic, not layout. The file stores
0.15 and an operator reasons in 15%, so the screen converts in both directions.
A percentage written where a fraction is expected would multiply every risk
limit in the system by one hundred, silently, and the application would start
cleanly on the result.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.presentation import settings as settings_module
from qat.presentation.runtime import Runtime
from qat.presentation.settings import SettingsScreen


def _screen(qtbot, settings: Settings | None = None) -> SettingsScreen:
    runtime = Runtime.build_demo(settings=settings or Settings(_env_file=None))
    screen = SettingsScreen(runtime)
    qtbot.addWidget(screen)
    return screen


def _capture_save(screen: SettingsScreen, monkeypatch) -> dict[str, str]:
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        settings_module.env_file,
        "update_env_file",
        lambda updates, path=None: captured.update(updates),
    )
    monkeypatch.setattr(settings_module.security, "set_secret", lambda name, value: None)
    screen._on_save_clicked()
    return captured


# --- The limits are actually on the screen ------------------------------------


def test_every_portfolio_limit_is_shown(qtbot):
    screen = _screen(qtbot)

    assert screen.per_trade_risk_input.value() == pytest.approx(1.0)  # 0.01 shown as 1%
    assert screen.aggregate_risk_input.value() == pytest.approx(5.0)
    assert screen.single_name_input.value() == pytest.approx(15.0)
    assert screen.sector_input.value() == pytest.approx(30.0)
    assert screen.cluster_pct_input.value() == pytest.approx(30.0)
    assert screen.cluster_threshold_input.value() == pytest.approx(0.70)
    assert screen.gap_budget_input.value() == pytest.approx(5.0)
    assert screen.max_positions_input.value() == 10


def test_the_churn_and_protection_settings_are_shown(qtbot):
    screen = _screen(qtbot)

    assert screen.min_hold_days_input.value() == 10
    assert screen.time_stop_days_input.value() == 30
    assert screen.entries_per_week_input.value() == 10
    assert screen.sweep_seconds_input.value() == 300
    assert screen.edge_min_trades_input.value() == 20
    assert screen.enforce_min_hold_check.isChecked() is True
    assert screen.enforce_time_stop_check.isChecked() is True


# --- What is written is what was meant ----------------------------------------


def test_a_percentage_on_screen_is_stored_as_a_fraction(qtbot, monkeypatch):
    """The whole hazard. Writing 15 where 0.15 belongs multiplies every limit
    by a hundred, and the application starts cleanly on the result."""
    screen = _screen(qtbot)
    screen.single_name_input.setValue(12.5)

    captured = _capture_save(screen, monkeypatch)

    assert captured["QAT_MAX_SINGLE_NAME_CONCENTRATION_PCT"] == "0.125"


def test_the_written_values_load_back_as_the_same_numbers(qtbot, monkeypatch, tmp_path):
    """The round trip, end to end: edit, save, and read the file back through
    Settings exactly as the next launch would."""
    screen = _screen(qtbot)
    screen.per_trade_risk_input.setValue(0.75)
    screen.aggregate_risk_input.setValue(4.0)
    screen.single_name_input.setValue(12.0)
    screen.sector_input.setValue(25.0)
    screen.cluster_pct_input.setValue(20.0)
    screen.cluster_threshold_input.setValue(0.65)
    screen.max_positions_input.setValue(8)
    screen.min_hold_days_input.setValue(15)
    screen.time_stop_days_input.setValue(45)
    screen.edge_min_trades_input.setValue(25)
    screen.enforce_time_stop_check.setChecked(False)

    captured = _capture_save(screen, monkeypatch)

    env = tmp_path / ".env"
    env.write_text("\n".join(f"{k}={v}" for k, v in captured.items() if v != ""), encoding="utf-8")
    reloaded = Settings(_env_file=str(env))

    assert reloaded.per_trade_risk_pct == pytest.approx(0.0075)
    assert reloaded.max_aggregate_risk_at_stop_pct == pytest.approx(0.04)
    assert reloaded.max_single_name_concentration_pct == pytest.approx(0.12)
    assert reloaded.max_sector_concentration_pct == pytest.approx(0.25)
    assert reloaded.max_correlated_cluster_pct == pytest.approx(0.20)
    assert reloaded.correlation_cluster_threshold == pytest.approx(0.65)
    assert reloaded.max_concurrent_positions == 8
    assert reloaded.min_holding_trading_days == 15
    assert reloaded.time_stop_trading_days == 45
    assert reloaded.edge_min_trades == 25
    assert reloaded.enforce_time_stop is False


def test_an_untouched_screen_writes_back_exactly_the_current_settings(qtbot, monkeypatch, tmp_path):
    """Opening Settings, changing nothing and pressing Save must not move a
    single limit - the most likely way this screen could do harm."""
    original = Settings(_env_file=None)
    screen = _screen(qtbot, original)

    captured = _capture_save(screen, monkeypatch)
    env = tmp_path / ".env"
    env.write_text("\n".join(f"{k}={v}" for k, v in captured.items() if v != ""), encoding="utf-8")
    reloaded = Settings(_env_file=str(env))

    for field in (
        "per_trade_risk_pct",
        "atr_stop_multiple",
        "kelly_fraction",
        "max_aggregate_risk_at_stop_pct",
        "max_single_name_concentration_pct",
        "max_sector_concentration_pct",
        "max_correlated_cluster_pct",
        "correlation_cluster_threshold",
        "max_gap_risk_at_shock_pct",
        "gap_shock_pct",
        "max_concurrent_positions",
        "portfolio_es_limit_pct",
        "daily_loss_limit_pct",
        "max_drawdown_limit_pct",
        "min_holding_trading_days",
        "time_stop_trading_days",
        "max_entries_per_week",
        "protection_sweep_seconds",
        "edge_min_trades",
        "enforce_min_holding_period",
        "enforce_time_stop",
        "max_cost_to_risk_pct",
        "delever_sweep_enabled",
        "min_holding_loss_escape_r",
    ):
        assert getattr(reloaded, field) == pytest.approx(getattr(original, field)), field


def test_the_selling_rail_is_shown_and_stays_off_by_default(qtbot):
    """The only rail here that sells uninvited. It must be visible, and opening
    the screen must not arm it."""
    screen = _screen(qtbot)

    assert screen.delever_sweep_check.isChecked() is False


def test_the_screen_cannot_produce_a_value_the_application_would_reject(qtbot):
    """per_trade_risk_pct is validated at 2% maximum. A spin box that allowed
    3% would write a file the next launch refuses to start on."""
    screen = _screen(qtbot)

    screen.per_trade_risk_input.setValue(99.0)

    assert screen.per_trade_risk_input.value() == pytest.approx(2.0)
