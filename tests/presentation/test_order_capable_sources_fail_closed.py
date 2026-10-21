"""Synthetic sources require an explicit isolated demo session."""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.data.history import RealHistorySource, SyntheticHistorySource, resolve_history_source
from qat.presentation.runtime import (
    Runtime,
    resolve_fundamentals_source,
    resolve_macro_source,
    resolve_market_data_source,
)


def real_settings(**changes):
    return Settings(_env_file=None, broker="ibkr", **changes)


def test_synthetic_market_data_refused_for_real_broker():
    with pytest.raises(RuntimeError, match="synthetic market data"):
        resolve_market_data_source(real_settings(market_data_source="synthetic"))


def test_synthetic_history_refused_for_real_broker():
    with pytest.raises(RuntimeError, match="synthetic history"):
        resolve_history_source(real_settings(market_data_source="synthetic"))


def test_mock_fundamentals_refused_for_real_broker():
    with pytest.raises(RuntimeError, match="mock fundamentals"):
        resolve_fundamentals_source(
            real_settings(fundamentals_source="mock"), SyntheticHistorySource(), ("BHP.AX",)
        )


def test_mock_macro_refused_for_real_broker_without_key(monkeypatch):
    monkeypatch.setattr("qat.presentation.runtime.get_secret", lambda _: None)
    with pytest.raises(RuntimeError, match="mock macro"):
        resolve_macro_source(real_settings())


def test_real_history_outage_cannot_fall_back_to_synthetic():
    class EmptyYahoo:
        async def get_bars(self, symbol, period, interval):
            return None

    source = RealHistorySource(EmptyYahoo(), allow_synthetic_fallback=False)
    with pytest.raises(RuntimeError, match="real daily bars"):
        import asyncio

        asyncio.run(source.get_daily_bars("BHP.AX"))


def test_synthetic_sources_available_only_with_explicit_demo_mode(monkeypatch):
    monkeypatch.setattr("qat.presentation.runtime.get_secret", lambda _: None)
    settings = Settings(_env_file=None, broker="mock", demo_mode=True)
    assert settings.synthetic_demo_allowed
    assert type(resolve_market_data_source(settings)).__name__ == "SyntheticMarketDataSource"
    assert isinstance(resolve_history_source(settings), SyntheticHistorySource)
    assert type(resolve_macro_source(settings)).__name__ == "MockMacroSource"
    assert (
        type(resolve_fundamentals_source(settings, SyntheticHistorySource(), ("BHP.AX",))).__name__
        == "MockFundamentalsSource"
    )


def test_demo_flag_cannot_expose_real_orders():
    for changes in (
        {"broker": "ibkr"},
        {"trading_mode": "live"},
    ):
        with pytest.raises(ValueError, match="demo mode"):
            Settings(_env_file=None, demo_mode=True, **changes)


def test_autonomous_mock_orders_remain_inside_explicit_demo():
    settings = Settings(_env_file=None, demo_mode=True, broker="mock", execution_mode="auto")
    assert settings.synthetic_demo_allowed
    with pytest.raises(RuntimeError, match="synthetic market data"):
        Runtime.build_demo(
            settings=Settings(_env_file=None, broker="mock", execution_mode="auto"),
            explicit_demo=False,
        )


def test_explicit_demo_builder_isolated_from_normal_app_startup():
    demo = Runtime.build_demo(settings=Settings(_env_file=None))
    assert demo.settings.synthetic_demo_allowed
    with pytest.raises(RuntimeError, match="synthetic market data"):
        Runtime.build_demo(settings=Settings(_env_file=None), explicit_demo=False)
