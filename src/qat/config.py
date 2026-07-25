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

    # --- Order policy (M11) --------------------------------------------------
    # Long-only by default: a "sell" signal for a symbol with no holding is
    # dropped rather than opening a short. Strategies emit directional signals
    # continuously, so without this the blotter fills with sell orders for
    # things the account never held.
    allow_short_selling: bool = False

    # --- Data pipeline (M2) --------------------------------------------------
    data_dir: str = "./data"
    fred_series: tuple[str, ...] = _DEFAULT_FRED_SERIES

    # --- AI advisory (M8) --------------------------------------------------
    anthropic_model: str = "claude-sonnet-5"
    # LM Studio's default port; still works with Ollama by pointing this at
    # Ollama's own OpenAI-compatible URL instead - LocalEngine is generic.
    local_llm_base_url: str = "http://localhost:1234/v1"
    local_llm_model: str = "local-model"
    ai_context_max_chars: int = Field(default=8_000, gt=0)
    ai_cost_budget_calls_per_day: int = Field(default=200, gt=0)

    # --- AI provider selection (M10) ----------------------------------------
    # Every AI request lands in one of two LLMRouter slots - "general" (regime
    # narrative, when not sensitive and within budget) or "sensitive" (any
    # request touching positions, an absolute privacy override). Each slot's
    # backing provider is independently selectable rather than a single
    # app-wide toggle, so the sensitive slot can stay local-only even if the
    # general slot uses Anthropic's cloud API.
    general_request_provider: Literal["anthropic", "local", "demo"] = "demo"
    sensitive_request_provider: Literal["local", "anthropic", "demo"] = "demo"

    # --- Market & watchlist (M10) --------------------------------------------
    market: Literal["US", "ASX"] = "US"
    watchlist_category: Literal["curated", "etf", "megacap"] = "curated"
    # Plain comma-separated strings, not tuple[str, ...] fields: pydantic-settings
    # JSON-decodes any complex-typed env value before a field_validator ever runs,
    # so a human-editable "SPY,AAPL,MSFT" env value would fail to parse as JSON.
    # A plain str field sidesteps that entirely; watchlist_curated_us_tuple below
    # does the actual comma-splitting. Matches the fixed 4-symbol watchlist every
    # prior milestone shipped with, so existing behaviour is unchanged by default.
    watchlist_curated_us: str = "SPY,AAPL,MSFT,GOOGL"
    watchlist_curated_asx: str = "STW.AX,BHP.AX,CBA.AX,CSL.AX"
    watchlist_max_symbols: int = Field(default=10, gt=0)
    watchlist_min_avg_volume: int = Field(default=100_000, ge=0)

    # --- Presentation (M11) ---------------------------------------------------
    # Caps how many order rows the blotter renders at once; the underlying
    # order history is never truncated, only the view.
    blotter_max_rows: int = Field(default=500, gt=0)

    # --- Logging -----------------------------------------------------------
    log_level: str = "INFO"

    @property
    def watchlist_curated_us_tuple(self) -> tuple[str, ...]:
        return tuple(s.strip() for s in self.watchlist_curated_us.split(",") if s.strip())

    @property
    def watchlist_curated_asx_tuple(self) -> tuple[str, ...]:
        return tuple(s.strip() for s in self.watchlist_curated_asx.split(",") if s.strip())

    @property
    def is_live(self) -> bool:
        return self.trading_mode == "live"
