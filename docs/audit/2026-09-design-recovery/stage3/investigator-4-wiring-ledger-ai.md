> **Audit evidence, Stage 3.** A fresh-context investigator, 12 September 2026.
> Its instructions: read only `src/qat` and `tests`; no documentation, git
> history or narrative; comments are claims; facts only, each with a
> file:line; no judgements. Reproduced as returned. **Not yet
> cross-verified.** Report section 5 records any correction found in
> cross-checking. (The deployed configuration differs from the defaults it
> assumed in places: `fundamentals_source=yfinance` and both LLM slots
> `local`, per report §3.)

# Stage 3 - Investigator 4: Wiring, ledger and AI boundary

**Method.** I read only files under `src/qat/`, and a few test file names under `tests/` (as grep hits). I read no `*.md`, no git history and nothing outside those two folders. One grep hit fell outside scope: `scripts/repair_fill_basis.py` references `audit_closed_trades`. I did not open it. Every reference below is relative to `src/qat/`. Where a comment claims something, it is marked **comment claims**, and I say whether the code I read matches.

## PART 1 - Runtime wiring

### 1.1 Entry sequence (`app.py`)
1. `ensure_app_dir()` runs (app.py:42), then `migrate_legacy_layout()` (app.py:43). The migration copies `./.env` and `./data/**` from the working directory into the app dir. It never overwrites (migration.py:87-123).
2. `Settings()` is built (app.py:45). It reads `.env` from `app_dir()/.env` (config.py:31-42, paths.py:59-61). The app dir is `%LOCALAPPDATA%/QuantAdvisoryTerminal`, or `QAT_HOME` if set (paths.py:36-56). The data dir is `<app_dir>/data` (paths.py:64-66, config.py:636).
3. `configure_logging(settings.log_level, settings.data_dir)` runs (app.py:46).
4. `RunMarker.claim()` writes `session_running.json` (app.py:64-67).
5. `Runtime.build_demo(settings=settings)` builds every component (app.py:69).
6. `MainWindow(runtime)` is built. It constructs 9 screens (main_window.py:89-100).
7. `loop.run_until_complete(runtime.orchestrator.start_all())` runs, then `run_forever()` (app.py:90-91).
8. The `finally` block only logs and calls `marker.release()` (app.py:92-98). **`Orchestrator.stop_all` has no caller anywhere in src** (grep: only its definition at orchestrator.py:44 and comments). No engine `stop()` runs through the orchestrator on exit.

### 1.2 What resolves for broker=ibkr, market=ASX, market_data_source=yfinance, execution_mode=auto (trading_mode=paper)

| Slot | Resolver | Result | Ref |
|---|---|---|---|
| Watchlist | `universe.resolve_watchlist` | `watchlist_curated_asx` (default `STW.AX,BHP.AX,CBA.AX,CSL.AX`), filtered by a *synthetic* volume, capped at `watchlist_max_symbols` | runtime.py:571; universe.py:307-339; config.py:910-912 |
| Benchmark | `MARKET_BENCHMARKS["ASX"]` | `STW.AX` | runtime.py:572; universe.py:35 |
| Broker | `resolve_broker` | `IBAdapter(IB(), bus, settings=settings)`. There is **no MockBroker fallback** for ibkr. A missing `ib_async` import or a constructor error propagates. | runtime.py:301-350 |
| Market data | `resolve_market_data_source` | `YFinanceMarketDataSource(poll_seconds=yfinance_poll_seconds)`. Falls back to `SyntheticMarketDataSource` with a warning if construction raises. | runtime.py:210-226 |
| History | `resolve_history_source` | `RealHistorySource()` | data/history.py:230-231 |
| Macro | `resolve_macro_source` | `FredMacroSource()` if the `FRED_API_KEY` secret exists, else `MockMacroSource(seed=1)` | runtime.py:369-385 |
| Bar-series feed | `resolve_bar_series_feed` | `None` unless `bar_macro_series` is non-empty (default `()`) | data/bar_series_feed.py:195-211; config.py:647 |
| Fundamentals | `resolve_fundamentals_source` | Default `fundamentals_source="mock"` gives `MockFundamentalsSource(seed=1)`. `yfinance` gives a `CachingFundamentalsSource`. | runtime.py:428-447; config.py:770 |
| Earnings calendar | `_build_earnings_calendar` | Default (`fundamentals_source="mock"`) gives `NullEarningsCalendar`. Only `yfinance` gives `YFinanceEarningsCalendar(data_dir)`. | runtime.py:399-409 |
| News | `resolve_news_source` | Default `news_source="yfinance"` gives `YFinanceNewsSource` | runtime.py:166-168; config.py:727 |
| LLM slots | `resolve_llm_engines` | Both default to `"demo"`, giving `DemoLLMEngine` ×2 | runtime.py:450-462, 138-154; config.py:897-898 |
| Session gating | inline | `True` (`session_follows_market_hours` and source ≠ synthetic) | runtime.py:919-921 |
| Autonomy | `Settings.autonomy_enabled` | `True` (auto and not live) | config.py:953-963 |

If `trading_mode="live"`, `IBAdapter.__init__` raises `LiveTradingNotConfirmedError`, because runtime never passes `live_trading_confirmed` (ib_adapter.py:244-249; runtime.py:350). No src code passes `live_trading_confirmed=` anywhere (grep). Nothing in `build_demo` (runtime.py:585) or `main` (app.py:69) catches it, so a live+ibkr configuration cannot start. **Comment claims** (runtime.py:336-339) that "only the in-app confirmation dialog may set it". No such setter exists in src. Separately, paper mode with `ibkr_port` in {4001, 7496} raises `LivePortInPaperModeError` (ib_adapter.py:101, 250-258).

### 1.3 Construction order inside `build_demo` (runtime.py)
1. `EventBus` (574), then `Orchestrator(bus)` (575).
2. `KillSwitch(data_dir)` (578), then `KillSwitchEngine(bus, kill_switch)` (579).
3. `RiskEngine(bus, kill_switch, settings)` (581). Internally it builds `KellyVolTargetSizer`, `PortfolioRiskChecker`, `PortfolioGovernor`, `CostModel` and `AuditLog(data_dir, market)` (domain/risk_engine/engine.py:108-114).
4. Broker: `IBAdapter` (585).
5. `DecisionJournal(data_dir)` (589).
6. `OMS(broker, risk_engine, kill_switch, bus, journal, settings, entry_allow_list=settings.entry_allow_list_set())` (590-602). The OMS builds `PositionAnomalyStore(data_dir)` and `RestingOrderAnomalyStore(data_dir)` and loads `absorbed_fills.json` (domain/oms/oms.py:219-263).
7. `AccountPoller(broker, interval_seconds=account_poll_seconds)` (605).
8. `TradeLedger(bus, data_dir, settings)` (609). It reads `closed_trades.csv` at construction (domain/performance/trades.py:622).
9. `CommissionAuditor(data_dir, settings)` (612). It is passed to `broker.set_commission_listener` if the broker has that method; IBAdapter does (runtime.py:613-615; data/broker/ib_adapter.py:1258-1260).
10. `SignalToOrderBridge(bus, oms, settings, bar_interval_seconds, bar_tz, trade_ledger, earnings_calendar, warm_symbols=watchlist)` (616-633). It reads `open_position_entries.json` at construction (domain/oms/signal_bridge.py:402-403).
11. `CorporateActionMonitor(oms, settings, entries_source=bridge.entry_open_dates)` (640-644). It is then assigned into `bridge.corporate_actions` (648) and `oms.corporate_actions` (652).
12. `PositionCloser(oms, broker, kill_switch, _LiveEntries(bridge))` (660).
13. `BookRiskMonitor(account_poller, bars=bridge.bars, settings, SECTOR_BY_SYMBOL)` (667-672).
14. `EquityMonitor(broker, kill_switch, settings, bus)` (678), `ReconciliationMonitor(oms, settings, bus)` (683), `DeleverSweep(oms, risk_engine.governor, settings, bus)` (684).
15. `EquityCurve(data_dir, market)` (691). It is assigned into `equity_monitor.equity_curve` (695).
16. `PerformanceReporter(trade_ledger, equity_curve, settings, journal)` (696-701), with `.pending_actions` set to a lambda (706-708).
17. `AutonomyGate(settings, kill_switch, scorecard_source=_scorecard_for)` (718). `_scorecard_for` calls `build_scorecard(strategy, trade_ledger.closed_trades(strategy), settings)` (710-716).
18. `AutonomousExecutor(bus, oms, gate, journal, equity_monitor, settings, fallback_price=_last_known_price)` (743-751). `_last_known_price` reads `bridge.bars` (720-741).
19. `MarketDataFeed(bus, source, feed_symbols, staleness_seconds, source_delay_seconds)` (795-801). `feed_symbols` = benchmark + watchlist, de-duplicated (777). `autonomy_gate.last_print_source = market_data_feed.last_print_at` (811).
20. `FeatureEngine` (812-816); history source (817); macro source (819); `MacroFeed(bus, macro, fred_series, poll_interval_seconds=3600.0)` (820); bar-series feed (823); fundamentals (825-827).
21. `default_strategies()` (828): 15 strategies (109-126).
22. `StrategyEngine(bus, [], fundamentals, bar_interval_seconds, bar_tz, regime_eligibility_mass, position_source=broker)` (860-871). `_deploy_configured` then deploys the names in `deployed_strategies` (830-851, 872).
23. `RegimeEngine(bus, benchmark_symbol, breadth_symbols=watchlist, bar_interval_seconds, bar_tz, features=regime_features, vix_series=regime_vix_series)` (874-882).
24. `WarmStart(history_source, macro, feed_symbols, benchmark, aggregators=(strategy_engine.bars, bridge.bars, feature_engine.bars), regime_engine, macro_series=fred_series)` (890-898).
25. `LLMRouter(anthropic_slot, local_slot, settings)` (901-903), `AIAdvisoryService(router, risk_engine, settings)` (904). `performance_reporter.narrator = _narrate_report` (906-914).
26. `SessionController(market_data_feed, strategy_engine, market, enabled=session_gating, poll_seconds)` (922-928).
27. The news source is resolved inside the `Runtime(...)` constructor call (1005).

### 1.4 Registration and start order (runtime.py:930-974; started sequentially by orchestrator.py:39-41)
1. `BrokerConnection(broker)`: `await broker.connect()` (runtime.py:260-265)
2. `warm_start`
3. `kill_switch_engine`
4. `risk_engine`
5. `equity_monitor`
6. `reconciliation_monitor`: adopts broker positions and scans resting orders at start (domain/oms/reconciliation.py:55-80)
7. `delever_sweep`
8. `trade_ledger`: subscribes to OrderFilled, EntryPriceCorrected, ExitPriceCorrected, Regime and MarketData events (trades.py:729-734)
9. `performance_reporter`
10. `market_data_feed`
11. `feature_engine`
12. `macro_feed`
13. `strategy_engine`
14. `autonomous_executor`
15. `corporate_action_monitor`
16. `signal_bridge`: its start runs `reconcile_entry_prices`, `reconcile_entry_strategies`, `restore_open_lots`, `replay_missed_exits`, `rearm_protective_stops`, then launches the sweep and warm-earnings tasks (signal_bridge.py:412-428)
17. `regime_engine`
18. `book_risk_monitor`
19. `session_controller`
20. `bar_series_feed`, only when configured (973-974)

`Orchestrator.start_all` has no per-engine exception handling (orchestrator.py:39-42). If `IBAdapter.connect` exhausts its 6 attempts it re-raises (ib_adapter.py:312-337, 423-429). That aborts `start_all` at engine #1, so nothing later starts, and the exception leaves `main` through the `finally` at app.py:92-98. `WarmStart.start` catches its own exceptions (domain/warm_start.py:66-73). The ReconciliationMonitor start catches adoption and scan failures (reconciliation.py:59-79).

### 1.5 Settings fields passed explicitly (beyond the whole `settings` object)

| Component | Explicit fields | Ref |
|---|---|---|
| KillSwitch | `data_dir` | runtime.py:578 |
| OMS | `entry_allow_list_set()` | runtime.py:601 |
| AccountPoller | `account_poll_seconds` | runtime.py:605 |
| TradeLedger, CommissionAuditor, DecisionJournal | `data_dir` | runtime.py:609, 612, 589 |
| SignalToOrderBridge | `bar_interval_seconds`, `MARKET_TIMEZONES[market]` | runtime.py:620-621 |
| EquityCurve | `data_dir`, `market` | runtime.py:691 |
| MarketDataFeed | `data_staleness_seconds`; `market_data_delay_seconds` (because the source is yfinance) | runtime.py:784-786, 799-800 |
| YFinance source | `yfinance_poll_seconds` | runtime.py:219 |
| FeatureEngine | `bar_interval_seconds`, tz | runtime.py:812-816 |
| MacroFeed / WarmStart | `fred_series` (MacroFeed poll hard-coded to 3600 s) | runtime.py:820, 897 |
| StrategyEngine | `bar_interval_seconds`, tz, `regime_eligibility_mass`, `deployed_strategies_tuple` | runtime.py:860-872 |
| RegimeEngine | `bar_interval_seconds`, tz, `regime_features`, `regime_vix_series` | runtime.py:874-882 |
| LLM resolution | `general_request_provider`, `sensitive_request_provider`, `local_llm_base_url` | runtime.py:138-154, 459-462 |
| SessionController | `market`, `session_follows_market_hours`, `market_data_source`, `session_poll_seconds` | runtime.py:919-928 |

The full `Settings` object goes to: RiskEngine, IBAdapter, OMS, TradeLedger, CommissionAuditor, SignalToOrderBridge, CorporateActionMonitor, BookRiskMonitor, EquityMonitor, ReconciliationMonitor, DeleverSweep, PerformanceReporter, AutonomyGate, AutonomousExecutor, LLMRouter, AIAdvisoryService, AnthropicEngine and LocalEngine.

### 1.6 Constructed but not orchestrator-registered
OMS, AccountPoller, DecisionJournal, CommissionAuditor, PositionCloser, AutonomyGate, EquityCurve, LLMRouter, AIAdvisoryService, the LLM engines, the history/fundamentals/news sources and the earnings calendar.

### 1.7 Present in src, not constructed for this configuration
- `AlpacaAdapter` (data/broker/alpaca_adapter.py)
- `AlpacaMarketDataSource` / `AlpacaHistorySource` (data/alpaca_source.py)
- `MockBroker` (only for broker=mock or an alpaca fallback)
- `SimulatedBroker` (only replay_session.py:54 and capabilities.py:147)
- `SyntheticMarketDataSource` / `SyntheticHistorySource` (only on fallback)
- `MockMacroSource` (only without a FRED key)
- `YFinance*Fundamentals`, `CachingFundamentalsSource`, `YFinanceEarningsCalendar` (only with `fundamentals_source="yfinance"`)
- `BarSeriesFeed` (only with `bar_macro_series`)
- `AnthropicEngine` / `LocalEngine` (only if a provider is chosen)
- Never imported by the app: `data/ibkr_news.py`, `data/broker/ib_probe.py`, `preflight.py`, `data/validation.py`, `domain/evaluation/replay_agreement.py`, `domain/backtester/{replay_session, manifest, run_comparison, ablation, macro_cache, research_universe, replay_sources}.py`, `data/store/{db,parquet}.py`, `domain/performance/fill_basis_repair.py`

## PART 2 - Ledger, evidence and reporting

### 2.1 How fills reach the ledger
`TradeLedger._on_fill` consumes `OrderFilledEvent` (trades.py:1086-1110). There are two publishers.

- **`OMS._announce_fill`** (oms.py:1164-1208), called from sign-off after transmit (oms.py:1161).
  - It publishes when status is "filled" **or "transmitted"** (1167).
  - `price = order.filled_price or order.reference_price` (1169).
  - `quantity = order.quantity`, the full order size (1177).
  - `price_is_fill = bool(order.filled_price)` (1185).
  - `ts = self._now()`, i.e. transmit time (1206).
  - For IBKR, `filled_price` is set only if `avgFillPrice` is truthy when `from_ib_trade` runs (data/broker/ib_translate.py:368-369).
  - Protective-stop sign-offs return before announcing (oms.py:1114-1132).
- **`OMS.absorb_broker_fills`** (oms.py:2065-2257) handles executions the app did not send.
  - `strategy=None`, `stop_price` defaults to None, `price_is_fill=True`, `ts=fill.filled_at` (2213-2231).
  - For executions of the app's own orders it publishes nothing. Instead it may publish `EntryPriceCorrectedEvent` or `ExitPriceCorrectedEvent` (2125-2137, 2316-2413).

The EventBus runs handlers concurrently. Handler exceptions are logged and swallowed (domain/bus.py:34-47).

### 2.2 Lot matching
- A buy appends an `OpenLot` to a per-symbol deque (trades.py:1089-1109).
- A sell calls `_close_against_lots`: FIFO from `lots[0]`, `matched = min(remaining, lot.quantity)` (1139-1201).
- One `ClosedTrade` is written per lot matched, per sell event (1221-1254).
- A partially consumed lot is replaced by a remainder lot (1260-1280). The remainder **does not carry `earnings_at_entry` or `order_id`**; both fall to their `None` defaults (fields at 268-275 are not passed).
- A surplus sell quantity with no lot is logged and ignored (1282-1292).
- `restore_open_lot` refuses if the symbol already has lots (711-712).

### 2.3 Costs and commission apportionment
- The cost model exists only if `apply_costs_in_paper or is_live` (trades.py:597-601).
- `charge(notional) = max(min_commission, notional·bps) + third_party` (domain/backtester/costs.py:74-96). **Slippage is excluded** (costs.py:86-96).
- ASX/fixed profile: 8.8 bps with a 6.60 floor, unless `commission_bps` or `broker_min_commission` is explicitly set (costs.py:51-65, 183-189).
- Per-order accumulation: `_increment_cost(order_id, qty, price)` charges each piece the difference between the order's cumulative charge with and without that piece. State is in the in-memory `_charged` dict (1120-1137, 607). With no order id, each piece is costed as a whole order (1131-1132).
- Entry cost is held whole on the lot. At close it is apportioned `entry_cost·matched/lot.quantity`; the remainder keeps the rest (1234, 1270).
- Exit cost is apportioned `exit_cost_total·matched/exit_quantity` across the lots that sell closes (1145-1146, 1235).
- Restored lots are costed `_fill_cost(quantity, price)`, where quantity is the *current broker quantity* (721; signal_bridge.py:779, 790-793).

### 2.4 Which price is recorded

| Field | Source | Ref |
|---|---|---|
| Entry (live) | `OrderFilledEvent.price` at transmit: the fill if known, else `reference_price`. `reference_price` = last bar close at sizing time. | trades.py:1094; oms.py:1169; signal_bridge.py:1328; oms.py:540-546 |
| Entry (corrected) | `EntryPriceCorrectedEvent.price` replaces `lot.price` **only if `lot.order_id == event.order_id`**. Entry cost and excursion seeds are recomputed. | trades.py:743-774 |
| Entry (restored at startup) | `_entries[symbol].price`, possibly overwritten by `reconcile_entry_prices` from the broker `avg_price`. For IBKR that average is converted back from commission-inclusive, except on the floor branch where it is skipped. | signal_bridge.py:532-631, 790-800 |
| Exit (app sell) | Transmit-time `filled_price or reference_price`. The reference depends on the exit path: signal = bar close (1328, 1403); time_stop = tick price (1282, 1310); delever = `pos.avg_price` (delever.py:182-186); manual_close = `entry.price` (position_closer.py:699-703) | oms.py:763, 842-866 |
| Exit (corrected) | `ExitPriceCorrectedEvent` rewrites matched rows on disk and in memory. It changes `exit_price` and `exit_cost` only; `worst_price` and `best_price` are not recomputed. | trades.py:776-913 |
| Exit (broker-side) | `fill.price` from `recent_fills` | oms.py:2219 |

### 2.5 R-multiple, slippage, MAE/MFE (all computed properties)
- `risk_per_share = entry − stop`, or None if there is no stop or the stop ≥ entry (trades.py:392-397).
- `r_multiple = net_pnl / (risk_per_share·qty)` (411-415). `gross_r_multiple` uses the price move only (418-423).
- The stop comes from `order.stop_price = candidate.stop_price or decision.stop_price` (oms.py:546). A strategy stop ≥ price is rejected by the sizer (engine.py:213-218), but it is still preferred on the order. Such a trade records R = None.
- `entry_slippage = entry_price − reference_price`, in currency per share. It is None without a reference (337-344). There is no exit slippage field.
- Excursion:
  - `worst_price` / `best_price` are seeded at the fill (1103-1104).
  - They are updated from every `MarketDataEvent` for the symbol, which for this configuration means the yfinance feed (1070-1084).
  - At close they are folded with the exit price (1219-1220).
  - Restored lots take their excursion from the daily bars after the entry day (signal_bridge.py:703-743), else from the entry price (trades.py:723-724). `replay_missed_exits` passes no reference or excursion (signal_bridge.py:497-504).
- `mae_r = −(entry − worst)/risk` and `mfe_r = (best − entry)/risk` (346-363).

### 2.6 `exit_reason` values

| Value | Set by | Ref |
|---|---|---|
| `signal` | Bridge signal exit; also the default when `_exit_reasons` has no entry for the symbol | signal_bridge.py:1403; oms.py:1187 |
| `time_stop` | Bridge time stop | signal_bridge.py:1310 |
| `delever` | DeleverSweep | delever.py:186 |
| `manual_close` | PositionCloser | position_closer.py:703 |
| `stop` / `target` | Absorbed broker fill: `stop` if `price ≤ 1.02 × known stop`, else `target`. An unknown stop gives `target`. | oms.py:2159, 2225, 2433-2449 |

`_exit_reasons` is keyed by **symbol** and set before the risk check (oms.py:744). It is popped only when a sell is announced (1187). A rejected exit leaves its reason in place for the next sell on that symbol.

### 2.7 `regime_at_entry`, `regime_probability`, `exposure_scalar`
- **Source.** The ledger keeps the last `RegimeEvent` it received: `label`, `probs.get(label)` and `exposure_scalar` (trades.py:1065-1068). These are copied onto a lot only when a **buy** `OrderFilledEvent` arrives (1099-1101).
- `RegimeEvent` is published only on a benchmark tick, once the matrix has at least `min_fit_bars` and the fit succeeds (domain/regime_engine/engine.py:322-404).
- The label comes from hysteresis over the fused probabilities (387). The scalar comes from a fixed table: bull 1.0, recovery 0.9, low_vol 1.0, sideways 0.7, bear 0.5, high_vol 0.4, recession 0.3 (regime_engine/fusion.py:30-38, 65-66). The recorded scalar does not include the earnings scalar.

**They are left blank when:**
1. No `RegimeEvent` has arrived since process start. The initial values are None (trades.py:612-614). `regime_engine` is registered after `signal_bridge`, so startup replays cannot see one (runtime.py:959-960).
2. The lot was restored via `restore_open_lot`, which never sets them (trades.py:713-726). Both the startup restore and `replay_missed_exits` use this path. `open_position_entries.json` does not persist them either (signal_bridge.py:1262-1273). So any position held across a restart closes with all three blank.
3. `regime_probability` alone is None if `label` is not a key of `probs` (1067).

Remainder lots keep all three (1271-1273). `collapse_to_positions` keeps the first member's values (1590-1600).

### 2.8 Collapse to positions
`closed_trades()` groups rows by `(order_id, symbol, opened_at)`. Rows without an `order_id` stay separate. Groups are merged with quantity-weighted prices and summed costs (trades.py:1320-1351, 1539-1602). `order_id` here is the **sell's** id (1244-1248). Every consumer calls `closed_trades()`: EdgeEstimator, scorecards, reports and the Performance screen.

### 2.9 Refusal of impossible trades
If `lot.strategy is not None and event.ts < lot.opened_at`, the ledger logs an ERROR and **returns** (trades.py:1188-1200). That abandons the rest of that sell, including quantity that could have matched later lots, and writes no "unmatched" line. Rows already written earlier in the same loop remain. Lots with no strategy (adopted positions) are exempt.

### 2.10 What the ledger does not react to
It subscribes to the five events listed in 1.4 only (trades.py:729-734). It has **no handler** for `OrderRejectedEvent` or `BrokerOrderIdResolvedEvent`, and none for cancellations. A lot or closed trade booked at transmit stays after a later broker rejection. The OMS's reversal handler touches only `_filled_quantities` (oms.py:1310-1352).

If the transmit-time `order_id` was the app UUID because no permId had arrived yet, a later correction keyed on the permId matches nothing:
- The entry-side lot correction needs an exact id match (trades.py:759).
- The exit-side amendment needs an exact `(order_id, symbol)` match (857, 862).

### 2.11 Entry-record persistence (`open_position_entries.json`)
- **Written** by `_save_entries` (signal_bridge.py:1258-1278) on:
  - every buy or sell `OrderFilledEvent` (1170)
  - each entry-price correction (1188)
  - each M65 price correction (622)
  - each strategy resolution (692)
- **Format:** JSON of symbol → `{opened_at, price, stop_price, target_price, strategy, reference_price, price_source}`.
- **Buy handling:** `setdefault` (1136). A buy for a symbol that already has a record leaves the old record untouched.
- **Record removal on a sell:** only if `broker.positions()` reports flat at that moment (1151-1153, 857-877).
- **Time-stop cleanup:** the time-stop path pops a record without saving (1301-1303). **Comment claims** "Written on every change" (1259-1261); this path does not match.
- **`price_source`:**
  - It is `"fill"` when `event.price_is_fill` is true, else `"reference"` (1147).
  - It is set to `"fill"` on `EntryPriceCorrectedEvent` (1187).
  - M65 skips `"fill"` records (582-585). When M65 overwrites a price it **does not change `price_source`** (618).
  - None means a record written before the field existed (1232-1236).

### 2.12 Ledger audit function
`audit_closed_trades(path)` (trades.py:1616-1670) compares stored `gross_pnl`, `net_pnl`, `pnl_pct` and `r_multiple` against recomputed values (`_DERIVED_COLUMNS`, 1608-1613). It also reports rows it cannot parse. It does not check `entry_slippage`, `mae_r`, `mfe_r`, `gross_r_multiple`, `risk_per_share`, `holding_days` or `held_through_earnings`. **No caller in src.** Callers: tests (`tests/domain/performance/test_the_ledger_file_agrees_with_itself.py`, `tests/domain/performance/test_fill_basis_repair.py`) and the out-of-scope script. `TradeLedger.repair_header` also has no src caller. `repair_csv_header` does run at every load (644, 1433).

### 2.13 Decision journal (`decision_journal.csv`)
- Append-only CSV with 16 fields (decision_journal.py:36-53, 111-125).
- A write is dropped if the `(outcome, reason)` is unchanged for that **symbol**. The dedupe state is in memory, per process, and shared by all writers (92-109).
- **OMS writers** (oms.py:2821-2842) leave market, session phase, equity, cash and day P&L blank. Outcomes written:
  - `proposed` (866)
  - `rejected` (917, 1036, 1078, 2818)
  - `signed_off` (1117, 1145)
  - `rejected_by_operator` (1244)
  - `pending_signoff` (1781)
- **AutonomousExecutor writers:** `auto_signed`, `blocked`, `blocked_by_oms`, with the full account fields (executor.py:197, 212, 222, 285-326).

### 2.14 `risk_decisions.csv`
- `AuditLog.record` appends one row per `evaluate_order` / `evaluate_exit` / `_reject` (audit.py:77-114; engine.py:358, 405, 417).
- Fields: timestamp, symbol, approved, final_shares, stop_price, reason, inputs (JSON), market (audit.py:36-45).
- The in-memory list starts empty on every run; the file is not read back (audit.py:70).
- The file is read by reports through `load_risk_decisions(since, market)` (evaluation/refusals.py:292-328). There is no upper date bound (reporter.py:225-227).
- `win_rate` and `win_loss_ratio` are **not** recorded in `inputs` (engine.py:187-195).

### 2.15 Equity curve
- `EquityMonitor.poll` runs every `equity_poll_seconds` with no session gating (equity_monitor.py:96-104). Each poll calls `EquityCurve.record(equity, cash, position_value=gross_position_value)` (119-132), which appends to `equity_curve.csv` (trades.py:1458-1484). Columns: ts, equity, cash, market, position_value (1403).
- `points()` returns only the trailing run of samples sharing the last market label (1486-1521).
- `equity_state.json` holds `{day, day_start_equity, high_water_mark}` and is written every poll (equity_monitor.py:116-117, 204-209).

### 2.16 Commission audit (`commission_checks.csv`)
- IBAdapter tallies `commissionReportEvent` per permId until `shares ≥ total_quantity`. It then calls the listener, unless any part of the commission was unusable (ib_adapter.py:418-420, 1275-1340).
- `CommissionAuditor.check` compares `report.commission` with `CostModel.charge(notional)`. Agreement requires a difference ≤ 0.01 and a matching currency (commission_audit.py:95-115, 43).
- It appends once per `order_id`. Ids already in the file are skipped (76-93, 116-128, 157-180).
- **Nothing reads the result back into the ledger.** The only src references are its construction and the file itself (grep). It is not included in `session_export.BUNDLED_FILES` (session_export.py:30-39).

### 2.17 Daily and weekly reports
- `PerformanceReporter._run` sleeps 300 s and then calls `maybe_report` (reporter.py:98-106, 66).
- A daily report is written once per trading day after the close (session not open and not "before open"). The guard is `report_state.json:last_daily` (116-146, 278-283).
- The weekly report is written on the last trading day of the week (137-142, 148-157).
- `_build` (208-266) uses:
  - `ledger.closed_trades()`: all markets, all strategies, collapsed
  - `equity_curve.points()`
  - the journal's blocked-reason summary for the period
  - refusals and approvals from `risk_decisions.csv` (market-filtered, `since` only)
  - scorecards per `ledger.strategies()`
  - open lots, pending actions
  - an optional narrator
- `build_report` filters trades by `closed_at` date and equity samples by date (reports.py:271-337). `generated_at` uses the wall clock (311).
- Output is appended as Markdown to `daily_reports.md` / `weekly_reports.md` (412-429).
- `regenerate_daily` appends a superseding report and has **no src caller** (reporter.py:165-198; the grep only finds a comment at presentation/performance.py:272).
- `summarise_blocked_reasons` counts **every** journal row whose outcome does not start with `auto_signed` and that has a reason (reports.py:382-408). That includes `proposed`, `signed_off` and the rest. They appear under the heading "Autonomy decisions blocked" (reports.py:237). **Comment claims** it counts why autonomy declined (reports.py:366-372). The code counts more than that.

### 2.18 Performance statistics (`metrics.py`)
- Everything is computed on `net_pnl` (128-157).
- With fewer than `MIN_TRADES_FOR_STATS = 5` trades, `win_rate`, `profit_factor`, `expectancy` and `average_r` are None (26, 138-152).
- `average_r` averages only trades that have an R (134).
- Sharpe uses consecutive *equity-sample* returns × √252 (182-197). The samples are every `equity_poll_seconds` (60 s by default), and the annualisation constant does not depend on the sampling interval.
- A mixed-currency input logs an ERROR but still computes (115-123).

### 2.19 Scorecard and promotion gate
- `build_scorecard` has five criteria (scorecard.py:74-118):
  - trade count ≥ `max(promotion_min_trades, 5)`
  - net P&L > 0
  - `average_r ≥ promotion_min_average_r`
  - `win_rate ≥ promotion_min_win_rate`
  - worst trade: pass if ≥ 0; otherwise `|worst| ≤ average_win × promotion_max_loss_to_avg_win`; fail if there is no winning trade (144-152)
- `eligible` = all five pass (44-46).
- Trades come from `closed_trades(strategy)` with **no market filter** (runtime.py:715; reporter.py:234-237; presentation/performance.py:414-417).
- **Enforcement exists only in `AutonomyGate.evaluate`**, for buys, when `promotion_evidence_enforced` is true (`enforce_promotion_evidence or is_live`) and a `scorecard_source` exists (gate.py:251-258; config.py:614-616). With the defaults (paper, flag False) it is not enforced; membership in `autonomous_strategies` is enough (gate.py:230-237). Sells and protective orders bypass it (146-195).
- Nothing edits settings from the scorecard. **Comment claims** the Settings screen shows promotion against the scorecard (scorecard.py:14-16). `presentation/settings.py` contains no scorecard reference (grep).

### 2.20 Kelly measured-input switch-over
- `SignalToOrderBridge._submit_sized` calls `self.edge.estimate(strategy)` (signal_bridge.py:1496). That becomes `OrderCandidate.win_rate` / `win_loss_ratio` (1497-1521), then `RiskEngine.sizer.size(...)` (engine.py:202-204).
- The sizer computes `kelly_f = kelly_fraction·max(0, W − (1−W)/R)` and `shares = min(kelly_f·equity/price, per_trade_risk_pct·equity/(atr_stop_multiple·ATR))` (risk_engine/sizing.py:32-40; kelly.py:9-20; backtester/sizing.py:38-45).
- `EdgeEstimator.estimate` (performance/edge.py:85-144):
  - trades = `closed_trades(strategy, market=settings.market)`
  - fewer than `edge_min_trades` → defaults 0.55 / 1.5 (signal_bridge.py:336-337)
  - no losses → defaults
  - otherwise the win rate is clamped to [0.25, 0.75] and `avg_win/|avg_loss|` to [0.5, 4.0] (36-41)
- A WARNING is logged on the first transition to "measured" per strategy (136-143).

### 2.21 PERSISTENCE MAP (all under `settings.data_dir` unless noted)

| File | Writer (module:line) | When | Format | Read by |
|---|---|---|---|---|
| `closed_trades.csv` | domain/performance/trades.py:1310-1314 | Each ClosedTrade (per lot per sell event) | CSV, `_FIELDS` (64-116) | trades.py:645-651 at startup |
| same (header rewrite) | trades.py:162-168 | At load if the header is behind | CSV | - |
| same (amendment) | trades.py:952-960 via `.tmp-<pid>` + `os.replace` | ExitPriceCorrectedEvent match | CSV | - |
| `closed_trades.csv.bak-YYYYmmdd-HHMMSS` | trades.py:1050-1053 | Once per process before the first amendment | copy | - |
| `equity_curve.csv` | trades.py:1473-1481 (rewrite 162-168) | Every equity poll (60 s) | CSV ts, equity, cash, market, position_value | trades.py:1433-1456 |
| `equity_state.json` | domain/autonomy/equity_monitor.py:204-209 | Every equity poll | JSON | equity_monitor.py:190-202 |
| `open_position_entries.json` | domain/oms/signal_bridge.py:1275-1276 | Fills, corrections, reconciliations | JSON | signal_bridge.py:1197-1256 |
| `absorbed_fills.json` | domain/oms/oms.py:1886-1888 | After each absorb pass | JSON watermark + absorbed (30-day retention) | oms.py:1807-1850 |
| `decision_journal.csv` | domain/decision_journal.py:116-123 | Each non-repeat decision | CSV, 16 fields | reporter via `entries()` (127-138) |
| `risk_decisions.csv` | domain/risk_engine/audit.py:90-112 | Each risk decision | CSV with JSON `inputs` | evaluation/refusals.py:292-328 |
| `commission_checks.csv` | domain/performance/commission_audit.py:170-178 | IBKR commission complete, once per order | CSV | commission_audit.py:78-93 (ids only) |
| `daily_reports.md` / `weekly_reports.md` | domain/performance/reports.py:419-429 | After close / regenerate | Markdown, appended | presentation/performance.py:507-508 |
| `report_state.json` | domain/performance/reporter.py:278-283 | After a report is written | JSON | reporter.py:268-276 |
| `kill_switch.json` | domain/risk_engine/kill_switch.py:91-103 | Each trip/reset | JSON | kill_switch.py:55-89 |
| `position_anomalies.json` | domain/oms/anomaly.py:190-214 | Declare/clear | JSON | anomaly.py:150-188 |
| `resting_order_anomalies.json` | domain/oms/resting_order_anomaly.py:210-229 | Declare/clean scan/clear | JSON | resting_order_anomaly.py:173 |
| `corporate_announcements.json` | domain/corporate_actions/announcements.py:131-151 | `remember()`; **not reached on IBKR** (monitor.py:369-381) | JSON | announcements.py:92 |
| `earnings_cache.json` | data/earnings.py:128-131 | `refresh()`; only when fundamentals_source=yfinance | JSON | earnings.py:114 |
| `fundamentals_cache.json` | data/fundamentals_cache.py:84-90 | `put()`; only when fundamentals_source=yfinance | JSON | fundamentals_cache.py:43 |
| `session_running.json` | run_marker.py:47-57; deleted at 65 | Startup; removed on orderly exit | JSON pid, started_at | run_marker.py:69-79 |
| `logs/qat.log*` | logging.py:309-327 | Continuous; 5 MB × 10 | JSON lines | session export |
| `exports/qat-session-<stamp>.zip` | domain/performance/session_export.py:66-89 | Export button (presentation/performance.py:333) | zip | - |
| `<app_dir>/.env` (outside data) | env_file.py:65; migration.py:96 | Settings Save; first-run migration | KEY=VALUE | config.py:41 |
| OS keyring (outside data) | security.py:27 | Secret set | keyring | security.py:17-23 |

Writers with no caller in the running app: `features/<sym>/<date>.parquet` and `backtests/<run>.parquet` (data/store/parquet.py:19-37), the SQLite engine (data/store/db.py:11-17), the backtester macro cache (domain/backtester/macro_cache.py:58-66), `manifest.write` (domain/backtester/manifest.py:186) and `run_comparison` (domain/backtester/run_comparison.py:63-65).

## PART 3 - AI / LLM boundary

### 3.1 Every importer of `domain/ai_advisory`
Exhaustive grep:

- `presentation/runtime.py:44-52` constructs the engines, router and service.
- `presentation/advisory_inputs.py:25` imports `AdvisoryContext`.
- `presentation/regime_monitor.py:36` imports the schema types.
- `presentation/settings.py:44` imports `LocalEngine` for the connection test.
- Callers of `runtime.ai_service`:
  - `presentation/ai_advisor.py:353` (`get_regime_narrative`)
  - `presentation/workbench.py:593` (`get_regime_narrative`)
  - `presentation/regime_monitor.py:286` (`get_macro_matrix_narrative`) and `:469` (`get_macro_assessment`)
  - `presentation/runtime.py:910` (`get_performance_narrative`, used as the report narrator)

No module under `domain/strategies`, `domain/oms`, `domain/risk_engine`, `domain/autonomy`, `domain/performance` (other than the narrator hook attribute) or `data/broker` imports `ai_advisory`. `risk_engine/engine.py:183` mentions it only in a docstring. `get_trade_rationale` has **no src caller**; only tests call it (tests/safety/test_ai_output_breaching_limits_is_blocked.py, tests/safety/test_prompt_injection_in_context_is_ignored.py, tests/domain/ai_advisory/test_service.py).

### 3.2 Engine and provider selection
- The choice is made once, at build (runtime.py:900-903).
- `anthropic` → `AnthropicEngine` if `get_secret("ANTHROPIC_API_KEY")` returns a value, else `DemoLLMEngine` with a warning (runtime.py:142-148).
- `local` → a blocking `GET {base}/models` with a 10 s timeout at startup. Reachable gives `LocalEngine`, otherwise Demo (runtime.py:129-135, 149-153).
- Anything else → Demo.

### 3.3 Router (`router.py:37-49`)
- Non-empty `context.positions` → local slot.
- Otherwise, if `anthropic_available` is false (no caller passes it; the default is True) → local.
- Otherwise, if `_calls_today ≥ ai_cost_budget_calls_per_day` → local.
- Otherwise the "general" kinds (regime_narrative, macro_analysis, performance_narrative) → anthropic slot and the counter increments. Everything else → local.
- `_calls_today` is never reset in code (router.py:35, 44, 47).
- The "local" slot is whatever `sensitive_request_provider` resolves to, and that setting may be `"anthropic"` (config.py:898).

### 3.4 Request types

| Method | Caller | Data sent | Slot | Schema | Destination of output |
|---|---|---|---|---|---|
| `get_regime_narrative` (Advisor) | ai_advisor.py:353 | Symbol and name; regime label and probabilities; all positions `{sym: qty}`; risk metrics (book_now / at_last_decision); fundamentals (+`is_synthetic`); next earnings; held position (qty, entry, last, pnl %, R, distances); rule-check verdict; news (title, providers, date, primary); corporate-action notes; operator question (advisory_account.py:73-139; advisory_inputs.py:95-145; context.py:82-218) | Local if any position is held, else general | `AdvisoryRecommendation` | Rich-text `QTextEdit` (ai_advisor.py:355-359); the rationale is not escaped |
| `get_regime_narrative` (Workbench) | workbench.py:593 | Same, plus `candidate_signal{strategy, last_target_exposure}` and backtest metrics | Same | Same | `QLabel` (workbench.py:596-599) |
| `get_macro_assessment` | regime_monitor.py:469 | Market code, regime label and probabilities, `MacroSignal.to_dict()`, FRED series, `positions={}` (service.py:98-108) | General | `MacroAssessment` | HTML panel (regime_monitor.py:485-508); `suggested_exposure_scalar` is displayed only |
| `get_macro_matrix_narrative` | regime_monitor.py:286 | Decision figures and reasons, friction headline, position count; `positions` go into the context (service.py:180-195) | Local if any position, else general | `MacroMatrixNarrative`, then numbers overwritten from the decision (service.py:199-299) | HTML panel (regime_monitor.py:414-436) |
| `get_performance_narrative` | runtime.py:906-914 via reporter.py:256-264 | Full report Markdown, including opened positions as `SYM xQTY @ $PRICE` (reports.py:129-138) and aggregate stats; `positions={}` in the context (service.py:132-139) | General | `AdvisoryRecommendation` (only `.rationale` is kept) | **Appended to `daily_reports.md` / `weekly_reports.md`** under "Analyst notes" (reports.py:258-259) |
| `get_trade_rationale` | none in src | Context and candidate | Local/general | `GuardedRecommendation` | Would call `risk_engine.evaluate_order` whenever the model's recommendation ≠ hold, writing a `risk_decisions.csv` row (guards.py:57-83; audit.py:77-79) |

**Comment claims** "the report itself contains no position sizes" (service.py:130-131). The report text includes per-symbol quantity and price (reports.py:135-138), so the claim does not match.

### 3.5 Redaction and size cap
- `redact_context_text` replaces only the values of secrets previously requested through `get_secret` (guards.py:30-38; security.py:14-33). Positions, prices, equity and news are not redacted.
- `cap_context_size` **raises** `ContextTooLargeError` above `ai_context_max_chars` (8000); it does not truncate (guards.py:41-46).

### 3.6 Structured output and tools
- **Anthropic.** One tool, `submit_recommendation`, whose `input_schema` is the pydantic schema, forced with `tool_choice`. The `tool_use.input` is validated into the schema. Settings: `max_tokens=1024`, `max_retries=1` (2 attempts), and a retry message on a validation error (llm_engine.py:73-117). The tool is an output channel; nothing executes it, and no agentic loop exists.
- **Local.** POST `/chat/completions` with `response_format` negotiated json_schema → json_object → text, a 60 s timeout, fence stripping, then pydantic validation (llm_engine.py:150-228).
- **Demo.** Canned payloads exist for `AdvisoryRecommendation` and `MacroAssessment` only (llm_engine.py:290-305). `MacroMatrixNarrative` raises `ValueError` (llm_engine.py:326-331). With the default demo slots, the matrix narrative therefore always shows "unavailable" (regime_monitor.py:292-297).

### 3.7 Reachability of AI output (exhaustive result)
- The outputs are consumed only in the rows of the table above: Qt widgets, report Markdown, and log lines (service.py:216-221, 288-291; screens' `logger.exception`).
- There is no path from any AI output to strategy selection, sizing, `RiskEngine.regime_scalar`, sign-off, `OMS`, the broker adapter or settings. Grep of `.recommendation`, the schema class names and `narrative` / `suggested_exposure_scalar` across src finds only those consumers.
- Persistent state the output **does** reach:
  - the report files (via the narrator)
  - `qat.log`
  - potentially `risk_decisions.csv` through the unwired `get_trade_rationale`

### 3.8 When the model is unavailable
- At startup: the Demo engine is substituted (3.2).
- At request time: exceptions propagate out of the service. Each screen catches them and shows an error (ai_advisor.py:360-365; workbench.py:485-491; regime_monitor.py:292-297, 475-481). The reporter logs a warning and writes the report without a narrative (reporter.py:256-264).
- With the default demo slots, every report narrative is the demo notice text (llm_engine.py:280-296).

### 3.9 Trading-path independence
`AIAdvisoryService` is not orchestrator-registered (runtime.py:930-967). No trading-path module imports it (3.1).

### 3.10 Other model calls
- The Settings "Test connection" button posts a 1-token completion directly with `LocalEngine._post` (presentation/settings.py:1295-1318).
- The runtime reachability probe issues a GET to `/models` only (runtime.py:129-135).
- `domain/macro_analysis` imports no LLM code (grep).
- Reporting reaches a model only through the narrator.

## Component cards

- **BrokerConnection** (runtime.py:240-271). Calls `connect` / `disconnect` if present. Deterministic. Failure raises and aborts startup (1.4).
- **TradeLedger**
  - Inputs: OrderFilled, Entry/ExitPriceCorrected, Regime and MarketData events.
  - Outputs: `ClosedTrade` rows and `closed_trades()`.
  - Memory: open lots, the `_closed` list, `_charged`, last regime.
  - Persistence: `closed_trades.csv`.
  - Failure: an OSError is logged. Memory is appended before the disk write, so the two can diverge (trades.py:1300-1316).
  - Refusal: impossible exits (2.9).
  - Deterministic. It influences orders **indirectly**, via EdgeEstimator sizing (2.20) and the scorecard gate when enforced (2.19).
- **EquityCurve / EquityMonitor.** The monitor polls the broker account. It writes the curve and `equity_state.json` and trips the kill-switch on daily-loss / drawdown (equity_monitor.py:134-152). Poll failures are logged and the loop continues. Deterministic. It affects orders through the kill-switch and through `day_pnl_pct` used by the AutonomyGate.
- **CommissionAuditor.** Input: IBKR commission reports. Output: a CSV row and a log line. It never raises (IBAdapter wraps it). Deterministic. No order influence.
- **DecisionJournal / AuditLog.** Append-only. Write failures are swallowed (decision_journal.py:124-125; audit.py:113-114). Deterministic. No order influence, except that the AuditLog's in-memory last entry feeds advisory risk metrics.
- **PerformanceReporter.** Reads the ledger, the curve, the journal, `risk_decisions.csv` and the narrator. Writes Markdown and state. Report failures are logged (reporter.py:105-106). AI-assisted narrative only. No order influence.
- **Scorecard / AutonomyGate evidence check.** Deterministic. Blocks auto sign-off of buys only when enforced.
- **EdgeEstimator.** Deterministic, reads the ledger. Directly sets the Kelly inputs for entry size.
- **SignalToOrderBridge, entry-record part.** Persists `open_position_entries.json`. Restores lots and re-arms stops at start. Deterministic. Influences orders (stops, minimum hold, time stop).
- **AIAdvisoryService, LLMRouter and engines.** AI-assisted. Memory: the router counter only. No persistence except via the narrator into the report files. No order influence (3.7).

## (1) Configurable parameters in scope (config.py; defaults)

| Field | Default | Line |
|---|---|---|
| trading_mode | "paper" | 45 |
| execution_mode | "recommend" | 55 |
| allow_autonomous_live_trading | False | 62 |
| autonomous_strategies | "" | 67 |
| deployed_strategies | "" | 85 |
| equity_poll_seconds | 60.0 | 98 |
| broker | "mock" | 164 |
| ibkr_host / ibkr_port / ibkr_client_id | 127.0.0.1 / 4002 / 1 | 167-169 |
| per_trade_risk_pct | 0.01 | 172 |
| kelly_fraction | 0.5 | 173 |
| edge_min_trades | 20 | 182 |
| atr_stop_multiple | 2.5 | 183 |
| entry_allow_list | "" | 464 |
| delever_sweep_enabled | False | 475 |
| protection_sweep_seconds | 300 | 530 |
| corporate_action_mode | "shadow" | 564 |
| data_staleness_seconds | 900 | 579 |
| ibkr_pricing_model | "fixed" | 389 |
| broker_min_commission / commission_bps / slippage_bps | 6.60 / 5.0 / 5.0 (ASX profile overrides unless explicitly set) | 392-394 |
| apply_costs_in_paper | True | 400 |
| enforce_time_stop / time_stop_trading_days | True / 30 | 431-432 |
| promotion_min_trades | 30 | 586 |
| promotion_min_average_r | 0.2 | 587 |
| promotion_min_win_rate | 0.4 | 588 |
| promotion_max_loss_to_avg_win | 3.0 | 591 |
| enforce_promotion_evidence | False | 599 |
| data_dir | `<app_dir>/data` | 636 |
| fred_series | DGS3MO, DGS10, T10Y3M, VIXCLS, BAA10Y | 17, 637 |
| bar_macro_series | () | 647 |
| market_data_source | "synthetic" | 687 |
| news_source / news_min_sources | "yfinance" / 1 | 727, 751 |
| fundamentals_source | "mock" | 770 |
| enforce_earnings_event_risk | True | 359 |
| session_follows_market_hours / session_poll_seconds | True / 20 | 783-784 |
| account_poll_seconds | 5 | 791 |
| yfinance_poll_seconds | 60 | 866 |
| market_data_delay_seconds | 1200 | 879 |
| anthropic_model | "claude-sonnet-5" | 882 |
| local_llm_base_url / local_llm_model | http://localhost:1234/v1 / "local-model" | 885-886 |
| ai_context_max_chars | 8000 | 887 |
| ai_cost_budget_calls_per_day | 200 | 888 |
| general_request_provider / sensitive_request_provider | "demo" / "demo" | 897-898 |
| market | "US" | 901 |
| watchlist_category / _curated_asx / _max_symbols / _min_avg_volume | curated / STW,BHP,CBA,CSL.AX / 10 / 100000 | 902-912 |
| storage_backend / database_url | sqlite / sqlite:///./qat.db (unwired) | 157-158 |

Hard-coded values that are not settings:

| Value | Ref |
|---|---|
| Edge defaults 0.55 / 1.5 | signal_bridge.py:336-337 |
| Edge clamps | edge.py:36-41 |
| `MIN_TRADES_FOR_STATS = 5` | metrics.py:26 |
| Commission tolerance 0.01 | commission_audit.py:43 |
| Stop/target threshold 1.02 | oms.py:2447 |
| Reporter check interval 300 s | reporter.py:66 |
| MacroFeed poll 3600 s | runtime.py:820 |
| LLM reachability timeout 10 s | runtime.py:106 |
| Local POST timeout 60 s | llm_engine.py:225 |
| Anthropic `max_tokens` 1024 | llm_engine.py:88 |
| Absorbed-id retention 30 days | oms.py:129 |

## (2) Code present but not wired or active
- `AIAdvisoryService.get_trade_rationale` and `guards.check_recommendation_against_risk_limits` (no src caller).
- `audit_closed_trades`, `TradeLedger.repair_header`, `PerformanceReporter.regenerate_daily` (no src caller).
- `domain/performance/fill_basis_repair.py` (no src importer).
- `data/store/db.py`, `data/store/parquet.py`; `database_url` and `storage_backend` are unused.
- `data/ibkr_news.py`, `data/broker/ib_probe.py`, `preflight.py`, `data/validation.py`, `domain/evaluation/replay_agreement.py`, and the backtester replay/manifest/ablation/macro-cache/research-universe/run-comparison modules.
- `Orchestrator.stop_all` (never called).
- The `anthropic_available` router argument (no caller passes it).
- A Demo payload for `MacroMatrixNarrative` does not exist.
- Corporate-action announcements are inactive on IBKR (runtime.py:314-330; monitor.py:369-381).
- The earnings rail and real fundamentals are inactive at the default `fundamentals_source="mock"`.

## (3) NOT DETERMINED
- Whether IBKR's `avgFillPrice` is non-zero when `from_ib_trade` runs at placement. This decides whether entries and exits start as fills or as reference prices. It needs runtime observation.
- Whether a permId is present at transmit. This decides whether corrections can match ledger rows (2.10). It needs runtime observation or a full read of `IBAdapter.place_order`.
- Whether `broker.positions()` reports flat at the instant the sell event is handled, which decides entry-record deletion (2.11).
- The contents and role of `scripts/repair_fill_basis.py` (outside scope).
- Whether the yfinance or anthropic libraries write their own cache files, and the Anthropic SDK's default timeout (outside src).
- The internals of `ReconciliationMonitor.poll`, `DeleverSweep`, `BookRiskMonitor`, `StrategyEngine`, `MarketDataFeed` and `KillSwitchEngine` beyond the lines cited. Their full behaviour needs a read of those files.

## Other comment claims checked against code
- llm_engine.py:2-3 describes LocalEngine as `json_object`. The code negotiates three modes (27, 189-216).
- ai_advisor.py:6-10 says the question travels in `fetched_notes`. The code sends it in `operator_question` (ai_advisor.py:311-323; context.py:211-217).
- prompts.py:72-75 says importing `macro_analysis` would be a new dependency. service.py:36-38 already imports it.
- config.py:274-277 says nothing reads `macro_growth_series`. regime_monitor.py:332 reads it.
- summary.py:94 says costs include "modelled slippage". Ledger costs exclude slippage (costs.py:86-96).
- The `OrderFilledEvent` docstring says "an order actually filled" (events.py:83-89). It is also published at transmit (oms.py:1167).
- The scorecard docstring mentions "a drawdown beyond tolerance" (scorecard.py:10-11). The code checks the worst trade against the average win.
