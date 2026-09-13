> **Audit evidence, Stage 3.** A fresh-context investigator, 12 September 2026.
> Its instructions: read only `src/qat` and `tests`; no documentation, git
> history or narrative; comments are claims; facts only, each with a
> file:line; no judgements. Reproduced as returned. **Not yet
> cross-verified.** Report section 5 records any correction found in
> cross-checking.

# Stage 3, Investigator 1: Market data to signal

All references are relative to `src\qat\` unless they start with `tests\`. I read only `src\qat\` and `tests\`, and wrote nothing.

**Scope limit.** Runtime values come from a `.env` file that `Settings.__init__` resolves through `paths.env_path()` (config.py:31-42). That file is outside the folders I was allowed to read. So the values actually deployed (market, `market_data_source`, `deployed_strategies`, broker, and so on) are **NOT DETERMINED**. Everything below describes the code paths and the `config.py` defaults. (Auditor's note: the deployed values are in report §3.)

## 0. What runtime.py builds and in what order

`Runtime.build_demo` (presentation/runtime.py:559-1007) is called once from `app.py:69`. Engines then start in registration order through `Orchestrator.start_all` (app.py:90; orchestrator.py:36-42). Each `start()` is awaited in turn and no exception is caught there.

- **Registration order** (runtime.py:930-974): BrokerConnection → WarmStart → KillSwitchEngine → RiskEngine → EquityMonitor → ReconciliationMonitor → DeleverSweep → TradeLedger → PerformanceReporter → **MarketDataFeed** → **FeatureEngine** → **MacroFeed** → **StrategyEngine** → AutonomousExecutor → CorporateActionMonitor → SignalToOrderBridge → **RegimeEngine** → BookRiskMonitor → SessionController. BarSeriesFeed is registered last, and only when it is configured.
- **Bus semantics.** `EventBus.publish` awaits `asyncio.gather` over every handler for that exact event type. It logs handler exceptions and never re-raises them (domain/bus.py:34-44). A publish with no handlers returns at once (bus.py:35-37). So a publisher waits until every subscriber has finished.
- **Feed symbols.** The benchmark comes first, then the watchlist, de-duplicated: `(benchmark_symbol, *watchlist)` (runtime.py:777). The benchmark is `universe.MARKET_BENCHMARKS[settings.market]`, which is `{"US": "SPY", "ASX": "STW.AX"}` (runtime.py:572; data/universe.py:35).

## Stage A: Market data ingestion

### Modules and key functions
- `data/market_data.py`: `RawTick` (:37-42), the `MarketDataSource` protocol (:45-46), `SyntheticMarketDataSource` (:49-73) and `MarketDataFeed` (:76-385).
- `data/yfinance_source.py`: `YFinanceMarketDataSource` (:235-512), `YFinanceHistorySource` (:192-232), `normalise_frame` (:101-150) and `fill_missing_intervals` (:163-189).
- `data/alpaca_source.py`: `AlpacaMarketDataSource` (:95-269) and `AlpacaHistorySource` (:272-398).
- `data/history.py`: `resolve_history_source` (:217-232), `RealHistorySource` (:159-196), `SyntheticHistorySource` (:132-156) and `fetch_daily_panel` (:57-114).
- `data/bars.py`: `BarAggregator` (:96-306) and `MultiSymbolAggregator` (:309-367).
- `domain/warm_start.py`: `WarmStart` (:42-135).
- `data/macro_fred.py`: `FredMacroSource` (:53-85), `MockMacroSource` (:88-99), `MacroHistory` (:102-139), `load_macro_history` (:142-173) and `MacroFeed` (:176-256).
- `data/bar_series_feed.py`: `BarSeriesFeed` (:61-183) and `resolve_bar_series_feed` (:186-211).
- `domain/session_controller.py`: `SessionController` (:57-233).

### Which live source runtime.py builds
`resolve_market_data_source` (runtime.py:171-226) chooses:
- **`"alpaca"`** builds `AlpacaMarketDataSource(feed=settings.alpaca_data_feed, poll_seconds=settings.alpaca_poll_seconds)` (:198-201). It logs a warning if `market != "US"` (:180-184). If construction raises, it falls back to `SyntheticMarketDataSource(seed=1, interval_seconds=1.0)` (:202-208). The constructor is lazy (alpaca_source.py:108-126): credentials and the SDK are first touched at poll time (`client` property :122-126, `_probe` :220-228, `_poll_once` :246-254). So a missing key shows up as failed polls, not as the fallback.
- **`"yfinance"`** builds `YFinanceMarketDataSource(poll_seconds=settings.yfinance_poll_seconds)` (:210-219) and falls back to synthetic on a construction exception (:220-226). The `yfinance` import is also lazy (`_real_client` yfinance_source.py:95-98; `client` property :269-273). `self.client` is evaluated inside the `try` in `_poll_once` (:434-446), so an import failure turns into empty polls.
- **Otherwise** (default `"synthetic"`, config.py:687) it builds `SyntheticMarketDataSource(seed=1, interval_seconds=1.0)` (:226).
- There is no IBKR market-data source in `market_data_source`'s Literal (config.py:687). The broker (IBKR, Alpaca or Mock) is resolved separately (runtime.py:274-351) and is not a tick source for the feed.

### Poll cadence
- **yfinance.** Polls every `poll_seconds` (default 60.0, config.py:866). Each poll is one `download(list_of_symbols, period="1d", interval="1m", auto_adjust=True)` (yfinance_source.py:435-442).
  - Backoff: once `consecutive_failures` reaches 5, or at least half the symbols have each missed 5 polls in a row (`down_symbol_fraction=0.5`, :250, :293-296), the wait becomes `min(poll*2^min(over+1,5), 300)` (:398-415).
- **Alpaca.** Polls latest-trade every `alpaca_poll_seconds` (default 60.0, config.py:762), with the same backoff rule (alpaca_source.py:139-183). A one-time bisection at start drops symbols Alpaca rejects (:185-244).
- **Synthetic.** Emits one tick per symbol per round, then sleeps 1.0 s (market_data.py:60-73).
- **Session gating.** The feed only runs while the market is open, and only when `session_follows_market_hours` (default True) and `market_data_source != "synthetic"` (runtime.py:919-928). `SessionController` checks every `session_poll_seconds` (default 20.0) and calls `feed.stop()` or `feed.start()` (session_controller.py:124-130, 180-206). Hours are US 09:30-16:00 NY and ASX 10:00-16:00 Sydney (domain/market_calendar.py:53-56, 318-398).

### What a tick looks like
- `RawTick(symbol, ts, price, volume)` (market_data.py:37-42).
- **yfinance tick** (built per symbol from the last row of the 1-minute frame, yfinance_source.py:455-491):
  - `price` = last 1m close. It is dropped if not finite or ≤ 0 (:468-470).
  - `ts` = that bar's own timestamp, or `now` if NaT (:483-487).
  - `volume` = that bar's volume.
  - Symbols go out in Yahoo spelling and are mapped back to the app's spelling (:433; data/symbols.py:57-64).
  - If the last 1m bar has not changed, the same ts/price/volume is re-emitted on every poll (nothing in :448-491 suppresses repeats).
- **Alpaca tick:** `price` = trade price (skipped if ≤ 0), `ts` = trade timestamp (or `now`), `volume` = trade size (alpaca_source.py:256-269).
- **Synthetic tick:** a random walk from 100.0 with steps uniform in ±0.5, floored at 0.01, rounded to 2 dp; `ts=now`; volume 1-1000 (market_data.py:60-71).

### Pipeline inside MarketDataFeed
- `_ingest_loop` puts ticks on an `asyncio.Queue(maxsize=1000)` (market_data.py:105, 158-160).
- `_process_loop` records `_last_seen[symbol] = tick.ts`, stamps `_last_tick_at` with the receive time, records lag, and publishes `MarketDataEvent(symbol, price, volume, ts=tick.ts)` (:162-177).
- `_ingest_loop` has no try/except. If `stream_ticks` raises, the ingest task ends and nothing restarts it until the next `feed.start()`. Some code in the yfinance source runs outside its `try`, for example `normalise_frame` at yfinance_source.py:456.

### Historical and warm-start bars
- `resolve_history_source` (history.py:217-232):
  - `"alpaca"` → `AlpacaHistorySource`, with `Adjustment.ALL` (alpaca_source.py:385-391).
  - `"yfinance"` → `RealHistorySource`, which calls `YFinanceHistorySource.get_bars(..., interval="1d", auto_adjust=True)` (history.py:182-196; yfinance_source.py:218-226).
  - Otherwise → `SyntheticHistorySource`.
- `WarmStart.seed` (warm_start.py:78-104) runs once per process, in `start()`, registered second (runtime.py:940):
  - Calls `fetch_daily_panel(history_source, feed_symbols, 300)` (DEFAULT_BARS=300, history.py:28).
  - Seeds the aggregators of StrategyEngine, SignalToOrderBridge and FeatureEngine (runtime.py:895).
  - For per-symbol sources it drops any symbol whose fetch fell back to synthetic (`last_was_synthetic`, history.py:74-80). Alpaca's bulk method has no synthetic fallback (alpaca_source.py:320-350).
  - yfinance asks for period `"2y"` for 300 bars (history.py:199-214) and takes `tail(300)` (:195).
- `BarAggregator.seed` keeps only bars whose interval has closed. Today's bar becomes the *forming* bar and future bars are dropped (bars.py:159-186). It raises if any bar already exists (:151-155).
- Nothing else re-seeds after startup. `WarmStart.seed` is called only from `WarmStart.start` (warm_start.py:68); the replay harness is the only other caller (domain/backtester/replay_session.py:269).

### Macro inputs
- `resolve_macro_source` (runtime.py:354-385) uses `FredMacroSource` when the `FRED_API_KEY` secret is set, otherwise `MockMacroSource(seed=1)`, which returns a single value `uniform(-1,5)` stamped now (macro_fred.py:94-99).
- `MacroFeed(bus, macro, settings.fred_series, poll_interval_seconds=3600.0)` (runtime.py:820) publishes the latest observation of each series as `MacroEvent(series, value, ts=observation date)` (macro_fred.py:214-240). FRED fetches the full series on every poll (:65-69). The default series are `("DGS3MO","DGS10","T10Y3M","VIXCLS","BAA10Y")` (config.py:17, 637).
- `BarSeriesFeed` runs only if `bar_macro_series` is non-empty *and* `market_data_source == "yfinance"` (bar_series_feed.py:195-211). It polls hourly (`period="3mo"`, `interval="1d"`) and publishes the last close as a `MacroEvent`. It refuses synthetic data, empty frames, non-finite closes and bars older than 5 days (:118-169).

### Summary for Stage A
- **Outputs:**
  - `MarketDataEvent`, consumed by FeatureEngine, StrategyEngine, RegimeEngine, SignalToOrderBridge (bars and time stop), TradeLedger (`_on_price`), and the UI (risk_console, regime_monitor).
  - `MacroEvent`, consumed by RegimeEngine and the UI regime_monitor.
  - Warm-start seeding of four buffers.
- **Decision authority:** none over trading. It decides which prices exist and when.
- **State in memory:**
  - Feed: `_queue`, `_last_seen`, `_stale_symbols`, `_last_tick_at`, `_observed_lags` (deque of 200) (market_data.py:105-131).
  - yfinance source: per-symbol `misses` and `consecutive_failures` (yfinance_source.py:280-283).
  - Three `MultiSymbolAggregator`s: max_bars 500 for StrategyEngine and FeatureEngine (strategies/engine.py:54, 74-76; data/feature_engine.py:29, 38-40) and 250 for the bridge (domain/oms/signal_bridge.py:338, 395-397). No gap filling on daily bars (bars.py:125-126).
- **Persistence:** none in this stage. None of the modules listed above does any file I/O; my grep for `Path(`, `open(`, `write_text` and similar found nothing. Logging only.
- **Failure behaviour:**
  - Construction failure falls back to synthetic with a warning (runtime.py:202-226).
  - Poll exceptions become empty polls (yfinance_source.py:443-446; alpaca_source.py:252-254).
  - Warm-start failure is logged and the app starts cold (warm_start.py:66-73).
  - Macro history is retried once after 2 s, then left out (macro_fred.py:155-173).
  - A macro poll exception is logged and the loop continues (:242-256).
- **Refusal behaviour:**
  - The warm start will not seed synthetic fallback data (history.py:74-80).
  - `normalise_frame` returns an empty frame for a MultiIndex column it cannot find, rather than another symbol's data (yfinance_source.py:117-127).
  - BarSeriesFeed refusals are listed above.
  - An out-of-order tick is dropped by the aggregator (bars.py:247-250).
- **LLM:** none. No module in this stage imports `ai_advisory`, `llm` or `anthropic` (grep across data/*, data/broker/*, the regime engine, strategies, warm_start, session_controller, bus and events: no matches).
- **Broker order influence:** indirect. Prices feed the bars that set swing's entry, stop and target, the bridge's sizing price and ATR, and the regime scalar. Chain: `MarketDataEvent` → StrategyEngine `SignalEvent` → bridge → `OMS.submit_order` → sign-off → `broker.place_order` (details in Stage E).

## Stage B: Data quality

### Staleness (per symbol)
- `_check_staleness_once` runs every 5.0 s (`staleness_check_interval` default, market_data.py:89, 235-245; runtime does not override it).
- Formula (:369-370): `elapsed = (now − last_seen_ts) − source_delay_seconds`, and the symbol is stale when `elapsed > staleness_seconds`.
  - `staleness_seconds` = `settings.data_staleness_seconds`, default 900 (config.py:579; runtime.py:799).
  - `source_delay_seconds` = `settings.market_data_delay_seconds` (default 1200, config.py:879) **only when `market_data_source == "yfinance"`**, else 0.0 (runtime.py:784-786).
  - So on yfinance a symbol goes stale when its bar timestamp is more than 2,100 s old. On Alpaca it is more than 900 s. Synthetic ticks are stamped `now`, so they never go stale while the loop runs.
- Events go out only on a change, as `DataStaleEvent(symbol, seconds_since_update, stale=True|False)` (:371-384).
- A symbol that has never printed is skipped (:359-360). One warning lists these "absent" symbols, and only once some other symbol has printed (:345-355).
- **What it blocks:** the only consumer in `src` is `StrategyEngine._on_stale_quote` (strategies/engine.py:181, 188-193). A stale symbol's ticks are still recorded in the bars, but **all strategy evaluation for that symbol is skipped, exits as well as entries** (:368-371). KillSwitchEngine does not subscribe to it (subscribe grep).
- **Restart edge (derived from the code; no test covers it).** `MarketDataFeed.start()` clears the feed's own `_stale_symbols` (market_data.py:139). `StrategyEngine._stale_symbols` is changed only by `DataStaleEvent` (strategies/engine.py:188-193). After a restart, a fresh print compares `False == dict.get(symbol, False)` and publishes nothing (market_data.py:371-372). So a symbol that was stale when the feed stopped stays in the StrategyEngine's exclusion set until it goes stale and recovers again in a later session. The only test references to `_stale_symbols` are tests\test_m128_tick_timestamps.py, tests\data\test_quote_freshness.py and two kill-switch tests; none restarts the feed.

### Feed health
- `_feed_health_loop` runs every 5 s. If more than 300 s (`feed_down_seconds`, market_data.py:91) pass since the last tick, or since start if there has been none, it publishes `MarketDataFeedEvent(healthy=False)` once. On the next tick it publishes `healthy=True` (:168-172, 179-233).
- It logs ERROR if ticks had arrived before, WARNING if none ever did (:219-230).
- The only consumer in `src` is `MainWindow._on_feed_health` (presentation/main_window.py:83). It gates nothing.

### Other feed diagnostics (logging only)
- Delay-claim check: the median observed lag over at least 20 samples is compared with the configured delay, with a warning beyond ±300 s. It never changes the threshold (market_data.py:32-34, 247-307).
- yfinance "N of M returned" warnings, plus the "most of the book down" error when at least half the symbols have missed 5 polls (yfinance_source.py:315-335, 493-511).
- `BLIND_WINDOW_FILTER` hides yfinance "possibly delisted" log lines while polls are empty (qat/logging.py:62-114; yfinance_source.py:313, 344).

### Validation on the live path
- **Source level only:**
  - yfinance drops NaN closes (`dropna`, yfinance_source.py:145), non-finite or non-positive prices (:468-470) and frames missing OHLC columns (:134-137).
  - Alpaca drops price ≤ 0 (alpaca_source.py:258-260).
  - `MarketDataFeed._process_loop` does no validation of its own (market_data.py:162-177).
- **`data/validation.py`** (`dedupe`, `reject_outliers`, `detect_and_fill_gaps`, `align_timezone`, `adjust_for_corporate_actions`, :39-134) has **no caller in `src`**. It is used only in tests\data\test_validation.py. There is no outlier rejection on the live path.
- Timestamps are normalised to UTC by `normalise_frame` (yfinance_source.py:149) and `bars.as_utc` (bars.py:56-65).

### Corporate-action adjustment
- **Historical bars** arrive already adjusted by the vendor: yfinance `auto_adjust=True` (yfinance_source.py:225, 441) and Alpaca `Adjustment.ALL` (alpaca_source.py:385-391). The adjustment is as of fetch time, which is process start.
- **No adjustment function runs on the live path.** `adjust_for_corporate_actions` has no `src` callers.
- `domain/corporate_actions/` (`StopAdjuster`, `SplitDetector`, `CorporateActionMonitor`) handles resting **stops** and OMS entry refusal (adjuster.py:31-83; detector.py:71-137; OMS use at domain/oms/oms.py:353-367). It does not touch bar buffers; grep of monitor.py for `bars` or `seed` found nothing bar-related.
- No code re-seeds or re-adjusts the in-memory aggregators after startup.

### Symbol handling
- **Watchlist** (`universe.resolve_watchlist`, universe.py:307-339):
  - "curated" comes from the comma-split, stripped settings strings (config.py:909-910, 922-928). Other categories come from static tuples.
  - The "volume" filter compares `synthetic_average_daily_volume(symbol)`, which is `Random("volume:"+symbol).randint(10_000, 20_000_000)` (:284-304), against `watchlist_min_avg_volume` (default 100,000).
  - The list is truncated to `watchlist_max_symbols`, default **10** (config.py:911). A comment at universe.py:248 claims this value "is 100". That does not match the `config.py` default; the deployed value is **NOT DETERMINED**.
- **Vendor translation:** `to_yfinance` keeps `.AX` and turns a class-share dot into a hyphen (symbols.py:57-64). `canonical()` (:120-126) has **no callers in `src`**. Settings watchlist strings are not upper-cased (config.py:924, 928). `entry_allow_list` is upper-cased (:950).

### Summary for Stage B
- **Decision authority:** per-symbol exclusion from signal generation (StrategyEngine only). The autonomy gate separately reads `market_data_feed.last_print_at` (runtime.py:811). It blocks an order whose symbol has no print this session, or whose last print is from an earlier trading date (domain/autonomy/gate.py:211-225).
- **State:** described under Stage A. `last_print_at` returns None after every `start()` (market_data.py:137, 309-321).
- **Persistence:** none.
- **Interactions:** SessionController stops and starts the feed (session_controller.py:182, 198). The staleness rail feeds StrategyEngine and, through `last_print_at`, the AutonomyGate. SignalToOrderBridge does **not** subscribe to `DataStaleEvent`: it sizes from its own bars regardless (signal_bridge.py:413-416, 1324-1328).
- **LLM:** none.
- **Broker order influence:** staleness stops StrategyEngine from emitting signals for that symbol. It does not stop the bridge's time-stop exit (signal_bridge.py:1280-1310) or sign-off.

## Stage C: Features

### Where features are computed and who uses them
1. **`FeatureEngine`** (data/feature_engine.py:20-52), built at runtime.py:812-816.
   - On every `MarketDataEvent`: add the tick to its daily aggregator, compute `FeatureBuilder.build` on the frame (the forming bar is included by default, bars.py:290-303), and publish `FeatureEvent`.
   - `FeatureBuilder.build` (data/features.py:72-89) returns `return_1d` (pct_change), `realized_vol` (20-bar std × √252), `atr` (14-bar simple mean of true range) and `trend_pct_above_sma` ((close − SMA50)/SMA50). A NaN or empty result defaults to 0.0 (:65-69).
   - **`FeatureEvent` has no subscriber anywhere in `src`**. The only `subscribe(` calls are for other event types. So this computation produces nothing downstream.
2. **`StrategyEngine`** computes its own `FeatureBuilder.build(bars)` per ticked symbol into `SymbolContext.technical` (strategies/engine.py:391-397). Consumers are mean_reversion, can_slim, multi_factor, sector_rotation and volatility (grep). **Swing does not read `technical`.** It computes EMAs and ATR from `context.bars` itself (swing.py:82-89, 161).
3. **`SignalToOrderBridge`** computes ATR(14) from its own bars for sizing (signal_bridge.py:1490-1494).
4. **`RegimeFeatureBuilder`** is covered in Stage D.

### Bars used
Everything uses daily bars. `bar_interval_seconds` defaults to 86,400 (config.py:861) and daily boundaries fall at exchange-local midnight (bars.py:68-93; `bar_tz=MARKET_TIMEZONES[market]`, runtime.py:815, 865, 879). The live frames include the **forming bar**, i.e. today's running price. The previous day's forming bar is closed by the first tick with a later boundary (bars.py:252-257).

The forming bar is updated from ticks: high = max, low = min, close = latest, and **volume += tick volume** (bars.py:240-245). With yfinance re-emitting the same 1m bar on each poll, volume therefore accumulates per poll. That follows from yfinance_source.py:489 together with bars.py:244. Swing and FeatureBuilder do not use volume.

### Summary for Stage C
- **Decision authority:** none.
- **State:** the aggregators. There are no caches of features except StrategyEngine's `_context_cache` (strategies/engine.py:78, 392-397).
- **Persistence:** none.
- **Failure:** no try/except in `FeatureEngine._on_market_data`. Exceptions go to the bus logger (bus.py:42-44).
- **LLM:** none.
- **Broker order influence:** `FeatureEvent` has none because it has no consumers. The StrategyEngine and bridge computations do (Stage E).

## Stage D: Regime

### Modules
- `domain/regime_engine/engine.py` (`RegimeEngine`, :59-572)
- `feature_matrix.py` (`RegimeFeatureBuilder`, :33-171)
- `scaling.py` (`ColumnStandardiser`, :20-58)
- `hmm_core.py` (`HMMRegimeModel`, :72-226)
- `fusion.py` (`score_from_hmm`, `RegimeFusion`, `HysteresisGate`, `exposure_scalar_for`, :41-231)
- `domain/regime.py` (seven labels, :13-23)

### Construction
Built at runtime.py:874-882 with `benchmark_symbol`, `breadth_symbols=watchlist`, the daily interval, `features=settings.regime_features` and `vix_series=settings.regime_vix_series`. The rest use engine defaults: `n_states=4`, `refit_interval_bars=20`, `min_fit_bars=60` (engine.py:67-69).

### Inputs and their sources
- **Benchmark `MarketDataEvent`s** give one row per bar. A new boundary appends a row; ticks inside the same bar rewrite the latest row (engine.py:322-343; feature_matrix.py:124-146). Out-of-order ticks are ignored (engine.py:331-333).
- **Breadth.** The latest price of each watchlist symbol is kept (engine.py:323-324) and snapshotted at each benchmark tick (:335).
- **`MacroEvent`** → `update_macro` (engine.py:319-320). The mapping is hard-coded (feature_matrix.py:76-82): `vix_series` (default "VIXCLS") fills `vix_level`, `"T10Y3M"` fills `yield_curve_slope`, `"BAA10Y"` fills `credit_spread`. Any other series, including the default `DGS3MO` and `DGS10`, is ignored. Event timestamps are ignored, so there is no age check on macro values in this path.
- **Seed.** `WarmStart._seed_regime` → `RegimeEngine.seed(benchmark_bars, MacroHistory, breadth)` (warm_start.py:106-135; engine.py:154-218).
  - Each historical benchmark bar is paired with the macro value current on its own date (`MacroHistory.as_of`, macro_fred.py:134-139).
  - Macro history is loaded only for `settings.fred_series` (runtime.py:897). A `regime_vix_series` served only through `bar_macro_series` has no seeded history, so `_vix` stays at its initial 0.0 (feature_matrix.py:72) for the seeded rows.
  - Breadth alignment at seed carries the last close forward. A symbol missing more than 10% of the benchmark dates is dropped, with at least one gap always tolerated (engine.py:220-317).

### Feature matrix
One row per bar, with columns chosen by name from `regime_features` (feature_matrix.py:84-122):
- `log_return` = ln(close_t / close_{t−1})
- `realized_vol` = 20-bar std of pct_change × √252
- `vix_level`, `yield_curve_slope`, `credit_spread` = last known macro values (initially 0.0)
- `breadth` = fraction of breadth symbols above their 50-bar SMA (`compute_breadth`, features.py:50-54). It is 0.5 unless at least 2 symbols have a price list exactly as long as the benchmark's and at least 50 rows exist (feature_matrix.py:148-161).

The matrix is **not trimmed**: `_rows`, `_closes` and `_benchmark_closes` grow by one per bar (feature_matrix.py:49-51, 122; engine.py:100, 340).

### Standardisation
`ColumnStandardiser` computes a per-column z-score, fitted on each refit's full matrix. A zero-std column becomes std 1.0 (scaling.py:40-54). The same scaler transforms the data for `predict_proba` until the next refit (hmm_core.py:155-159).

### HMM
- `GaussianHMM(n_components=4, covariance_type="diag", random_state=0, n_iter=100)` (hmm_core.py:117-122). It needs at least `2*n_states` rows (:107-111), but the engine's `min_fit_bars=60` is the binding limit (engine.py:346-354).
- `DegenerateRegimeFitError` is raised if any transition-matrix row sums to 0 (hmm_core.py:135-142).
- State signatures are the mean **raw** `log_return` and `realized_vol` per Viterbi-predicted state. An empty state gets NaN (:204-226).
- The constructor raises if `log_return` or `realized_vol` is missing from the features (:85-91).

### Fit and refit schedule
- The engine fits when `not is_fitted or _bars_since_fit >= 20` (engine.py:356). `_bars_since_fit` increases only on a new bar boundary (:340-343).
- After a warm start the model is unfitted, so the first benchmark tick that finds at least 60 rows fits the model. After that it refits every 20 new daily bars.
- The posterior is computed on the full matrix on **every benchmark tick**: `predict_proba(matrix)[-1]` (:362-370). Fit and predict run synchronously inside the bus handler.

### Rules overlay and fusion
`RegimeFusion.compute` (fusion.py:147-186):
1. HMM scores: for each valid state s with posterior p, return z-score rz and vol z-score vz across states:
   - bull += p·clip(rz, 0, 2)
   - bear += p·clip(−rz, 0, 2)
   - sideways += p·max(0, 1−|rz|)
   - high_vol += p·clip(vz, 0, 2)
   - low_vol += p·clip(−vz, 0, 2)

   (:93-136, cap 2.0 at :69)
2. Bull is set to 0 if price < SMA200. SMA200 is computed from the last 200 benchmark closes and is 0.0, which disables the block, when fewer than 200 closes exist (engine.py:569-572; fusion.py:52-54).
3. VIX axis: below 15 adds 1.0 to low_vol; above 25 adds 1.0 to high_vol. These are **hard-coded constants** (fusion.py:27-28, 57-62, 163-167). `settings.vix_shock_level` is **not** read by the regime engine; it is used only by presentation/regime_monitor.py and domain/macro_analysis/signal.py.
4. recession = Φ(−0.53 − 0.63·slope) × (bear + high_vol)/2 (fusion.py:24-25, 41-49, 169-172).
5. recovery = (bull if slope − prev_slope > 0 and SMA200 rising and 0.95 ≤ price/SMA200 ≤ 1.05, else 0) + max(0, slope − prev_slope)·0.5 (:174-180).
   - `_prev_yield_curve_slope` and `_prev_sma_200` are updated on every benchmark tick, not per bar (engine.py:390-391). Both start at 0.0 (:109-110).
6. Scores are normalised over the positive values. If they sum to zero, the result is uniform 1/7 (fusion.py:182-186).

### Hysteresis
`HysteresisGate(margin=0.15, min_persistence=3)` (fusion.py:194-231):
- The first call takes the argmax.
- After that the label changes only when a challenger beats the current label's probability by more than 0.15 on 3 consecutive `update` calls.
- `update` is called once per benchmark tick (engine.py:387), so persistence is counted in **ticks**, not bars.
- Probabilities are published unsmoothed; only the label is sticky.

### Published event
`RegimeEvent(label, probs={7 labels}, exposure_scalar, ts=tick ts)` goes out on every benchmark tick after warm-up (engine.py:396-403). The scalar table (fusion.py:30-38) is:

| Label | Exposure scalar |
|---|---|
| bull | 1.0 |
| recovery | 0.9 |
| low_vol | 1.0 |
| sideways | 0.7 |
| bear | 0.5 |
| high_vol | 0.4 |
| recession | 0.3 |

`RegimeHealthEvent` is published on every change of state and on the first report (engine.py:424-446).

**RegimeEvent consumers:**
- StrategyEngine (probs and label; strategies/engine.py:230-244)
- RiskEngine (`regime_scalar`, `regime_label`; risk_engine/engine.py:139-141)
- TradeLedger (`regime_at_entry` and the probability of the label; domain/performance/trades.py:1065-1067, 1099-1100)
- UI: dashboard, workbench, regime_monitor and ai_advisor

`RegimeHealthEvent` is consumed only by `MainWindow` (main_window.py:84).

### Before the first classification
- The engine publishes `RegimeHealthEvent(False, "warming up …")` and no `RegimeEvent` (engine.py:346-354).
- RiskEngine keeps `regime_scalar=1.0` and `regime_label=None` (risk_engine/engine.py:115, 127).
- StrategyEngine refuses entries (Stage E).
- If the warm start or the benchmark seed failed, the first classification needs 60 live daily bars (warm_start.py:110-117).

### Failure behaviour
- A fit exception or `DegenerateRegimeFitError` is logged with per-feature ranges and returns False. No event is published for that tick, even if an earlier fit exists, and the fit is retried on each later benchmark tick (engine.py:356-360, 502-513).
- A posterior exception is logged and nothing is published (:362-370).
- After a failure, StrategyEngine and RiskEngine keep the **last published** probabilities, label and scalar. Neither subscribes to `RegimeHealthEvent`.
- Constant columns are logged by name (:466-481). The feature-spread share is logged (:489-499). `non_monotonic_fits` is counted (:514-518); nothing in `src` reads it.

### Summary for Stage D
- **Decision authority:** the label sets the position-size multiplier in RiskEngine (risk_engine/engine.py:234). The probability distribution decides strategy eligibility in StrategyEngine.
- **Persistence:** none. The label and hysteresis state are in memory only.
- **Deterministic or AI:** a statistical HMM (hmmlearn) with a fixed `random_state=0`, plus deterministic rules. No LLM import. `ai_advisory` publishes nothing on the bus (grep for `publish(` and SignalEvent/RegimeEvent in domain/ai_advisory: no matches).
- **Broker order influence:** the scalar multiplies the share count of every order through `RiskEngine.evaluate_order` (engine.py:234). Eligibility decides whether StrategyEngine emits entry signals at all.

## Stage E: Strategy eligibility and swing signals

### Deployment
- `default_strategies()` builds 15 strategies. Swing is built as **`SwingStrategy()` with no arguments** (runtime.py:109-126, 120), and that is the only `SwingStrategy(` constructor call in `src`.
- `StrategyEngine(bus, [], …)` starts with an empty set. `_deploy_configured` deploys each name in `settings.deployed_strategies_tuple` (default `""`, config.py:85, 938-940) and logs an ERROR for unknown names (runtime.py:830-872).
- The Workbench can add strategies from `available_strategies` for the current session only (presentation/workbench.py:426-435).
- Whether "swing" is actually configured is **NOT DETERMINED** (see the scope limit).

### StrategyEngine per tick
`_on_market_data` (strategies/engine.py:359-453):
1. Record the tick into the bars (always).
2. Return if `emitting` is False (outside the session; session_controller.py:183, 199).
3. Return if the symbol is stale.
4. Return if nothing is deployed.
5. Fetch fundamentals once per symbol, cached in memory for the life of the process. The first fetch is an awaited network call when `fundamentals_source="yfinance"` (:380-383). Because `bus.publish` awaits all handlers, this holds up `MarketDataFeed._process_loop`.
6. Build the `SymbolContext` and `FeatureSnapshot`. Positions come from `broker.positions()`, cached for 5 s; on failure it uses the last cache or `{}` (:195-228).
7. For each strategy, compute `eligible`, run `on_features`, and publish each signal unless it is ineligible and does not close an open position (:442-453). "Closes an open position" means side == "sell" and account-level held quantity > 0 (:455-469).

### Eligibility
`is_eligible` (:258-290):
- `requires_regime` defaults to True and runtime does not override it (runtime.py:860-871). **Until any RegimeEvent arrives, every strategy is ineligible**, so there are no entries; exits still pass (:285-286, 442-453). This is warned once (:408-421).
- After that: eligible if Σ probs over `suitable_regimes()` ≥ `regime_eligibility_mass` (default 0.5, config.py:814; runtime.py:866).
- The label-membership fallback on `default_regime=SIDEWAYS` (:287-289) needs empty probs after a regime has arrived. `RegimeEvent` always carries 7 probabilities (engine.py:399), so in the live runtime this branch is reached only with `requires_regime=False`.
- Swing's suitable regimes: **{sideways, bull, low_vol, recovery}** (swing.py:38-65).

### Swing logic
`SwingStrategy.on_features` (swing.py:115-178). The bars are StrategyEngine's daily frame **including the forming bar**: `iloc[-1]` is today's running price and `iloc[-2]` is the prior bar.

**Parameters.** All are constructor defaults; none comes from Settings (swing.py:24-36):

| Parameter | Value |
|---|---|
| `fast_window` | 20 |
| `slow_window` | 50 |
| `atr_window` | 14 |
| `atr_stop_multiple` | 2.5 |
| `reward_risk` | 2.0 |

`settings.atr_stop_multiple` (config.py:183, also 2.5) is read by RiskEngine's fallback stop (risk_engine/engine.py:217), **not** by swing.

**Steps:**
1. **Guard.** If `len(bars) < max(50,14)+2 = 52`, return nothing (:76-80, 117-118).
2. **EMAs.** `ewm(span=20, adjust=False)` and `ewm(span=50, adjust=False)` on close (:82-89). `in_uptrend = EMA20[-1] > EMA50[-1]` (:121).
3. **SELL.** If `held > 0` (account position for this symbol from the snapshot, :130), and not `in_uptrend`, emit `SignalEvent(side="sell", conviction=1.0, meta={"exit_reason":"trend_broken","ema_fast","ema_slow"})` (:131-146). If held > 0 and still in an uptrend, return nothing (:149).
4. **BUY.** Requires `held <= 0` and all of the following:
   - `in_uptrend` (:151-152)
   - `close[-2] <= EMA20[-2]`, the pullback (:154-156)
   - `close[-1] > EMA20[-1]`, the reclaim (:157-159)
   - ATR(14) at the last bar not NaN and > 0. ATR is a simple rolling mean of true range, computed by `compute_atr` (features.py:30-40) (:161-163).
   - Then:
     - `stop = close[-1] − 2.5·ATR`
     - `target = close[-1] + 2.0·(close[-1] − stop)`, which is close + 5·ATR
     - `conviction = clip((close[-1] − EMA20[-1])/EMA20[-1]·20, 0.1, 1.0)`
     - Emit `SignalEvent(side="buy", meta={"stop_price","target_price","atr"})` (:164-178).
5. Nothing de-duplicates at the strategy: signals repeat on every tick while the conditions hold. The bridge is where it becomes idempotent (signal_bridge.py:1313-1348).

### Swing summary
- **State:** `strategies`, `_current_regime`, `_current_probs`, `_regime_is_real`, `_stale_symbols`, `_eligibility`, `_fundamentals_cache`, `_context_cache`, `_positions_cache`, `emitting` (strategies/engine.py:65-117). Swing itself holds no state.
- **Persistence:** none (the deployed set is not persisted). `CachingFundamentalsSource` reads and writes `Path(settings.data_dir) / "fundamentals_cache.json"` when fundamentals come from yfinance (fundamentals_cache.py:28, 39; runtime.py:439-440).
- **Failure:** a positions failure falls back to cache or `{}`, which suppresses exits (:220-224). Handler exceptions are logged by the bus. `YFinanceFundamentalsSource` returns an empty snapshot on error (yfinance_fundamentals.py:96-103).
- **Refusals:** no entries before the first regime. No entries when mass < 0.5. No signals for stale symbols, outside the session, or with nothing deployed. An ineligible strategy's sells pass only if the symbol is held.
- **LLM:** none (imports checked).

### Chain to a broker order
1. **`SignalToOrderBridge._on_signal`** (signal_bridge.py:1312-1350):
   - Skip if the symbol already has an order pending sign-off.
   - Skip if the bridge bars have fewer than 2 rows (`_MIN_HISTORY_FOR_SIZING=2`, :316).
   - `price` = the bridge aggregator's last close.
   - A SELL goes to `_handle_sell`: minimum-hold check, then `oms.submit_exit_order` for the full held quantity. With nothing held and shorting off, it is dropped (:1397-1411).
   - A BUY is skipped if already held or if there is a live buy. Otherwise the weekly turnover cap applies (:1429-1438), then `_submit_sized` with swing's `stop_price` and `target_price` from meta (:1443-1452).
   - `_submit_sized` needs bridge ATR > 0 (:1490-1494), builds an `OrderCandidate` and calls `oms.submit_order` (:1584-1590).
2. **`OMS.submit_order`:** checks the entry allow-list, anomalies, pending corporate actions and the kill switch (oms.py:330-370), then runs `RiskEngine.evaluate_order`. There, swing's stop is used when it is below price (`stop_source="strategy"`), and shares are multiplied by `regime_scalar` (risk_engine/engine.py:213-234).
3. An approved order goes to `pending_signoff`. **Only `OMS.sign_off` calls `broker.place_order`** (oms.py:1-10, 869, 1067). Sign-off is done by a human, or by `AutonomousExecutor` when `settings.autonomy_enabled` (execution_mode "auto", not live without the extra flag; config.py:953-963).

## (1) Configurable parameters in scope

**Settings fields** (`config.py`, env prefix `QAT_`):

| Field | Default | Line | Read at |
|---|---|---|---|
| `market` | "US" | 901 | runtime.py:572 |
| `market_data_source` | "synthetic" | 687 | runtime.py:179-226, 784-786, 920; history.py:218-232; bar_series_feed.py:198 |
| `alpaca_data_feed` | "iex" | 759 | |
| `alpaca_poll_seconds` | 60.0 | 762 | |
| `yfinance_poll_seconds` | 60.0 | 866 | |
| `market_data_delay_seconds` | 1200.0 | 879 | yfinance only |
| `data_staleness_seconds` | 900.0 | 579 | |
| `bar_interval_seconds` | 86400.0 | 861 | |
| `session_follows_market_hours` | True | 783 | |
| `session_poll_seconds` | 20.0 | 784 | |
| `watchlist_category` | "curated" | 902 | |
| `watchlist_curated_us` | "SPY,AAPL,MSFT,GOOGL" | 909 | |
| `watchlist_curated_asx` | "STW.AX,BHP.AX,CBA.AX,CSL.AX" | 910 | |
| `watchlist_max_symbols` | 10 | 911 | |
| `watchlist_min_avg_volume` | 100000 | 912 | synthetic volume |
| `fred_series` | ("DGS3MO","DGS10","T10Y3M","VIXCLS","BAA10Y") | 17, 637 | |
| `bar_macro_series` | () | 647 | |
| `regime_vix_series` | "VIXCLS" | 661 | |
| `regime_features` | 6 columns | 840-847 | |
| `regime_eligibility_mass` | 0.5 | 814 | |
| `vix_shock_level` | 25.0 | 679 | **not read by the regime engine** |
| `deployed_strategies` | "" | 85 | |
| `fundamentals_source` | "mock" | 770 | |
| `fundamentals_cache_days` | 7.0 | 774 | |
| `data_dir` | from paths | 636 | |
| `atr_stop_multiple` | 2.5 | 183 | RiskEngine fallback only |
| `allow_short_selling` | False | 623 | bridge |
| `entry_allow_list` | "" | 464 | OMS |

**Secrets (not Settings):** `FRED_API_KEY` (runtime.py:369), and the Alpaca key and secret (alpaca_source.py:67-75).

**Hard-coded, not configurable:**
- MarketDataFeed: check interval 5 s, queue 1000, feed-down 300 s, lag constants 200/20/300 (market_data.py:32-34, 89-91).
- yfinance: failures 5, backoff cap 300 s, down fraction 0.5, `period="1d"`/`interval="1m"` (yfinance_source.py:84, 248-250, 437-439).
- Synthetic fallback: seed 1, interval 1 s (runtime.py:208, 226).
- Warm start: 300 bars. MacroFeed: 3600 s (runtime.py:820). BarSeriesFeed: 3600 s and 5 days.
- Aggregators: max_bars 500/500/250.
- FeatureBuilder: 20/14/50.
- Regime: n_states 4, refit 20, min_fit 60, SMA 200, vol window 20, breadth window 50 and neutral 0.5, breadth missing fraction 0.10, series names T10Y3M and BAA10Y.
- HMM: diag covariance, seed 0, 100 iterations.
- Fusion: probit −0.53/−0.63, VIX 15/25, bonus 1.0, z cap 2.0, scalar table, recovery band 0.95-1.05 and 0.5 weight.
- Hysteresis: 0.15 margin, 3 updates.
- StrategyEngine: SIDEWAYS default, 5 s position cache, `requires_regime=True`.
- Swing: all parameters in the table above. Bridge: `_MIN_HISTORY_FOR_SIZING=2`.

## (2) Present in code but not wired into the running system
- `data/validation.py`: all five functions have no `src` caller (tests only).
- `FeatureEvent`: `FeatureEngine` publishes it with no subscriber in `src`, so its feature computation has no consumer.
- `symbols.canonical()`: no caller.
- `features.compute_cross_sectional_zscore`: no caller.
- `settings.vix_shock_level`: not used by RegimeEngine or fusion, which hard-code 25.0.
- `DGS3MO` and `DGS10`: fetched and published, but `RegimeFeatureBuilder.update_macro` ignores them.
- `RegimeEngine.non_monotonic_fits` and `MarketDataFeed.observed_delay_seconds`: no reader outside their own module and logging.
- StrategyEngine's `default_regime` label fallback: unreachable in the live runtime while `requires_regime=True`.
- `RegimeHealthEvent` and `MarketDataFeedEvent`: consumed only by the UI (`MainWindow`). No engine acts on them.
- `AlpacaMarketDataSource`, `AlpacaHistorySource` and `BarSeriesFeed`: built only under the setting conditions above.
- `preflight.py`: not imported by `app.py` or `runtime.py`. How it is invoked is **NOT DETERMINED** from `src`.

## (3) NOT DETERMINED
- The deployed values of `market`, `market_data_source`, `deployed_strategies` (including whether swing is deployed), `watchlist_*`, `bar_macro_series`, `regime_vix_series` and `broker`. This needs the `.env` file under `%LOCALAPPDATA%`, which was out of scope.
- Whether `FRED_API_KEY` is set, i.e. real or mock macro data. This needs the keyring.
- Startup races: ticks or MacroEvents published before StrategyEngine or RegimeEngine subscribe. MarketDataFeed and MacroFeed are registered before them, and `SignalToOrderBridge.start` awaits broker calls in between (runtime.py:948-960; signal_bridge.py:412-428). Settling this needs runtime observation.
- Whether Yahoo's daily history includes today's partial bar during the session. This affects whether the regime seed's last row and the aggregators' forming bar are "today".
- The exact behaviour of `hmmlearn`'s internal initialisation. It is a library outside `src`.
