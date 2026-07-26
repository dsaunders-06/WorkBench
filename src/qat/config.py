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

    # --- Execution mode (M13) ------------------------------------------------
    # "recommend": every order waits for a human sign-off in the Order Blotter,
    #   carrying the reasoning behind it. This is the default and always has
    #   been the only behaviour before M13.
    # "auto": the AutonomyGate may sign off qualifying orders unattended.
    #
    # Defaulting to "recommend" is a safety requirement, not a preference - an
    # unattended execution path must never be what you get by doing nothing.
    execution_mode: Literal["recommend", "auto"] = "recommend"

    # Unattended execution is confined to paper accounts. This is deliberately
    # a separate flag from trading_mode rather than a check on it, so that
    # reaching live autonomous trading needs a code change and not just a
    # config edit - there is no supported configuration in which this app
    # trades real money with no human in the loop.
    allow_autonomous_live_trading: bool = False

    # Strategies cleared to trade unattended, comma-separated. Empty means none:
    # autonomy is earned per strategy through the promotion gate, never
    # inherited by every strategy at once because one of them proved out.
    autonomous_strategies: str = ""

    # Halt new autonomous BUYs when the day's P&L is this far under water.
    # Protective sells are never gated by it - they reduce risk.
    autonomous_pause_buys_below_day_pnl_pct: float = Field(default=-0.04, lt=0)
    autonomous_halve_size_below_day_pnl_pct: float = Field(default=-0.02, lt=0)

    # Reject an auto-signed order whose price has drifted this far from the
    # price it was sized against - sizing, stop and target would all be stale.
    autonomous_price_drift_limit_pct: float = Field(default=0.03, gt=0)

    # How often the equity monitor polls the broker to feed the daily-loss and
    # drawdown rails. These rails were dead code before M13; nothing called them.
    equity_poll_seconds: float = Field(default=60.0, gt=0)

    # --- Storage ---------------------------------------------------------
    storage_backend: Literal["sqlite", "timescale"] = "sqlite"
    database_url: str = "sqlite:///./qat.db"

    # --- Broker ------------------------------------------------------------
    # mock = in-process simulator (default, no credentials needed)
    # alpaca = Alpaca paper account (US equities only)
    # ibkr = Interactive Brokers Gateway/TWS
    broker: Literal["mock", "alpaca", "ibkr"] = "mock"

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

    # --- Portfolio governor (M15) --------------------------------------------
    # Total loss if every open position hit its stop at once. Per-trade limits
    # bound one trade and say nothing about ten trades each within budget; the
    # reference implementation measured 36.8% against a 5% cap before this
    # existed. A position with no known stop counts its whole value as at risk.
    max_aggregate_risk_at_stop_pct: float = Field(default=0.05, gt=0, le=1.0)

    # A count, not a percentage - the simplest bound on how thinly the
    # portfolio is spread. Pending orders occupy a slot, since an order awaiting
    # sign-off is committed exposure that has not filled yet.
    max_concurrent_positions: int = Field(default=10, gt=0)

    # The delever sweep targets this fraction of the cap rather than the cap
    # itself: landing exactly on the boundary re-triggers the sweep from
    # ordinary price movement alone on the very next check.
    delever_target_fraction_of_cap: float = Field(default=0.9, gt=0, lt=1.0)

    # Whether the sweep may trim positions on its own. Off by default: it
    # SELLS, and a rail that sells without being asked is a bigger delegation
    # than one that merely blocks buying. Off, a breach is reported and blocks
    # new risk but unwinds only as positions close naturally.
    delever_sweep_enabled: bool = False

    reconciliation_poll_seconds: float = Field(default=300.0, gt=0)

    # --- Promotion gate (M16) ------------------------------------------------
    # What a strategy must demonstrate on REALISED trades before it is eligible
    # to trade unattended. These make "fine tuned" a falsifiable claim rather
    # than a judgement call. The gate advises: an operator may still promote a
    # strategy it has not cleared, but the scorecard shows them doing it.
    promotion_min_trades: int = Field(default=30, gt=0)
    promotion_min_average_r: float = Field(default=0.2)
    promotion_min_win_rate: float = Field(default=0.4, ge=0.0, le=1.0)
    # A good average hides a single catastrophic trade. The worst loss may not
    # exceed this multiple of the average win.
    promotion_max_loss_to_avg_win: float = Field(default=3.0, gt=0)

    # When true, the autonomy gate additionally requires a promoted strategy to
    # still MEET the bar on its own realised trades, so one that has degraded
    # stops trading unattended without anyone having to notice. Off by default
    # only because a fresh install has no trade history and would otherwise
    # block everything for a reason that looks like a bug; turn it on once the
    # ledger has data.
    enforce_promotion_evidence: bool = False

    # --- Order policy (M11) --------------------------------------------------
    # Long-only by default: a "sell" signal for a symbol with no holding is
    # dropped rather than opening a short. Strategies emit directional signals
    # continuously, so without this the blotter fills with sell orders for
    # things the account never held.
    allow_short_selling: bool = False

    # Cash floor that a buy may never eat into (spec M12). Two guarantees sit
    # on this: the account can never be leveraged (a buy's notional can never
    # exceed available cash - not configurable), and cash can never be fully
    # depleted. gt=0 is what makes the second one structural: the reserve is
    # tunable but cannot be set to zero, so it cannot be quietly switched off.
    min_cash_reserve: float = Field(default=1.0, gt=0)

    # --- Data pipeline (M2/M14) ----------------------------------------------
    data_dir: str = "./data"
    fred_series: tuple[str, ...] = _DEFAULT_FRED_SERIES

    # "synthetic" = the seeded random walk every milestone up to M13 ran on.
    # "yfinance" = real (free, delayed, rate-limited) market data.
    #
    # Synthetic remains the default so the demo app and the test suite are
    # unchanged and offline by default. Nothing about a strategy's behaviour on
    # synthetic prices tells you anything about its behaviour on real ones.
    market_data_source: Literal["synthetic", "yfinance"] = "synthetic"

    # Interval ticks are aggregated into OHLC bars over (M14). 60s matches the
    # finest granularity the free feed actually serves.
    bar_interval_seconds: float = Field(default=60.0, gt=0)

    # How often the real feed is polled. Yahoo is delayed by roughly 15 minutes
    # for most exchanges, so polling faster than this spends rate-limit budget
    # without producing newer prices.
    yfinance_poll_seconds: float = Field(default=60.0, gt=0)

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

    @property
    def autonomous_strategies_tuple(self) -> tuple[str, ...]:
        return tuple(s.strip() for s in self.autonomous_strategies.split(",") if s.strip())

    @property
    def autonomy_enabled(self) -> bool:
        """Both conditions, never just the mode: autonomy in a live account
        requires an explicit second flag that ships False and has no Settings
        UI, so a live unattended session cannot be reached by configuration
        alone."""
        if self.execution_mode != "auto":
            return False
        if self.is_live and not self.allow_autonomous_live_trading:
            return False
        return True
