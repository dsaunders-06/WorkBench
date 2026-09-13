> **Audit evidence, Stage 3.** A fresh-context investigator, 12 September 2026.
> Its instructions: read only `src/qat` and `tests`; no documentation, git
> history or narrative; comments are claims; facts only, each with a
> file:line; no judgements. Reproduced as returned. **Not yet
> cross-verified.** Report section 5 records any correction found in
> cross-checking. (The deployed configuration it calls NOT DETERMINED is in
> report §3.)

# Stage 3 - Investigator 2: Signal to pending order

**Scope:** what the code does between a strategy's `SignalEvent` and an `Order` with status `pending_signoff`. All paths are relative to `src\qat\`. I read only `src\qat\` and a few files under `tests\`. I did not read any `.md`, any git history, or the operator's `.env`, which lives at `app_dir()/.env` (`paths.py:59-61`). The **default** configuration comes from `config.py`. The **running** configuration is NOT DETERMINED.

## 0. Wiring (`presentation/runtime.py`)

- **Construction order:**
  - `KillSwitch(data_dir)` (581 context: `runtime.py:578`).
  - `RiskEngine(bus, kill_switch, settings)` (`runtime.py:581`). It builds its own `KellyVolTargetSizer`, `PortfolioRiskChecker`, `PortfolioGovernor`, `CostModel.from_settings` and `AuditLog` (`risk_engine/engine.py:108-114`).
  - `OMS(broker, risk_engine, kill_switch, bus, journal=DecisionJournal(data_dir), settings, entry_allow_list=settings.entry_allow_list_set())` (`runtime.py:589-602`).
    - `max_order_pct_of_cash` and `symbol_allow_list` are **not passed**. So `max_order_pct_of_cash` comes from settings (`oms/oms.py:183-187`) and `symbol_allow_list` is `None` (`oms.py:188`).
  - `TradeLedger` (`runtime.py:609`).
  - `SignalToOrderBridge(bus, oms, settings, bar_interval_seconds, bar_tz, trade_ledger, earnings_calendar=_build_earnings_calendar(settings), warm_symbols=watchlist)` (`runtime.py:616-633`).
    - `default_win_rate`, `default_win_loss_ratio` and `max_history` are not passed, so the defaults 0.55 / 1.5 / 250 apply (`signal_bridge.py:336-338`).
  - `CorporateActionMonitor` is attached to both the bridge and the OMS (`runtime.py:640-652`).
  - `DeleverSweep(oms, risk_engine.governor, …)` (`runtime.py:684`). It uses the same governor instance and no `poll_seconds`, so the default is 300 s (`risk_engine/delever.py:55`).
  - `AutonomousExecutor` (`runtime.py:743-751`).
- **Engine start order:** broker connection → warm start → kill-switch engine → risk engine → … → strategy engine → autonomous executor → corporate-action monitor → signal bridge → regime engine (`runtime.py:930-967`).
- **The only publisher of `SignalEvent` in `src`** is `domain/strategies/engine.py:453`.
- **Event bus:** `publish` awaits every handler with `asyncio.gather(return_exceptions=True)`. A handler exception is logged as "EventBus handler failed" and is not re-raised (`domain/bus.py:34-44`).

## Stage A - Signal to order candidate (`domain/oms/signal_bridge.py`)

**Entry point:** `_on_signal` (1312-1350), subscribed at `start()` (414).

### What it does, in execution order

1. **Pending de-dup.** If `event.symbol in oms.pending_signoff_symbols()`, it returns silently (1321-1322).
   - That set holds every order with status `pending_signoff`, of any side or type, including protective stops and exits (`oms.py:834-840`). So a pending protective stop or exit on a symbol also suppresses buy and sell signals for it.
2. **History.** It takes `bars = self.bars.frame(symbol)`. If there are fewer than 2 rows (`_MIN_HISTORY_FOR_SIZING = 2`, line 316), it returns silently (1324-1326).
3. **Price.** `price = bars["close"].iloc[-1]` (1328). The frame includes the forming bar (`data/bars.py:290-303`).
4. **Holding.** `positions = await oms.broker.positions()` (1330). This call is **not wrapped**. An exception goes to the bus and is logged there, and no refusal is recorded.
   - `held` is the broker quantity for the symbol, or 0.0 (1331-1334).
5. **Sell branch.** If `side == "sell"`, it calls `_handle_sell` (1336-1338). See the SELL list below.
6. **No pyramiding.** If `held > 0`, it returns silently (1340-1341).
7. **Committed buy.** If `oms.has_live_buy(symbol)` (any buy with status `pending_signoff` or `transmitted`, `oms.py:1667-1672`), it returns silently (1347-1348).
8. **Weekly entry budget.** In `_submit_entry`: if `_entries_this_week(now) >= settings.max_entries_per_week`, it logs INFO and returns (1429-1438).
   - The count covers timestamps in the in-memory list `_entry_times` within the last 7 calendar days (1417-1420).
   - `_entry_times` gets a timestamp on **every** buy `OrderFilledEvent` (1150). OMS publishes that event when an order reaches `filled` **or** `transmitted` (`oms.py:1167`).
   - `_entry_times` is not persisted, so it starts empty on every start (407).
9. **Stop and target from strategy metadata.** `_meta_price` accepts positive int or float values only (319-326, 1450-1451). Only `swing` sets both (`strategies/swing.py:164-175`). `breakout` sets `stop_price = prior_high` (`strategies/breakout.py:51`).
10. **ATR.** In `_submit_sized`, ATR(14) is computed from the bridge's bars (`data/features.py:30-40`, window 14). If ATR is NaN or ≤ 0, it returns silently (1490-1494).
11. **Edge.** `edge = self.edge.estimate(strategy)` (1496). See Stage B.
12. **Earnings lookups.** `days_to_earnings = _earnings_distance(calendar, symbol)` and `earnings_date = calendar.next_earnings(symbol)`. Both are wrapped, and any exception becomes `None` (195-207, 1454-1467).
    - The calendar is `NullEarningsCalendar` unless `enforce_earnings_event_risk and fundamentals_source == "yfinance"` (`runtime.py:399-400`). The default `fundamentals_source` is `"mock"` (`config.py:770`).
    - When it is real, `YFinanceEarningsCalendar(settings.data_dir)` is built **without a `market` argument** (`runtime.py:402`), so `market="US"` (`data/earnings.py:107`). Distances are then counted on the US trading calendar and US trading date (`earnings.py:240-242`), and dates are converted to the US timezone (`earnings.py:296`), whatever `settings.market` is.
    - Lookups read the cache only (`earnings.py:191-202`). The cache TTL is 1 day (`earnings.py:105`). It is refreshed only by the one startup warm task (`signal_bridge.py:428, 430-457`). No other caller of `refresh` exists in `src`.
13. **Sector.** `sector = SECTOR_BY_SYMBOL.get(symbol)` (1520). If the symbol is unmapped, a WARNING is logged once per session. There is no gate (1522-1529).
14. **Account read.** `account = await oms.broker.account()` is wrapped. On failure, `oms.record_unsized_signal(...)` writes a rejected order with the reason "account unavailable: …" and returns (1546-1559).
15. **Portfolio inputs.**
    - `existing_weights = {pos.symbol: pos.quantity * pos.avg_price}` (1560). That is entry or average cost. On IBKR, `avg_price` = `avgCost` (`data/broker/ib_translate.py:585`), and the adapter declares that figure commission-inclusive (`ib_adapter.py:225`).
    - `existing_returns` holds per-held-symbol daily returns, indexed by timestamp, excluding the candidate (1571-1577, 170-192).
16. **Hand-off.** `await oms.submit_order(candidate, account.net_liquidation, existing_weights, existing_returns, SECTOR_BY_SYMBOL)` (1584-1590). This call is not wrapped.

### Stage A summary

- **Inputs:** `SignalEvent` (symbol, side, strategy, meta). `conviction` is not read anywhere in the bridge, OMS or risk engine. Also the bridge's own bar aggregator (daily bars, `max_bars=250`, 395-397), broker positions and account, the ledger (for edge) and the earnings calendar.
- **Outputs:** an `OrderCandidate` (`risk_engine/engine.py:46-79`) passed to `OMS.submit_order`, or an exit request to `OMS.submit_exit_order`, or nothing.
- **Decision authority:** the bridge's own code. No human is involved.
- **State in memory:**
  - `_entries` (persisted), `_entry_times`, `_time_stopped`, `_hold_blocked`, `_unmapped_sectors_logged`, `_earnings_calendar_warmed` (403-409, 371).
  - `_hold_blocked` is only ever added to (1387) and nothing in `src` reads it.
- **Persistence:**
  - `Path(data_dir)/"open_position_entries.json"`: read at construction (402-403, 1190-1256). Written on every buy/sell fill, entry-price correction and startup reconciliation (1170, 1188, 622, 692, 1258-1278).
  - `data_dir/"earnings_cache.json"` (`earnings.py:34, 109, 128-133`).
  - Rejections go through the OMS journal (see G).
- **Failure behaviour:**
  - `positions()` failures in `_on_signal` (1330) and `_check_time_stop` (1299) propagate to the bus.
  - An `account()` failure becomes a recorded refusal (1546-1559).
  - Earnings failures become `None`.
  - `_save_entries` catches `OSError` and logs it (1277-1278).
- **Refusal behaviour:** drops at steps 1, 2, 6, 7 and 10 are silent (no journal or audit row). Step 8 writes an INFO log only. Step 14 writes a journal "rejected" row.
- **Interactions:** reads OMS pending and live orders. Its fills feed `_entries`, which drives the minimum hold, the time stop, re-arming and the weekly budget. The earnings distance feeds the RiskEngine earnings scalar.
- **Deterministic?** Yes. No LLM import (imports at 47-64). It does depend on the wall clock through `_now()` (1413-1415) and `datetime.now` in the earnings cache TTL (`earnings.py:146`).
- **Can it influence a broker order?** Yes. It decides whether a candidate or exit request exists at all, and it sets the price, stop and target carried into the order.

## Stage B - Position sizing

- **Sizer:** `KellyVolTargetSizer.size` (`risk_engine/sizing.py:32-40`).
  - `kelly_f = kelly_fraction × max(0, W − (1−W)/R)` (`risk_engine/kelly.py:9-20`).
  - `kelly_shares = kelly_f × equity / price` (`sizing.py:38`). The Kelly fraction is applied as a fraction of equity **notional**.
  - `cap_shares = per_trade_risk_pct × equity / (atr_stop_multiple × ATR)` (`backtester/sizing.py:38-45`).
  - Result: `max(0, min(kelly_shares, cap_shares))` (`sizing.py:40`).
  - **Comment claims** "blended with volatility targeting" (`sizing.py:1-2`). The code takes the minimum of the two, and the "volatility target" is only the ATR-stop fixed-fractional formula. No separate annualised volatility target exists in this path.
- **Per-trade risk / stop distance**, in `RiskEngine.evaluate_order`:
  - The stop distance is `price − candidate.stop_price` if the strategy gave a stop below price. Otherwise it is `atr_stop_multiple × ATR` (`engine.py:213-219`).
  - If `raw_shares × stop_distance > per_trade_risk_pct × equity`, raw shares are trimmed to `budget / stop_distance` (`engine.py:229-232`).
  - Net effect: `raw = min(kelly, pct·E/(k·ATR), pct·E/stop_distance)`.
  - For buys, the effective stop is `max(0, price − stop_distance) or None` (`engine.py:226-228`).
- **Win rate and payoff inputs:** `EdgeEstimator.estimate(strategy)` (`domain/performance/edge.py:85-144`).
  - It returns the defaults W=0.55, R=1.5 when:
    - there is no ledger or no strategy (92-93);
    - there are fewer than `edge_min_trades` (default 20) closed trades for that strategy **in `settings.market`** (102-109);
    - stats are missing (112-113), which happens when there are fewer than `MIN_TRADES_FOR_STATS = 5` (`performance/metrics.py:26, 145`);
    - there are no losing trades (115-123).
  - Otherwise it uses measured values clamped to W ∈ [0.25, 0.75] and R ∈ [0.5, 4.0] (36-41, 125-132).
  - Measured values come from **net P&L in money per closed position**, not R-multiples (`metrics.py:128-147`). `closed_trades` collapses fills to positions and filters by strategy and market (`performance/trades.py:1320-1351`).
  - Derived arithmetic: at the defaults with `kelly_fraction` 0.5, f = 0.5 × 0.25 = 0.125, which is 12.5% of equity notional. At the lower clamps (0.25, 0.5), f* is negative, so f = 0 and the order is rejected with "Sizing produced zero shares".
  - Short entries go through `_submit_short` with no strategy (`signal_bridge.py:1411, 1477`), so they always use the defaults.
- **Where it runs:** inside `evaluate_order`, which OMS calls (see C).
- **State and persistence:** none, except `EdgeEstimator._last_source`, which only controls logging (edge.py:83, 136-143). The ledger is read in memory.
- **Deterministic?** Yes. No LLM.

## Stage C - Risk engine `evaluate_order` (`domain/risk_engine/engine.py:167-359`), exact order

| # | Line | Condition | Effect | Parameter (default) |
|---|---|---|---|---|
| C1 | 197-200 | `kill_switch.tripped` | **REJECT** | - |
| C2 | 202-208 | sizer returns ≤ 0 | **REJECT** "Sizing produced zero shares" | `kelly_fraction` 0.5, `per_trade_risk_pct` 0.01, `atr_stop_multiple` 2.5 |
| C3 | 213-232 | `raw × stop_distance > per_trade_risk_pct × equity` | **TRIM** (`resized_for_stop_budget`) | `per_trade_risk_pct` 0.01, `atr_stop_multiple` 2.5 |
| C4 | 234, 143-165 | `raw × regime_scalar × earnings_scalar` | **TRIM** (multiplier). The earnings multiplier applies to buys only, when `0 ≤ days_to_earnings ≤ blackout` | regime scalar (see F), `enforce_earnings_event_risk` True, `earnings_blackout_days` 5, `earnings_event_size_scalar` 0.5 |
| C5 | 241-254 | buy and `available_cash` not None: `(cash − min_cash_reserve)/price < 1` | **REJECT** "Insufficient cash"; otherwise **TRIM** to affordable (`resized_for_cash`) | `min_cash_reserve` 1.0 |
| C6 | 266-286 | buy only: `PortfolioGovernor.evaluate` (see D) | **REJECT** if not allowed; otherwise **TRIM** to `max_shares` (`resized_by_governor`) | see D |
| C7 | 297-319 | buy only: `PortfolioRiskChecker.check` (sells get `_APPROVED_SELL`, 35-43) | **REJECT** on ES / single-name / sector | see D |
| C8 | 332-347 | buy and `apply_costs_in_paper or is_live`: `risk_dollars ≤ 0` or `round_trip > max_cost_to_risk_pct × risk_dollars` | **REJECT** "too small to carry its fees" | `max_cost_to_risk_pct` 0.10, `apply_costs_in_paper` True |
| C9 | 349-359 | - | APPROVE, with `final_shares = scaled_shares` (continuous) and `stop_price = effective_stop` | - |

- **Logging and audit:** every approval and every rejection writes a `RiskDecision` through `AuditLog.record`, to the in-memory list and to `data_dir/"risk_decisions.csv"` (`audit.py:29, 73, 77-114, engine.py:358, 417`).
  - The `inputs` dict records: price, equity, `regime_scalar`, `regime_label`, `available_cash`, `stop_source`, `stop_distance`, `resized_*` flags, `days_to_earnings`, `earnings_event_scalar`, governor inputs, `portfolio_check` VaR95/VaR99/ES/single-name/sector, `round_trip_cost` and `cost_to_risk_pct`.
  - A CSV write failure is logged and swallowed (`audit.py:113-114`).
- **Comment claims vs code:**
  - The module docstring gives the order as "sizing → stop/max-loss → portfolio VaR/ES/concentration → regime scalar → gate" (engine.py:1-4). The code applies the regime scalar at C4, **before** the cash rule and the portfolio checks.
  - The cost rail comment says it needs "the FINAL share count" (321-324). It uses the risk engine's final count, but OMS later floors and trims the quantity (G9-G12) without running the cost rail again.
- **State in memory:** `regime_scalar` (default 1.0) and `regime_label` (default None). Both are set only from `RegimeEvent` (115-141) and are not persisted.
- **Failure behaviour:** any exception inside `evaluate_order` is caught by OMS and becomes a rejected order (`oms.py:394-414`).
- **Deterministic?** Yes. No LLM import (engine.py:21-30).
- **Can it influence a broker order?** Yes. It approves, rejects and sets the share count and the bracket stop.

### `evaluate_exit` (engine.py:371-406), used by every exit

1. Kill switch → **REJECT**.
2. `quantity ≤ 0` → **REJECT**.
3. Otherwise APPROVE at exactly `quantity`, with an audit row.

There is no sizing, governor, cash or cost check on exits.

## Stage D - Portfolio governor (`risk_engine/governor.py`) and portfolio risk checker (`risk_engine/portfolio_risk.py`)

### Governor snapshot (`governor.py:95-162`)

- **Held positions:**
  - Price per position = `prices.get(sym) or pos.current_price or pos.avg_price` (130). The trading path passes no `prices` (`engine.py:267-280`), so it uses the broker mark when the adapter reports one (IBKR `portfolio().marketPrice`, `ib_adapter.py:1611-1637`), otherwise average cost.
  - Risk per share = `price − stop`, where the stop is `OMS._position_stops[sym]`. If there is no stop, or the stop is ≥ price, the **whole price** counts (262-268).
  - `_position_stops` is filled from:
    - an entry's `stop_price` at sign-off (`oms.py:1139-1140`);
    - a signed protective stop (1114-1116);
    - broker resting stops at adoption (1408-1411);
    - replacement with the broker's level when it has drifted (1620).
  - It is emptied for lost stops (1613), with a one-check grace period while a protective order awaits sign-off (1602-1614).
- **Pending buys** (`OMS.pending_orders()` = `pending_signoff` + `transmitted`, `oms.py:784, 830-832`):
  - valued at `reference_price`;
  - risk = `qty × (ref − stop)` if the stop is below ref, otherwise `qty × ref`;
  - pending sells are skipped (136-154).
- **Position count** = held symbols + pending-buy symbols not held (145-146, 159).

### Governor `evaluate` (272-501), in order

| # | Line | Check | Effect | Parameter (default) |
|---|---|---|---|---|
| D1 | 297-298 | equity ≤ 0 | REJECT | - |
| D2 | 299-300 | proposed shares ≤ 0 | REJECT | - |
| D3 | 304-308 | new name and `position_count ≥ max_concurrent_positions` | REJECT (at `>=`) | `max_concurrent_positions` 10 |
| D4 | 310-316 | headroom = cap − `risk_at_stop_dollars`; headroom ≤ 0 | REJECT | `max_aggregate_risk_at_stop_pct` 0.05 |
| D5 | 318-322 | candidate risk per share ≤ 0 | REJECT | - |
| D6 | 324-329 | `headroom / per_share_risk < 1` | REJECT; otherwise a limit | - |
| D7 | 341-356 | single name: held (qty × **avg_price**) + pending buys (× ref) | REJECT if affordable < 1; otherwise a limit | `max_single_name_concentration_pct` 0.15 |
| D8 | 370-388 | sector (only if `candidate_sector and sector_by_symbol`): held (× avg_price) + pending buys | REJECT if < 1; otherwise a limit | `max_sector_concentration_pct` 0.30 |
| D9 | 407-429 | correlated cluster: held symbols whose correlation with the candidate is ≥ threshold, over the last `correlation_window_bars` of the inner-joined overlap, with ≥ 20 shared observations (42, 208-221). Held value at **avg_price**, pending orders **not** included | REJECT if < 1; otherwise a limit | `correlation_cluster_threshold` 0.70, `correlation_window_bars` 60, `max_correlated_cluster_pct` 0.30 |
| D10 | 442-452 | gap: `(max_gap × E / gap_shock) − gross_exposure` (gross from the snapshot: marks + pending) | REJECT if < 1 share; otherwise a limit | `gap_shock_pct` 0.06, `max_gap_risk_at_shock_pct` 0.05 |
| D11 | 472-481 | `final = min(proposed, all limits)` | TRIM | - |

- **Price basis differs inside the governor:** D4 and D10 use the broker mark (130). D7, D8 and D9 use `avg_price` through `(prices or {}).get(sym, pos.avg_price)` (343, 375, 417).

### PortfolioRiskChecker (`portfolio_risk.py:71-131`)

- **Inputs:**
  - Weights = `existing_weights` (qty × avg_price from the bridge, no pending orders) + the candidate's dollar exposure at the post-governor share count (`engine.py:288-289`).
  - Returns = the held series + the candidate's series.
  - The portfolio return series is the inner join (dropna) of the series weighted by `weight/equity` (133-180). Duplicate timestamps are dropped (161-170).
- **Measures:**
  - Historical VaR 95 and VaR 99 are computed but **not gated**. They are only recorded (92-93, `engine.py:311-317`).
  - ES 97.5 = the mean of returns at or below −VaR97.5 (39-47). Fewer than 2 observations gives 0.0 (33-34, 41-42).
- **Gates, in order:**
  1. ES > `portfolio_es_limit_pct` (0.03) → REJECT (117-118).
  2. Single name > 0.15 → REJECT (119-124).
  3. Sector > 0.30 → REJECT (125-129).
- **Comment claims:** the governor's single-name trim "leaves the checker downstream as a backstop that now never has cause to fire" (`governor.py:338-340`). For buys that reach it, the checker's single-name and sector figures use a basis no larger than the governor's (no pending orders, the same avg_price, and held-symbol buys are already blocked at A6/A7). I found no case where it fires apart from floating-point equality at the boundary. I did not prove this exhaustively.

### De-lever (`risk_engine/delever.py`)

- Every 300 s (55, 77-80) it computes `delever_fraction` from a snapshot **without pending orders** (`governor.py:505-534`). The target is `cap × delever_target_fraction_of_cap (0.9)`.
- It always logs a WARNING when over the cap (143-165).
- If `delever_sweep_enabled` (default **False**), it calls `oms.submit_exit_order(sym, floor(held × fraction), price=avg_price, reason="delever")` for every position (166-190). Those orders land in pending sign-off.

### Stage D summary

- **State and persistence:** the governor and checker hold no state. They read OMS in-memory `_position_stops` and `_orders`. `_orders` is not persisted: the only file OMS itself writes is `absorbed_fills.json` (`oms.py:120, 1888`).
- **Failure behaviour:** exceptions propagate into the OMS try block and become a rejected order.
- **Deterministic?** Yes. No LLM.

## Stage E - Cost controls

- **Model selection:** `CostModel.from_settings` (`backtester/costs.py:43-65`).
  - It looks up `MARKET_COST_PROFILES[(settings.market, settings.ibkr_pricing_model)]` (51).
  - It uses the profile's `commission_bps` **unless `"commission_bps"` is in `settings.model_fields_set`** (52-57).
  - It uses the profile's `min_commission` unless `"broker_min_commission"` is in `model_fields_set` (58-59).
  - `slippage_bps` always comes from settings. `third_party_bps` always comes from the profile, or 0 when there is no profile.
- **ASX + `ibkr_pricing_model="fixed"` (the default, `config.py:389`):**
  - Profile `_ASX_FIXED`: 8.8 bps, min 6.60, third-party 0 (`costs.py:183-189`).
  - So the ASX rate is **8.8 bps if `commission_bps` was not explicitly supplied**, or the supplied value (for example 5.0) if it was.
  - The floor is 6.60 either way unless `broker_min_commission` is set explicitly. The settings default is also 6.60 (`config.py:392`).
  - Slippage is 5.0 bps (`config.py:394`).
  - Tiered: 8.8 bps, min 5.50, third-party 0.45375 bps (`costs.py:195-212`).
  - US has no profile, so it uses the settings values (`costs.py:214-217`; tests `test_market_cost_profiles.py:116-125`).
  - Tests confirm that an explicit init kwarg beats the profile (`tests/.../test_market_cost_profiles.py:109-113`).
- **Is `commission_bps` explicit in the running config? NOT DETERMINED.**
  - The Settings screen's `save_now` writes neither `QAT_COMMISSION_BPS` nor `QAT_BROKER_MIN_COMMISSION` (`presentation/settings.py:1341-1385`).
  - Whether the operator's `.env` or environment contains them was not examined, because it is outside the permitted scope.
  - Whether env/.env-sourced values count as "set" is pydantic-settings library behaviour. No test in the repo covers it.
- **Cost-to-risk rail (C8):**
  - `round_trip = 2 × apply(notional)`.
  - `apply = max(min, bps × N) + third_party + slippage` (`costs.py:74-84, 130-144`).
  - `risk_dollars = scaled_shares × stop_distance` (`engine.py:333-334`).
  - Limit is 10%. Buys only.
  - Derived arithmetic, ASX fixed at 8.8 bps and N > 7,500: round trip ≈ 0.276% of notional. With a 10% limit that implies a stop distance of at least about 2.76% of price.
- **Slippage handling:** modelled only as bps inside the cost rail. The sizing price is the last bar close. The entry is a market order: `Order.order_type` defaults to `"market"` (`adapter.py:53`) and OMS sets no limit price.
- **Deterministic?** Yes. Refusal is a REJECT recorded in the audit and the journal.

## Stage F - Other sizing modifiers

- **Regime scalar:**
  - `RiskEngine.regime_scalar` is set by `RegimeEvent` (`engine.py:139-141`), published only by `regime_engine/engine.py:396-403`.
  - The value is `exposure_scalar_for(label)` = BULL 1.0, RECOVERY 0.9, LOW_VOL 1.0, SIDEWAYS 0.7, BEAR 0.5, HIGH_VOL 0.4, RECESSION 0.3 (`regime_engine/fusion.py:30-38, 65-66`).
  - It defaults to 1.0 before any event arrives (`engine.py:115`).
  - It applies to buys **and** short sells (`engine.py:234`).
  - Upstream, `StrategyEngine.is_eligible` returns False for every strategy until a RegimeEvent arrives (`requires_regime=True` default; `strategies/engine.py:63, 285-286`). That blocks entry signals, not exits (442-445).
  - The regime model is an HMM with `random_state=0` (`regime_engine/hmm_core.py:76, 117-121`). It is deterministic and has no LLM.
- **Earnings scalar:** see C4. It abstains when `days_to_earnings` is None.
- **No-leverage / cash reserve:** see C5. OMS also rejects when cash is None (G8).
- **Max order % of cash:**
  - `cap = max_order_pct_of_cash × spendable_from(cash, min_cash_reserve)`, where `spendable_from` = `max(0, cash − reserve)` (`adapter.py:261-276`).
  - It trims to `floor(cap / price)`, and rejects if the result is < 1 (`oms.py:484-519`). Default 0.10 (`config.py:225`).
  - It is not applied to exits (749-761 comment; no such code in `submit_exit_order`).
- **Broker max order shares:** trims to the ceiling if one is set (`oms.py:524-535`). The default is `None`, so it is off (`config.py:299`). It is applied only in `submit_order`, not in `submit_exit_order`.

## Stage G - `OMS.submit_order` (`domain/oms/oms.py:322-551`), exact order

| # | Line | Condition | Effect |
|---|---|---|---|
| G1 | 316-320, 330-332 | `symbol_allow_list` (None in runtime) or `entry_allow_list` (None at the default `""`, `config.py:942-951`) excludes the symbol | REJECT |
| G2 | 338-340 | position anomaly for the symbol (`position_anomalies.json`, `anomaly.py:26`) | REJECT |
| G3 | 347-351 | resting-order anomaly (`resting_order_anomalies.json`) | REJECT |
| G4 | 360-367 | corporate action pending (`monitor.pending_action`) | REJECT. The monitor only records actions for **held** symbols with a resting stop (`corporate_actions/monitor.py:177, 191-196`; `detector.py:89-95`). On a broker without `announcements` (IBKR) it fetches nothing new (`monitor.py:369-381`). |
| G5 | 369-370 | kill switch tripped | REJECT |
| G6 | 375 | `broker.account()` | **Not wrapped.** An exception propagates to the bridge and then to the bus; no refusal is recorded. |
| G7 | 394-418 | `risk_engine.evaluate_order(... available_cash=account.cash, positions=await broker.positions(), position_stops, pending_orders)`: an exception, or not approved, or ≤ 0 shares | REJECT (with the risk reason) |
| G8 | 430-437 | `int(final_shares) < 1` | REJECT (always floored) |
| G9 | 456-462 | `account.cash is None` | REJECT. The engine skipped C5 in this case, so an "approved" audit row can coexist with this rejection. |
| G10 | 484-492 | `spendable is None` | REJECT. Unreachable after G9. |
| G11 | 493-519 | notional > 10% of spendable | TRIM (INFO log only); REJECT if < 1 share |
| G12 | 524-535 | shares > `broker_max_order_shares` | TRIM (off by default) |
| G13 | 537-551, 842-867 | - | Creates `Order(status="pending_signoff", reference_price=candidate.price, strategy, stop_price=candidate.stop_price or decision.stop_price, take_profit_price, earnings_date)`. Journals "proposed" and publishes `OrderPendingSignoffEvent`. |

- **Stop precedence:** at G13, `candidate.stop_price or decision.stop_price` means a strategy stop that is **≥ price** is still attached to the order, even though the engine sized with the ATR stop in that case (`engine.py:213-218`).
- **Recording:**
  - Every refusal creates a `rejected` Order in memory (`oms.py:2801-2819`) and a `decision_journal.csv` row (`decision_journal.py:34`; `oms.py:2821-2842`). Journal failures are swallowed.
  - OMS trims (G11, G12) appear only in the log. The audit row keeps the sizer's figure.
- **After pending (outside scope, noted for interaction):**
  - `sign_off` re-checks the kill switch, protective-stop quantity and cash (`oms.py:906-1056`). It is the only caller of `broker.place_order` (1067).
  - In "auto" mode, `AutonomousExecutor` reacts to `OrderPendingSignoffEvent` and may **reduce** quantity before `sign_off` (`autonomy/executor.py:157-203`). It is off by default (`config.py:55, 953-963`).

## Ordered list 1 - BUY, signal to pending order

1. `signal_bridge.py:1321`: any `pending_signoff` order on the symbol → silent drop.
2. `:1325`: fewer than 2 bars → silent drop.
3. `:1330`: broker positions read (not wrapped).
4. `:1340`: held > 0 → silent drop.
5. `:1347`: live buy (`pending_signoff` or `transmitted`) → silent drop.
6. `:1430`: ≥ `max_entries_per_week` (10) in the last 7 days → drop (INFO log).
7. `:1493`: ATR(14) invalid → silent drop.
8. `:1496-1509`: edge lookup; earnings distance and date (cache only; Null calendar by default).
9. `:1522`: unmapped sector → WARNING once (no gate).
10. `:1547`: account read fails → REJECT (journalled).
11. `oms.py:330`: allow lists → REJECT.
12. `oms.py:338`: position anomaly → REJECT.
13. `oms.py:347`: resting-order anomaly → REJECT.
14. `oms.py:360`: corporate action pending → REJECT.
15. `oms.py:369`: kill switch → REJECT.
16. `oms.py:375`: account read (not wrapped).
17. `engine.py:197`: kill switch → REJECT.
18. `engine.py:202`: Kelly/ATR sizer gives 0 → REJECT.
19. `engine.py:230`: per-trade stop budget (1% of equity) → TRIM.
20. `engine.py:234`: regime scalar × earnings scalar (0.5 within 5 days) → TRIM.
21. `engine.py:244/252`: no-leverage (cash − 1.0) → REJECT if < 1 share, otherwise TRIM.
22. `governor.py:297-452`, in order: equity, size, position count (10), aggregate risk-at-stop (5%), per-share risk, headroom < 1, single name (15%), sector (30%), cluster (0.70 / 60 bars / 30%), gap (6% shock / 5% budget) → REJECT; then `:472` TRIM to the minimum.
23. `portfolio_risk.py:117-129`: ES 97.5 > 3%, single name > 15%, sector > 30% → REJECT.
24. `engine.py:340`: round trip > 10% of risk dollars → REJECT.
25. `oms.py:415`: not approved → REJECT.
26. `oms.py:431`: whole shares < 1 → REJECT.
27. `oms.py:456`: cash None → REJECT.
28. `oms.py:495-519`: 10% of spendable cash → TRIM, or REJECT if < 1.
29. `oms.py:525`: broker ceiling → TRIM (off).
30. `oms.py:537`: `pending_signoff` created; journal "proposed"; event published.

## Ordered list 2 - SELL / exit

**Strategy sell signal**

1. `signal_bridge.py:1321`: pending de-dup (any side).
2. `:1325`: fewer than 2 bars → drop.
3. `:1330`: positions read.
4. `:1398`: held > 0 and minimum hold blocks → drop (INFO log once).
   - The hold is `enforce_min_holding_period` True, `min_holding_trading_days` 10 weekdays (UTC dates, holidays ignored, 210-223).
   - It escapes when `(entry − price)/(entry − stop) ≥ min_holding_loss_escape_r` (0.5).
   - With no stop, or a stop ≥ entry, it blocks with no escape (296-313).
   - An unknown entry is never blocked (1369-1370).
5. `:1403`: held > 0 → `submit_exit_order(qty=held, price=last close, reason="signal")`.
6. `:1405`: held ≤ 0 and `allow_short_selling` False (default) → drop.
   - If shorting is enabled, a short goes through the BUY path from step 7 onward, without the weekly budget or earnings scalar, with no governor, checker, cost or cash rule, but with G1-G12, and with no stop attached.

**Time stop** (`signal_bridge.py:1284-1310`, runs on every MarketDataEvent)

- It fires when `enforce_time_stop` is True, an entry exists, the symbol is not already in `_time_stopped`, and at least 30 weekdays have passed since `opened_at` (measured against the tick `ts`).
- It re-reads positions (not wrapped). If held ≤ 0, it pops the entry without saving the file (1302).
- Otherwise it adds the symbol to `_time_stopped` **before** submitting (1304). The symbol is removed only on a flat fill (1153), so a rejected time-stop exit is not retried in that session.
- It does not check `pending_signoff_symbols`.

**`OMS.submit_exit_order`** (`oms.py:660-765`)

1. `symbol_allow_list` → REJECT.
2. Anomaly: if reason is `delever` → REJECT. Otherwise, broker quantity None → REJECT; else resize to the broker quantity.
3. `_release_protective_legs` (594-658):
   - A read failure → REJECT.
   - It **cancels the legs at the broker** (629-633), then re-reads. Legs still resting → REJECT.
   - This runs **before** the kill-switch check in `evaluate_exit` (`engine.py:392`), so with the switch tripped, the legs are cancelled and then the exit is rejected.
4. `evaluate_exit`: kill switch or qty ≤ 0 → REJECT (the journal reason is the bare "rejected", 746-747).
5. Pending sell (market order), with no strategy and no stop (763-765).

There is no per-order cash cap, no broker ceiling, no corporate-action gate, no cost rail and no duplicate-exit guard beyond bridge step 1.

## (1) Configurable parameters in scope (`config.py`, field = default)

- **Sizing:**
  - `per_trade_risk_pct`=0.01 (172)
  - `kelly_fraction`=0.5 (173)
  - `edge_min_trades`=20 (182)
  - `atr_stop_multiple`=2.5 (183)
- **Portfolio risk:**
  - `portfolio_es_limit_pct`=0.03 (184)
  - `max_single_name_concentration_pct`=0.15 (197)
  - `max_sector_concentration_pct`=0.30 (306)
  - `correlation_cluster_threshold`=0.70 (322)
  - `correlation_window_bars`=60 (340)
  - `max_correlated_cluster_pct`=0.30 (344)
  - `gap_shock_pct`=0.06 (376)
  - `max_gap_risk_at_shock_pct`=0.05 (380)
  - `max_aggregate_risk_at_stop_pct`=0.05 (444)
  - `max_concurrent_positions`=10 (449)
  - `delever_target_fraction_of_cap`=0.9 (469)
  - `delever_sweep_enabled`=False (475)
- **Cash and order size:**
  - `max_order_pct_of_cash`=0.10 (225)
  - `broker_max_order_shares`=None (299)
  - `min_cash_reserve`=1.0 (630)
- **Earnings:**
  - `enforce_earnings_event_risk`=True (359)
  - `earnings_blackout_days`=5 (363)
  - `earnings_event_size_scalar`=0.5 (364)
  - `fundamentals_source`="mock" (770), which selects the calendar
- **Costs:**
  - `ibkr_pricing_model`="fixed" (389)
  - `broker_min_commission`=6.60 (392)
  - `commission_bps`=5.0 (393)
  - `slippage_bps`=5.0 (394)
  - `apply_costs_in_paper`=True (400)
  - `max_cost_to_risk_pct`=0.10 (407)
- **Churn:**
  - `enforce_min_holding_period`=True (412)
  - `min_holding_trading_days`=10 (413)
  - `min_holding_loss_escape_r`=0.5 (425)
  - `enforce_time_stop`=True (431)
  - `time_stop_trading_days`=30 (432)
  - `max_entries_per_week`=10 (437)
- **Other:**
  - `entry_allow_list`="" (464)
  - `protection_sweep_seconds`=300 (530)
  - `corporate_action_mode`="shadow" (564)
  - `allow_short_selling`=False (623)
  - `market`="US" (901)
  - `trading_mode`="paper" (45), which feeds `is_live` for the cost rail
  - `execution_mode`="recommend" (55)
  - `bar_interval_seconds`=86400 (861)
  - `deployed_strategies`="" (85)
  - `data_dir` (636)
- **Hard-coded, not in settings:**
  - default W/R 0.55/1.5 (`signal_bridge.py:336-337`)
  - edge clamps (`edge.py:36-41`)
  - `MIN_TRADES_FOR_STATS`=5
  - ATR window 14
  - bridge `max_bars`=250
  - 20 minimum correlation observations
  - ES/VaR confidence levels (`portfolio_risk.py:25-27`)
  - regime scalars (`fusion.py:30-38`)
  - cost profiles (`costs.py:183-217`)
  - earnings TTL 1 day
  - de-lever poll 300 s

## (2) Present in code but inactive at the defaults

- De-lever trimming is off (`delever_sweep_enabled`=False): it logs only.
- Short-selling path is off (`allow_short_selling`=False).
- `broker_max_order_shares` trim is off (None).
- `entry_allow_list` and `symbol_allow_list` are None, so no restriction.
- Earnings scalar: the rail flag is on, but the calendar is Null unless `fundamentals_source="yfinance"`, so the scalar is always 1.0 at the defaults.
- Autonomous sign-off is off (`execution_mode="recommend"`).
- VaR 95/99 is computed and never gated.
- G10 is unreachable.
- `_hold_blocked` is written and never read.
- The AI guard path `check_recommendation_against_risk_limits` would call `evaluate_order` and write audit rows (`ai_advisory/guards.py:73`). Its only caller, `AIAdvisoryService.get_trade_rationale` (`service.py:58-76`), has **no caller in `src`**.
- No `qat.domain.ai_advisory` or LLM module is imported anywhere in the signal-to-pending path. `RiskEngine.regime_scalar` is written only from `RegimeEvent`, and presentation modules only read it.

## (3) Two controls checking the same quantity

- **Kill switch:** OMS G5 (`oms.py:369`) and engine C1 (`engine.py:197`), plus sign-off (`oms.py:906`).
- **Per-trade risk:** the sizer's ATR cap (`backtester/sizing.py:44`) and the engine's stop budget (`engine.py:229-232`). They differ only when a strategy stop is used.
- **Cash:**
  - engine no-leverage rule (`engine.py:242`: `cash − reserve`, which can go negative);
  - OMS per-order cap (`spendable_from`, floored at 0);
  - OMS `cash is None` checks (G9 and G10);
  - sign-off cash re-check (`oms.py:1039`).
- **Single-name concentration:** governor D7 (trim; includes pending; avg_price) and checker (reject; no pending).
- **Sector concentration:** governor D8 and checker, with the same differences.
- **Correlation:** governor cluster cap D9, and implicitly the ES combined series.
- **Duplicate buy guards:** bridge pending-signoff (A1), held (A6), live buy (A7), and the governor's `already_held` for slot counting (`governor.py:290-292`).
- **Aggregate risk-at-stop:** governor D4 and the de-lever sweep share `snapshot()`. The de-lever snapshot excludes pending orders.
- **Corporate actions:** OMS entry refusal G4, and the bridge re-arm deferral (`signal_bridge.py:1040-1045`).

## (4) NOT DETERMINED

- **Running configuration values**, meaning the contents of `app_dir()/.env` and environment variables: market, broker, `fundamentals_source`, execution mode, and whether `commission_bps` / `broker_min_commission` are explicitly set. Together these decide whether ASX uses 8.8 bps or the configured 5.0. **Needed:** the operator's `.env` and process environment.
- **Whether pydantic-settings counts env/.env values in `model_fields_set`.** This is library behaviour, not covered by any repo test. **Needed:** a test or the pydantic-settings source.
- **Whether `corporate_announcements.json` holds entries** that could make G4 fire under IBKR. **Needed:** the data file.
- **Whether the adapter in use populates `Position.current_price`** for every held symbol at the moment of evaluation. It matters because the governor falls back to `avg_price` otherwise. **Needed:** live adapter state.
- **Contents of `SECTOR_BY_SYMBOL` for the running watchlist** (D8 applies only to mapped symbols). **Needed:** the watchlist resolution plus `data/sectors.py:16-240`, which I did not read line by line.
- **Behaviour of `AutonomousExecutor` / `AutonomyGate` after pending.** Out of scope; I only saw that it can reduce quantity before `sign_off`.
