from __future__ import annotations

import pytest
from pydantic import ValidationError

from qat.config import Settings


def test_defaults_are_safe():
    settings = Settings(_env_file=None)
    assert settings.trading_mode == "paper"
    assert settings.is_live is False
    assert settings.storage_backend == "sqlite"


def test_unset_market_defaults_to_asx(monkeypatch):
    monkeypatch.delenv("QAT_MARKET", raising=False)
    assert Settings(_env_file=None).market == "ASX"


@pytest.mark.parametrize(
    ("field", "value"),
    [("market", "US"), ("broker", "alpaca"), ("market_data_source", "alpaca")],
)
def test_retired_market_and_sources_are_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


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


# --- corporate actions (M39) --------------------------------------------------


def test_corporate_action_mode_defaults_to_shadow():
    """The default is what makes M39's first deployment a no-op, and that is
    what keeps it inside the freeze on arrival."""
    assert Settings(_env_file=None).corporate_action_mode == "shadow"


def test_corporate_action_mode_can_be_promoted_via_env(monkeypatch):
    """Promotion to acting is a deliberate config change, recorded like any
    other."""
    monkeypatch.setenv("QAT_CORPORATE_ACTION_MODE", "act")

    assert Settings(_env_file=None).corporate_action_mode == "act"


def test_corporate_action_mode_rejects_an_unknown_value():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, corporate_action_mode="maybe")
