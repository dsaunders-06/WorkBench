from __future__ import annotations

from qat.config import Settings


def test_defaults_are_safe():
    settings = Settings(_env_file=None)
    assert settings.trading_mode == "paper"
    assert settings.is_live is False
    assert settings.storage_backend == "sqlite"


def test_trading_mode_can_be_overridden_via_env(monkeypatch):
    monkeypatch.setenv("QAT_TRADING_MODE", "live")
    settings = Settings(_env_file=None)
    assert settings.trading_mode == "live"
    assert settings.is_live is True


def test_risk_limits_have_paper_defaults():
    settings = Settings(_env_file=None)
    assert settings.per_trade_risk_pct == 0.01
    assert settings.kelly_fraction == 0.5
    assert settings.atr_stop_multiple == 2.5
