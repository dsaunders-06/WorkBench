"""Typed, validated application configuration.

Default trading_mode is always "paper" - this is a hard safety default
(spec §L, Acceptance Criteria O), covered by tests/safety/test_default_paper_mode.py.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_FRED_SERIES = ("DGS3MO", "DGS10", "T10Y3M", "VIXCLS", "BAA10Y")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="QAT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Trading mode --------------------------------------------------
    trading_mode: Literal["paper", "live"] = "paper"

    # --- Storage ---------------------------------------------------------
    storage_backend: Literal["sqlite", "timescale"] = "sqlite"
    database_url: str = "sqlite:///./qat.db"

    # --- IBKR ------------------------------------------------------------
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 4002  # paper Gateway default; 7497 for paper TWS
    ibkr_client_id: int = 1

    # --- Risk limits (paper §6/§18, Table 18.1; overridable per-strategy later) ---
    per_trade_risk_pct: float = Field(default=0.01, gt=0, le=0.02)
    max_per_trade_risk_pct: float = Field(default=0.02, gt=0, le=0.02)
    kelly_fraction: float = Field(default=0.5, gt=0, le=1.0)
    atr_stop_multiple: float = Field(default=2.5, gt=0)
    portfolio_es_limit_pct: float = Field(default=0.03, gt=0)
    daily_loss_limit_pct: float = Field(default=0.03, gt=0)
    max_drawdown_limit_pct: float = Field(default=0.20, gt=0)
    data_staleness_seconds: int = Field(default=60, gt=0)
    max_single_name_concentration_pct: float = Field(default=0.25, gt=0, le=1.0)
    max_sector_concentration_pct: float = Field(default=0.40, gt=0, le=1.0)

    # --- Data pipeline (M2) --------------------------------------------------
    data_dir: str = "./data"
    fred_series: tuple[str, ...] = _DEFAULT_FRED_SERIES

    # --- AI advisory (M8) --------------------------------------------------
    anthropic_model: str = "claude-sonnet-5"
    local_llm_base_url: str = "http://localhost:11434/v1"
    ai_context_max_chars: int = Field(default=8_000, gt=0)
    ai_cost_budget_calls_per_day: int = Field(default=200, gt=0)

    # --- Logging -----------------------------------------------------------
    log_level: str = "INFO"

    @property
    def is_live(self) -> bool:
        return self.trading_mode == "live"
