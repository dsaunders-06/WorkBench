"""The optional Phase 3 producer is registered without enabling card actions."""

from qat.config import Settings
from qat.data.macro_fred import FredMacroSource
from qat.operational.shadow import Phase3ShadowRunner
from qat.presentation.cards_panel import RecommendationCardsPanel
from qat.presentation.main_window import MainWindow
from qat.presentation.runtime import Runtime


def test_shadow_off_by_default():
    runtime = Runtime.build_demo(Settings(_env_file=None, demo_mode=True))
    assert runtime.shadow_runner is None


def test_shadow_on_registers_daily_runner_and_read_only_panel(qtbot, tmp_path):
    settings = Settings(
        _env_file=None,
        broker="ibkr",
        ibkr_account_id="DU123456",
        market_data_source="yfinance",
        fundamentals_source="yfinance",
        data_dir=str(tmp_path / "data"),
        phase3_shadow_enabled=True,
        phase3_operational_root=str(tmp_path / "OPERATIONAL"),
        phase3_authorities_dir=str(tmp_path / "authorities"),
    )
    runtime = Runtime.build_demo(settings=settings, macro_source=FredMacroSource(api_key="test"))
    assert isinstance(runtime.shadow_runner, Phase3ShadowRunner)
    assert runtime.orchestrator._engines[-1] is runtime.shadow_runner
    window = MainWindow(runtime)
    qtbot.addWidget(window)
    panel = window.findChild(RecommendationCardsPanel)
    assert panel is not None and panel.read_only
    assert panel.service is None
