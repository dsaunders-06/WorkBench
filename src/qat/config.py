"""Typed, validated application configuration.

Default trading_mode is always "paper" - this is a hard safety default
(spec §L, Acceptance Criteria O), covered by tests/safety/test_default_paper_mode.py.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from qat.paths import data_dir as default_data_dir
from qat.paths import env_path

_DEFAULT_FRED_SERIES = ("DGS3MO", "DGS10", "T10Y3M", "VIXCLS", "BAA10Y")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="QAT_",
        # A placeholder only. model_config is evaluated once, at import, so a
        # path baked in here could never follow QAT_HOME; __init__ below
        # resolves the real one per construction.
        env_file=None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def __init__(self, **values: Any) -> None:
        """Resolve the .env at construction, not at import (M22).

        model_config is evaluated once when the class is created, so an
        absolute path written there is fixed for the life of the process and
        cannot follow a later QAT_HOME - which made the behaviour impossible to
        test and surprising to anyone relocating the app directory. Callers
        passing _env_file explicitly, including the tests that pass None, are
        left alone.
        """
        values.setdefault("_env_file", env_path())
        super().__init__(**values)

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

    # Strategies live at startup, comma-separated. Distinct from
    # autonomous_strategies: this decides whether a strategy is *evaluated at
    # all*, that one decides whether its orders may self-sign.
    #
    # Added M27b, and the sequencing matters. Until now the live set existed
    # only in memory: it started empty at every launch (spec §K - nothing
    # trades until a human vets it in the Workbench) and was filled by a button
    # click. That is a defensible rule for an attended session and an
    # impossible one for an unattended test, which is the phase this
    # application is actually in - a run left going overnight inherited nothing
    # and could not trade whatever the market did.
    #
    # Declared here rather than persisted from the button, so the live set is
    # something the operator states and can read back, not something the app
    # remembers having been told once. Workbench deployments remain
    # session-only additions on top.
    deployed_strategies: str = ""

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

    # --- Trading costs (M27) -------------------------------------------------
    # IBKR charges a MINIMUM per transaction, which a bps-only model cannot
    # express: at 5bps a $2,000 trade models as $1 against a real $6. The fixed
    # fee hurts small trades hardest, so understating it is exactly backwards.
    # Which IBKR schedule to price against. At ASX Tier I both models charge
    # 0.088%, but Tiered adds exchange and clearing fees on top, so Fixed is
    # the cheaper of the two above the floor crossover.
    ibkr_pricing_model: Literal["fixed", "tiered"] = "fixed"

    # Overridden per market by MARKET_COST_PROFILES unless set explicitly.
    broker_min_commission: float = Field(default=6.60, ge=0)
    commission_bps: float = Field(default=5.0, ge=0)
    slippage_bps: float = Field(default=5.0, ge=0)

    # Costs are modelled during paper trading even though Alpaca charges
    # nothing. The point of a paper test is to learn whether a strategy
    # survives the costs it will actually pay; measuring it commission-free
    # would promote strategies on figures that do not exist at the broker.
    apply_costs_in_paper: bool = True

    # The cost rail, expressed against RISK rather than notional. Every order
    # has a stop, so 1R is always known, whereas a profit target is optional
    # strategy metadata. It also scales correctly: $12 round-trip is 1.2% of a
    # $1,000 risk but 4% of a $300 one, and it is the small trade that needs
    # refusing.
    max_cost_to_risk_pct: float = Field(default=0.10, gt=0, le=1.0)

    # Churn control. Ten concurrent positions turned over weekly costs $6,240 a
    # year at $12 a round trip - 6.2% of a $100k account before a single losing
    # trade. At ten trading days it is 3.1%.
    enforce_min_holding_period: bool = True
    min_holding_trading_days: int = Field(default=10, ge=0)

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

    # Enforcement is NOT optional on a live account (M29).
    #
    # The policy said "earn autonomy" and the code granted it anyway, which is
    # exactly the inconsistency governance exists to prevent. But turning the
    # flag on during the paper phase is self-defeating in a way worth naming:
    # the bar is 30 closed trades, paper is where those trades are supposed to
    # come from, and enforcing it there means nothing ever trades, so no
    # evidence is ever produced, so the bar is never met. Circular.
    #
    # Resolved by binding it to what is actually at stake rather than to a flag
    # someone has to remember. Paper collects the evidence; live requires it,
    # always, whatever the setting says. An operator can opt in early on paper;
    # nobody can opt out on live.
    @property
    def promotion_evidence_enforced(self) -> bool:
        return self.enforce_promotion_evidence or self.is_live

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
    # Absolute for the same reason as env_file above: the trade ledger and the
    # journals must not depend on the working directory of whoever launched the
    # application.
    data_dir: str = Field(default_factory=lambda: str(default_data_dir()))
    fred_series: tuple[str, ...] = _DEFAULT_FRED_SERIES

    # "synthetic" = the seeded random walk every milestone up to M13 ran on.
    # "yfinance" = real (free, delayed, rate-limited) market data.
    #
    # Synthetic remains the default so the demo app and the test suite are
    # unchanged and offline by default. Nothing about a strategy's behaviour on
    # synthetic prices tells you anything about its behaviour on real ones.
    market_data_source: Literal["synthetic", "yfinance", "alpaca"] = "synthetic"

    # Which Alpaca data feed to request (M17). iex is real time on any account
    # including free paper, but is a single exchange carrying a small share of
    # US consolidated volume. sip is the full consolidated tape and needs a
    # paid Algo Trader Plus subscription - requesting it without one fails
    # rather than quietly degrading. delayed_sip is consolidated but 15 minutes
    # behind, and is available on the free tier.
    alpaca_data_feed: Literal["iex", "sip", "delayed_sip"] = "iex"

    # How often Alpaca's latest-trade endpoint is polled.
    alpaca_poll_seconds: float = Field(default=60.0, gt=0)

    # Where company fundamentals come from (M18). "mock" is the seeded
    # generator every milestone up to M17 ran on; it answers every field for
    # every symbol, which is exactly why it must not be the thing a real
    # decision rests on. "yfinance" returns real figures and leaves genuinely
    # unavailable ones empty, so the fundamentals strategies abstain instead of
    # scoring an ETF on an invented return on equity.
    fundamentals_source: Literal["mock", "yfinance"] = "mock"

    # Fundamentals move quarterly, so a week-old figure is current. The cache
    # bounds how often an unofficial, rate-limited vendor is asked.
    fundamentals_cache_days: float = Field(default=7.0, gt=0)

    # Whether the feed and strategy engine follow market hours (M19). On real
    # data leaving them running around the clock means polling a rate-limited
    # vendor all night, emitting signals from the previous close, and tripping
    # the staleness rail within a minute of every close.
    #
    # Ignored on simulated prices, which have no trading hours: a demo app that
    # looks dead all weekend reads as a bug rather than a feature.
    session_follows_market_hours: bool = True
    session_poll_seconds: float = Field(default=20.0, gt=0)

    # How often the shared account poller re-reads the broker (M21). Alpaca
    # documents 200 requests a minute per account, read straight off the
    # X-Ratelimit-Limit response header; the Dashboard's own two-second timer
    # was spending sixty of them on repainting one tile. Five seconds costs
    # twelve a minute for account, balances and positions together.
    account_poll_seconds: float = Field(default=5.0, gt=0)

    # --- Walk-forward defaults (M19) -----------------------------------------
    # Window sizes for the Workbench's walk-forward panel, in daily bars.
    # Roughly six months in-sample against three months out-of-sample.
    walk_forward_in_sample_bars: int = Field(default=120, gt=0)
    walk_forward_out_sample_bars: int = Field(default=60, gt=0)

    # How much of the regime probability distribution must sit inside a
    # strategy's suitable regimes before it may trade (M27b).
    #
    # The gate used to read the single argmax label. On 30 July that label was
    # `high_vol` at 0.31 against `bull` at 0.29 - so a 0.02 difference between
    # the top two decided whether the only promoted strategy traded at all,
    # while 0.49 of the mass sat in regimes where it was eligible. Taking the
    # argmax of a nearly flat distribution and treating it as certainty threw
    # away the confidence the model had already computed.
    #
    # 0.5 means "more likely in than out". Note the consequence for an
    # uninformative classifier: with seven regimes and a flat distribution a
    # four-regime strategy sits at 0.57 and trades, a one-regime strategy at
    # 0.14 and does not. That is the intended direction - when the model knows
    # nothing, breadth of mandate decides, not an arbitrary argmax.
    regime_eligibility_mass: float = Field(default=0.5, gt=0.0, le=1.0)

    # Interval ticks are aggregated into OHLC bars over (M14), daily since
    # M27a.
    #
    # It was 60s, which meant swing's EMA20/EMA50 were 20 and 50 *minutes* and
    # the regime HMM's 60-bar fit window was one hour of market. Both were
    # specified in daily bars, and no strategy in this system had ever been
    # evaluated on the data it was designed for. The intraday feed keeps its
    # role for execution pricing, staleness and account state; it is no longer
    # the source of signal history.
    #
    # Viable only alongside the warm start (domain/warm_start.py): at this
    # interval an unseeded buffer needs ten weeks to fill an EMA50.
    bar_interval_seconds: float = Field(default=86_400.0, gt=0)

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
    def deployed_strategies_tuple(self) -> tuple[str, ...]:
        return tuple(s.strip() for s in self.deployed_strategies.split(",") if s.strip())

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
