> **Audit evidence, Stage 3.** A fresh-context investigator, 12 September 2026.
> Its instructions: read only `src/qat` and `tests`; no documentation, git
> history or narrative; comments are claims; facts only, each with a
> file:line; no judgements. Reproduced as returned. **Not yet
> cross-verified**, except where noted: the exit-leg / kill-switch finding
> (sections G and H) was verified against the code and the 9 September logs
> on 14 September. It is logged as CE-017 and reported to the operator.

# Stage 3 - Investigator 3: Sign-off to reconciliation and protection

**Method.** I read only files under `src/qat/`, and I opened test files under `tests/` to check specific behaviours. I ran nothing: no tests, no git, no application. Every reference is `path:line` relative to `src/qat/`. Where a code comment makes a claim, it appears as "comment claims" with whether the code matches. A statement marked **derived** chains several code facts together; I have not executed it, and it is not covered by any test I found.

**The deployed configuration is not known.** The `.env` file sits outside the permitted folders, so this report describes the code paths and the `config.py` defaults. Whether the running install uses `broker=ibkr`, `execution_mode=auto`, `market=ASX` and so on is not established.

## 0. Wiring (what `Runtime.build_demo` constructs)

- `KillSwitch(settings.data_dir)` is shared by everything (presentation/runtime.py:578). `KillSwitchEngine` subscribes it to the bus (runtime.py:579, domain/risk_engine/kill_switch.py:199-213).
- `RiskEngine(bus, kill_switch, settings)` (runtime.py:581).
- The broker comes from `resolve_broker`. The default is `MockBroker` (runtime.py:351); `ibkr` builds an `IBAdapter` with the bus (runtime.py:301-350).
  - `live_trading_confirmed` and `read_only` are never passed, so both are False (runtime.py:350; data/broker/ib_adapter.py:232-233). With `trading_mode=live` on IBKR, the constructor raises (ib_adapter.py:244-249).
- The OMS is built with the broker, risk engine, kill switch, bus, journal, settings and `entry_allow_list` (runtime.py:590-602).
  - **`symbol_allow_list` is never passed**, so it is `None` (domain/oms/oms.py:188).
- `SignalToOrderBridge` (runtime.py:616-633). `CorporateActionMonitor` is attached to both the bridge and the OMS (runtime.py:640-652).
- `PositionCloser(oms, broker, kill_switch, _LiveEntries(bridge))` (runtime.py:660).
- `EquityMonitor` (runtime.py:678), `ReconciliationMonitor` (runtime.py:683), `DeleverSweep(oms, risk_engine.governor)` (runtime.py:684).
- `AutonomyGate(settings, kill_switch, scorecard_source)` (runtime.py:718). Its `last_print_source` is set to `market_data_feed.last_print_at` (runtime.py:811).
- `AutonomousExecutor(bus, oms, gate, journal, equity_monitor, settings, fallback_price=_last_known_price)` (runtime.py:743-751). The fallback price is the last close from the bridge's bar aggregator (runtime.py:720-741).
- **Start order** (runtime.py:930-967): BrokerConnection → warm_start → kill_switch_engine → risk_engine → equity_monitor → reconciliation_monitor → delever_sweep → trade_ledger → performance_reporter → market_data_feed → feature_engine → macro_feed → strategy_engine → autonomous_executor → corporate_action_monitor → signal_bridge → regime_engine → book_risk_monitor → session_controller.
  - `Orchestrator.start_all` awaits each `start()` in turn (domain/orchestrator.py:36-42).
- `EventBus.publish` awaits every handler through `asyncio.gather` (domain/bus.py:34-44). A subscriber therefore runs to completion inside the publisher's `await`. This matters in auto mode: the executor signs orders off *inside* `submit_order`, `submit_exit_order` and `submit_protective_stop`.

## A. Sign-off

### Who can call `OMS.sign_off`

Searching `src/qat` for `.sign_off(` finds exactly three callers:

1. **Human, Order Blotter.** `_on_sign_off_clicked` shows a confirm dialog, then `_do_sign_off` loops `oms.sign_off(order_id, "operator (blotter)")` one order at a time and collects exceptions (presentation/blotter.py:442-470, 52). Only `pending_signoff` rows are selectable for it (blotter.py:386-387).
2. **Autonomous executor**, operator `"autonomous-executor"` (domain/autonomy/executor.py:203, 45).
3. **PositionCloser** (the manual close from the Dashboard), through `_sign_off_or_reread`:
   - the exit, as `"operator (dashboard)"` (position_closer.py:720; presentation/dashboard.py:75, 754);
   - the recovery re-protect, as `"auto-reprotect"` (position_closer.py:943).

### `OMS.sign_off` → `_sign_off_locked`, in order (domain/oms/oms.py:869-1162)

0. **Lock.** Every call takes `self._signoff_lock` (an `asyncio.Lock`, oms.py:250, 877-878). The lock is held across `broker.place_order`, so sign-offs are fully serialised. With IB, one sign-off can include waits of up to `ibkr_permid_wait_seconds` (5 s) and, for buys, up to 2 s for a quote (ib_adapter.py:1484-1510, 604-611).
1. **Status check.** Status other than `pending_signoff` raises `ValueError` (oms.py:882-883).
2. **Duplicate-transmission guard.** An id already in `self._transmitted` raises `ValueError` (oms.py:900-904). The set is filled only after `place_order` returns (oms.py:1089) and lives in memory only (oms.py:280).
3. **Kill switch.** If tripped: status set to `rejected`, journalled `"kill-switch tripped: <reason>"`, order returned (oms.py:906-920). This applies to every order type: buys, exits and protective stops.
4. **Protective stops only** (`order_type=="stop"` and side sell, data/broker/adapter.py:72-74). The broker position is re-read with `_broker_quantity` (oms.py:1688-1703), which returns `abs(quantity)` or `None`:
   - `None` → rejected, "broker unreadable" (oms.py:953-971);
   - held ≤ 1e-6 → rejected, "flat" (oms.py:972-989);
   - held + 1e-6 < order quantity → rejected, "shrank" (oms.py:990-1010);
   - a protective order *smaller* than the holding is allowed (comment oms.py:947-950; code 990).
   - Market sells get **no** re-read at sign-off.
5. **Buys only: cash re-check** (oms.py:1018-1056).
   - Calls `broker.account()`, then `_costing_price`. The price order is `limit_price`, then `filled_price`, then the broker quote (`ask` or `last`), then `reference_price`, then `None` (oms.py:1210-1236).
   - No price → rejected (oms.py:1021-1037).
   - `cost = quantity × price`, `spendable = account.cash − min_cash_reserve`. If cost > spendable → rejected (oms.py:1038-1056).
   - Rejects rather than resizes.
6. **Transmit.** `filled = await broker.place_order(order)`. On an exception: status `rejected`, journalled `"broker refused: …"`, returned; not added to `_transmitted` (oms.py:1066-1079).
7. **After a return that did not raise:**
   - `_transmitted.add(order_id)` (1089);
   - `_orders[order_id] = filled`, also aliased under the broker id if it differs (1090-1103);
   - broker id added to `_broker_order_ids` (1106-1107).
8. **Protective stop:** records `_position_stops[symbol] = stop_price`, journals `signed_off`, returns. It does **not** book quantity (oms.py:1114-1132).
9. **Everything else:**
   - books `_filled_quantities[symbol] += ±order.quantity` (oms.py:1134-1137). This is the *ordered* size, and it is booked **whatever status the broker returned** (transmitted, filled, rejected or cancelled); there is no status check between 1067 and 1137;
   - records the stop for buys, or pops it when a sell flattens the position (1139-1144);
   - journals, then `_announce_fill` (1145-1161).

### Autonomous path

**`AutonomousExecutor`** (domain/autonomy/executor.py)

- **Trigger 1: event.** Subscribes to `OrderPendingSignoffEvent` (executor.py:89-91). `_on_pending` returns at once unless `settings.autonomy_enabled` (160-161). `autonomy_enabled` = `execution_mode=="auto"` and (not live, or `allow_autonomous_live_trading`) (config.py:953-963).
- **Trigger 2: retry loop.** `_retry_loop` sleeps `retry_interval_seconds`, a constructor default of 60.0 that is not a Settings field and is not passed by the runtime, then runs `retry_pending` (executor.py:61, 101-119).
  - `retry_pending` iterates `oms.pending_orders()` (executor.py:146), which **includes `transmitted`** orders (oms.py:784, 830-832).
  - `pending_orders()` does not deduplicate the aliased entries (compare `orders()`, oms.py:1286-1294). A transmitted order held under two keys is therefore evaluated twice per sweep.
  - For transmitted orders the gate blocks at the status rail (gate.py:125-126). The journal suppresses consecutive identical verdicts per symbol (domain/decision_journal.py:92-112).
  - Each `_consider` call is wrapped in its own try (executor.py:147-155).
- **`_consider`** (executor.py:172-222):
  - fetches `broker.account()` per order;
  - reads `day_pnl_pct` from the equity monitor (executor.py:176-184);
  - gets a price from `_current_price`: broker quote `last`, then `ask`, then `bid` (finite and > 0), else `fallback_price` (bar close), else `None` with a WARNING that the drift check is skipped (executor.py:224-283);
  - calls `gate.evaluate`. If blocked, it journals and returns (189-198);
  - if the gate halved the size, it mutates `order.quantity` (200-201);
  - calls `oms.sign_off`. A `rejected` result is journalled as `blocked_by_oms` (205-213).
- **Failure.** An exception in `_on_pending` leaves the order pending and journals "evaluation raised" (executor.py:163-170, 313-326).
- **No expiry.** No code expires a pending order. Pending orders live only in `OMS._orders` in memory (oms.py:194) and do not survive a restart.

**`AutonomyGate.evaluate` rails, in order** (domain/autonomy/gate.py:96-297). Every block returns quantity 0 and a reason (109-116).

| # | Condition | Result | Line |
|---|---|---|---|
| 1 | `execution_mode != "auto"` | block | 119-120 |
| 2 | `is_live` and not `allow_autonomous_live_trading` | block | 121-122 |
| 3 | kill switch tripped | block | 123-124 |
| 4 | status ≠ `pending_signoff` | block | 125-126 |
| 5 | quantity ≤ 0 | block | 127-128 |
| 6 | `order.is_protective_stop` | **allow**, whatever the session | 146-154 |
| 7 | `session.is_open` False (closed, pre-open, closing auction) | block | 156-157 |
| 8 | `trading_state == "opening_auction"` (ASX first 10 min, domain/market_calendar.py:125, 387-393) | block | 180-184 |
| 9 | side == sell | **allow** | 187-195 |
| 10 | Buys, when `last_print_source` is set: no print this session → block; last print from an earlier trading date → block | block | 211-225 |
| 11 | phase not in {Morning Trend, Afternoon, Closing Session} (market_calendar.py:96-98, 154-155) | block | 227-228 |
| 12 | no strategy | block | 231-232 |
| 13 | strategy not in `autonomous_strategies` | block | 233-237 |
| 14 | `promotion_evidence_enforced` and a scorecard exists and it is not eligible (a `None` card passes) | block | 251-258 |
| 15 | `day_pnl_pct ≤ autonomous_pause_buys_below_day_pnl_pct` (−0.04) | block | 260-264 |
| 16 | `current_price` and `reference_price` present and \|Δ\|/ref > `autonomous_price_drift_limit_pct` (0.03) | block | 266-273 |
| 17 | `day_pnl_pct ≤ autonomous_halve_size_below_day_pnl_pct` (−0.02) → quantity = max(1, qty//2) | resize | 277-281 |
| 18 | otherwise | allow | 283-297 |

- `AccountState.cash` is never read by `evaluate`. **Comment claims** "the cash floor … deliberately [does] not apply to sells" (gate.py:9-11); the gate has no cash-floor rail at all. Cash is checked in the OMS.
- The gate is built without a `clock` (runtime.py:718), so the session comes from the wall clock (gate.py:104-106; market_calendar.py:321).

### Human path

- The Blotter confirmation lists the orders and calls `oms.sign_off` sequentially (blotter.py:442-470).
- Bulk sign-off is serialised by the OMS lock. The cash re-check runs per order against a fresh `account()` (oms.py:1019).

### Stage A attributes

- **Inputs:** a pending `Order`; broker account, quote and positions; the kill switch; settings; the equity monitor's day-start state.
- **Outputs:** the order passed to `broker.place_order`; status changes; `_filled_quantities`, `_position_stops`, `_transmitted` and `_broker_order_ids` updated; decision-journal rows; `OrderFilledEvent`.
- **Decision authority:** the OMS (status, duplicate, kill switch, protective re-read, cash); the gate (unattended only); the human in the Blotter.
- **State in memory:** `OMS._orders`, `_transmitted`, `_broker_order_ids`, `_filled_quantities`, `_position_stops`, `_signoff_lock`; the executor's `_retry_task`.
- **Persistence:** `decision_journal.csv` is appended (decision_journal.py:34, 111-125). Nothing else here persists.
- **Failure:** broker exception → `rejected`. Gate exception → left pending. Journal write failure is swallowed (oms.py:2841-2842; decision_journal.py:124-125).
- **Refusal:** status `rejected` plus a journal reason, or a `ValueError` for status/duplicate.
- **Deterministic / AI:** deterministic. None of these files imports `ai_advisory`, and the only LLM mentions are comments (gate.py:12, autonomy/__init__.py:6).
- **Broker influence:** yes; this is the only caller of `place_order` found (oms.py:1067).

## B. Transmission (`IBAdapter.place_order`, data/broker/ib_adapter.py:883-912)

1. `_check_not_read_only()`. `read_only` is False in the runtime (ib_adapter.py:478-482; runtime.py:350).
2. `_round_prices_onto_ticks` rounds `limit_price`, `stop_price` and `take_profit_price` onto the exchange tick **in place** on the OMS's own `Order` object (ib_adapter.py:852-881).
3. The contract is `Stock(base, "SMART", currency[, primaryExchange])` (data/broker/ib_translate.py:90-109).
4. **Routing:**
   - **`order.is_bracket`** (market-type order with a stop or target, adapter.py:63-70) → `_place_bracket` (ib_adapter.py:642-667):
     - **Parent:** `MarketOrder` (or `LimitOrder` if `limit_price` is set), `tif="GTC"`, `transmit=False` (ib_translate.py:194-209). Entries never set `limit_price` (oms.py:842-864), so the parent is market.
     - **Legs** (ib_translate.py:212-280): the target as `LimitOrder` at `take_profit_price` and the stop as `StopOrder` at `stop_price`. Both are on the reverse side, carry `parentId`, `tif="GTC"`, `transmit=False`, `ocaGroup="qat-<app order id>"` and `ocaType=1`. The **last** leg gets `transmit=True`. Only the legs whose price is set are created.
   - **`order_type=="stop"` with a target** → `_place_oca`: a pair of `LimitOrder(target)` and `StopOrder(stop)`, both GTC, `ocaType=1`, group `qat-<id>`, no parent, both transmitted (ib_translate.py:283-311; ib_adapter.py:669-689).
   - **Otherwise** → `to_ib_order`:
     - a stop without a target is `StopOrder(..., tif="GTC")` (ib_translate.py:128-152);
     - a stop with no `stop_price` raises `UnrepresentableOrderError` (129-130);
     - a limit is `LimitOrder(..., "GTC")`;
     - everything else is `MarketOrder(..., tif="GTC")` (189-191).
     - The `UnrepresentableOrderError` branches for bracket and stop-with-target (131-145, 154-167) cannot be reached through `place_order`, which routes those cases earlier (ib_adapter.py:887-890).
5. **Identity.**
   - `_await_perm_id` polls every 0.05 s for up to `ibkr_permid_wait_seconds` (ib_adapter.py:1484-1517).
   - `from_ib_trade` sets the status from `_IB_STATUS_MAP` (default `"transmitted"`), `filled_price = avgFillPrice` if non-zero, and `filled_quantity = orderStatus.filled`. When a permId exists it **overwrites `order.order_id` with the permId** (ib_translate.py:314-377).
   - The adapter registers the order under both ids (ib_adapter.py:909-911, 664-666, 687-688).
6. **Status map** (ib_translate.py:63-76): Filled → filled; Cancelled / ApiCancelled → cancelled; Inactive → rejected; PendingSubmit / PreSubmitted / Submitted / ApiPending / PendingCancel → transmitted; anything unmapped → transmitted (367).
7. **Errors after transmission** arrive asynchronously on `errorEvent` → `_on_ib_error` (ib_adapter.py:1342-1476):
   - `_order_for_req_id` matches the orderId against `_ib_orders` and against **every leg in `_ib_groups`**. A matched order whose status is `"filled"` is treated as not order-scoped (1195-1256).
   - `classify` (data/broker/ib_errors.py:129-150):
     - not order-scoped → IGNORE;
     - codes {105, 110, 321, 329, 399, 404, 434} → WARN (log only);
     - codes {383, 202, 10148} → REJECT;
     - any other order-scoped code → **HALT**.
   - REJECT and HALT set the matched order's status to `"rejected"` (1418-1420). For non-protective orders they publish `OrderRejectedEvent(booked_quantity=order.quantity, executed_quantity=order.filled_quantity)` (1445-1457).
   - 383 also runs `_audit_size_limit` (1458-1459). HALT also publishes `KillSwitchEvent` (1460-1474).
   - A 202 on a bracket **child** leg marks the *entry* order rejected. `tests/data/broker/test_ib_adapter_hears_rejections.py:114-127` asserts `adapter._orders[app_id].status == "rejected"`.
   - `Order.filled_quantity` is written only at placement (ib_translate.py:373). The `executed_quantity` a later rejection carries is therefore that placement-time snapshot. **Comment claims** it is "at the moment of rejection" (domain/events.py:274); the code carries the placement value.
8. **OMS reaction to `OrderRejectedEvent`:** it reverses `booked − executed`, signed by side. It does nothing if `executed_quantity is None` or the symbol was never booked (oms.py:1310-1365).
9. **Cancels** (`cancel_order`, ib_adapter.py:1069-1118):
   - resolve the id: `_orders`, then `_adopt_from_broker` (which scans `reqAllOpenOrders` and publishes `BrokerOrderIdResolvedEvent`, 914-980), then `openTrades` matched by permId (1177-1193); raise `CancelNotResolvedError` if nothing resolves;
   - cancel every order in the group, re-check up to 3 × 0.7 s and cancel survivors again (1120-1175);
   - set status `"cancelled"` optimistically (1117).
10. **Connection:** heartbeat every 10 s (437-450). Reconnect makes 5 attempts at 1, 2, 4, 8 and 16 s, then publishes `KillSwitchEvent` (452-476). Every IB request is under `ibkr_call_timeout_seconds` (1519-1545), and `reqAllOpenOrders` is serialised by a lock (1547-1593).

### Stage B attributes

- **Inputs:** an app `Order`.
- **Outputs:** IB orders, and the mutated `Order` (status, permId, prices rounded to tick, filled price and quantity).
- **State in memory:** adapter `_orders`, `_ib_orders`, `_ib_groups`, `_qualified_contracts`, commission tallies. None of it persists.
- **Persistence:** none.
- **Deterministic:** yes.
- **Broker influence:** direct.

## C. Where an order becomes a recorded position

| Record | Written when | Source of quantity | Source of price | Ref |
|---|---|---|---|---|
| `OMS._filled_quantities` (in memory) | at **sign-off**, once `place_order` returns, for any returned status (protective stops excluded) | ordered `order.quantity` | n/a | oms.py:1134-1137 |
| same | partial reversal on `OrderRejectedEvent` | booked − executed | n/a | oms.py:1349-1356 |
| same | foreign fill absorbed (not record-only) | fill delta | n/a | oms.py:2167-2171 |
| same | replaced wholesale from `broker.positions()` at adoption (startup), and after a record-only replay | broker | n/a | oms.py:1400-1403, 2415-2431 |
| `OMS._position_stops` (in memory) | buy sign-off with a stop; protective sign-off; adoption from `resting_stops`; `verify_position_stops` | – | stop, after tick rounding | oms.py:1114-1116, 1139-1140, 1408-1411, 1620 |
| `SignalToOrderBridge._entries` (→ `open_position_entries.json`) | `OrderFilledEvent` for a buy, via `setdefault`; removed when the broker reports flat after a sell | – | `event.price`; `price_source` is `"fill"` if `price_is_fill` | domain/oms/signal_bridge.py:1135-1170, 1258-1278 |
| `TradeLedger` open lot | `OrderFilledEvent` for a buy; sells close lots | event quantity | event price | domain/performance/trades.py:1086-1110, 1139-1235 |

**When `OrderFilledEvent` fires**

- For app-sent orders, `_announce_fill` publishes at status `"filled"` **or** `"transmitted"`, with `price = order.filled_price or order.reference_price` and `price_is_fill = bool(filled_price)` (oms.py:1164-1208). For IB this is usually at transmit time, carrying the reference price.
- For absorbed foreign fills, `price_is_fill=True`, `strategy=None` and `ts=fill.filled_at` (oms.py:2212-2232).

**Where each price comes from**

- **Entry reference price:** `candidate.price` = the last close in the bridge's bar aggregator, which is fed by the app's market-data feed (signal_bridge.py:1328, 1497-1500; domain/oms/oms.py:541). **Comment claims** the yfinance feed runs about 20 minutes behind (config.py:868-879).
- **Exit reference prices:** signal exit and time stop use the tick or bar price (signal_bridge.py:1310, 1403); de-lever uses `pos.avg_price`, the broker's average cost (domain/risk_engine/delever.py:185); manual close uses the **entry price** from the entry record (domain/oms/position_closer.py:699-703).
- **Mid-session correction:** during `absorb_broker_fills`, an own order's IB execution `avgPrice` (cumulative) is compared with the announced price. A difference above 1e-4 relative, on a symbol that is not quarantined, publishes `EntryPriceCorrectedEvent` or `ExitPriceCorrectedEvent` (oms.py:2316-2413; ib_translate.py:435-442).
- **Startup correction:** `reconcile_entry_prices` reads the broker `Position.avg_price` (IB `avgCost`). Because the adapter declares `avg_price_includes_commission` (ib_adapter.py:225), it converts through `CostModel.fill_price_from_average_cost`, skips floor cases, and skips records with `price_source=="fill"` or quarantined symbols (signal_bridge.py:532-631).
- **Tick rounding** can move the stop and target from the levels the sizer computed (ib_adapter.py:852-881).

**Stage C attributes**

- **Persistence:** `open_position_entries.json` (signal_bridge.py:68, 402); `closed_trades.csv` (trades.py:62); `absorbed_fills.json` (oms.py:120).
- **Deterministic:** yes.
- **Broker influence:** indirect. `_position_stops` feeds the governor's risk-at-stop figure and `verify`; `_filled_quantities` feeds reconciliation, and through it the kill switch; the entry stop and target set the re-arm levels.

## D. Fills and broker-side events

- **Source:** `IBAdapter.recent_fills` → `reqExecutionsAsync(ExecutionFilter())` (default filter), then local filtering by `filled_at > since` and tracked symbols; an empty symbol list returns `[]` (ib_adapter.py:691-747). `from_ib_fill` uses permId, cumulative `cumQty`, cumulative `avgPrice` and `execution.time`, and drops sides other than BOT/SLD (ib_translate.py:387-442).
- **Entry points:**
  - `absorb_broker_fills()` runs at the start of every `check_reconciliation` (oms.py:2516);
  - `absorb_broker_fills(record_only=True)` runs once at bridge startup, from `replay_missed_exits` (signal_bridge.py:459-530).
  - Nothing absorbs fills in real time.
- **Query window:** from `min(watermark − 1 s, min(stamps of remembered absorbed fills and own partials) − 1 s)` (oms.py:1947-1992). The symbols are tracked quantities, plus every symbol with an order, plus the `watch_symbols_for_fills` hint (oms.py:2040-2063).
- **Collapse:** only the highest cumulative snapshot per order id is kept (oms.py:2116-2121).
- **Identity test `_is_foreign_unrecorded`** (oms.py:1911-1945):
  - an id in `_broker_order_ids` or `_orders` is **own** (not foreign);
  - an id already absorbed is foreign only if the cumulative quantity grew; a pre-M53 record counts as finished;
  - otherwise it is foreign if `filled_at ≥ watermark`.
  - Both identity sets are in memory only. Late permIds arrive through `BrokerOrderIdResolvedEvent` (oms.py:1307-1308).
- **Own orders:** `_close_out_own_order` sets status `filled` once cumulative ≥ order quantity, and only from `transmitted` (oms.py:2274-2314). `_correct_announced_price` is as in C.
- **Foreign fills:**
  - `_unabsorbed_part` takes the delta quantity and derives the increment price from the running averages (oms.py:1994-2023);
  - quantity is updated unless `record_only`, and the stop is popped if flat (2167-2174);
  - `_absorbed_fills` is updated (2175-2180) and a WARNING logged (2182-2211);
  - `OrderFilledEvent` is published with `exit_reason` = `"stop"` if price ≤ stop × 1.02, else `"target"` (2433-2449).
  - Manual TWS trades and resting stop or target fills all take this path. A foreign buy opens a lot with no stop and no strategy (trades.py:1089-1109).
- **Record-only replay:** quantities are re-read from the broker afterwards (oms.py:2234-2246).
- **Watermark:** set to the pass's *start* time and saved after every pass, with 30-day id retention (oms.py:2096, 2255-2256, 1852-1890). It is loaded at construction; a watermark older than 2 h logs a warning (1794-1850).
- **Ledger guard:** an exit earlier than a strategy lot's `opened_at` is refused (trades.py:1188-1200).
- **Commission:** IB `commissionReportEvent` is tallied per permId and handed to `CommissionAuditor` (ib_adapter.py:1262-1340; runtime.py:612-615).

**Stage D attributes**

- **Persistence:** `absorbed_fills.json` `{watermark, absorbed{order_id:{filled_at, quantity, price, quantity_known}}}` (oms.py:1869-1888).
- **Failure:** a query failure returns `[]` with an exception log (oms.py:2097-2101).
- **Deterministic:** yes.
- **Broker influence:** indirect, through reconciliation and the kill switch.

## E. Reconciliation (`ReconciliationMonitor`, domain/oms/reconciliation.py; `OMS.check_reconciliation`, oms.py:2494-2577)

- **Startup:** `adopt_broker_positions` (oms.py:1367-1450) sets tracked quantities and the baseline from the broker and learns stops from `resting_stops`. Then `check_resting_orders` runs if `resting_order_reconcile_enabled` (reconciliation.py:55-80).
- **Cadence:** every `reconciliation_poll_seconds` (300), under a `reconciliation_poll_timeout_seconds` (120) deadline (reconciliation.py:90-148).
  - A timeout logs ERROR, then CRITICAL after 3 in a row, and **does not trip** (reconciliation.py:114-141).
  - The Risk Console "force check" button also calls `poll()` (presentation/risk_console.py:646-647).
- **`check_reconciliation`:**
  1. `absorb_broker_fills()`;
  2. `verify_position_stops()`;
  3. broker positions;
  4. in-flight tolerance = the summed `remaining` of working **BUY** orders at the broker, from any origin (oms.py:2451-2492);
  5. over the union of symbols, a symbol diverges if \|tracked − broker − in_flight_buy\| > 1e-6 (2529-2543);
  6. a divergence is excluded if `PositionAnomalyStore.explains(symbol, broker_qty)`, which is bound to the declared broker quantity (domain/oms/anomaly.py:130-148);
  7. anything unexplained → ERROR log and `kill_switch.check_reconciliation()`, i.e. `trip("Broker reconciliation mismatch")` (oms.py:2568-2576; kill_switch.py:172-173).
- **Publish:** the monitor publishes `KillSwitchEvent` only when the switch was not already tripped before the poll (reconciliation.py:153-165).
- **Orders are not part of this comparison.** The resting-order scan runs afterwards in its own try, and it never trips (reconciliation.py:177-184; oms.py:2591-2595).
- **Working sells have no tolerance.** Only working buys are subtracted (oms.py:2489).

**Stage E attributes**

- **Persistence:** `position_anomalies.json` is read (anomaly.py:26, 150-188); its writers are the Risk Console declare (risk_console.py:452-458) and the corporate-action monitor (monitor.py:269, 432).
- **Deterministic:** yes.
- **Broker influence:** it trips the kill switch; it places nothing.

## F. Protection

1. **At entry:** the bracket legs STP and LMT, GTC, `ocaType=1` (section B).
   - The stop is the strategy's stop if the signal carried one in `meta`, else `price − atr_stop_multiple × ATR` (signal_bridge.py:1450-1451; domain/risk_engine/engine.py:213-228; oms.py:546).
   - If neither exists (`effective_stop` is `None`, engine.py:226-228) and there is no target, the entry goes out as a plain `MarketOrder` GTC with no legs (adapter.py:63-70; ib_translate.py:191).
2. **Adoption at startup:** `_position_stops` is seeded from `resting_stops()` = IB STP / STP LMT orders in working status with an `auxPrice`, keeping the tighter of any duplicates (oms.py:1408-1411; ib_adapter.py:777-837; ib_translate.py:450-498).
3. **Re-arm** `rearm_protective_stops` (signal_bridge.py:991-1088) runs at bridge start after the replay (426) and every `protection_sweep_seconds` (300) (1106-1125).
   - It first reports earnings exposure.
   - `naked_positions` = broker positions with \|qty\| > 0 and no resting STP (oms.py:1674-1686).
   - It skips quarantined symbols, symbols with a pending corporate action, and positions with no entry record or no entry stop (each group logged).
   - It then calls `submit_protective_stop(symbol, abs(qty), entry.stop_price, entry.target_price)`, which refuses qty ≤ 0 or stop ≤ 0 and returns an existing pending protective order instead of adding a second (oms.py:1705-1783).
   - The result is `pending_signoff`. The gate allows it even when the market is closed (gate.py:146-154). The OMS re-reads the holding at sign-off (A.4).
   - There is no check for a pending exit on the same symbol in `rearm_protective_stops` or `submit_protective_stop`.
4. **Verification** `verify_position_stops` runs on every reconciliation poll (oms.py:1527-1652):
   - for held symbols in `_position_stops`: missing at the broker → "lost"; level differs by > 1e-4 relative → the belief is replaced with the broker's level;
   - a lost symbol with a pending protective order gets **one** check of grace, after which the belief is dropped (1602-1614).
   - It places nothing.
5. **Resting-order scan** `check_resting_orders` (oms.py:2579-2758):
   - reads `open_orders()` (all IB open orders; `[]` when the client cannot answer, ib_adapter.py:749-775) and positions;
   - per (symbol, side), resting quantity is netted as the max within an OCA group or parent, summed across groups; a long justifies SELLs up to its size, a short justifies BUYs, a flat symbol justifies nothing (domain/oms/resting_orders.py:158-248);
   - a working buy on a flat symbol explains up to its quantity (resting_orders.py:251-318);
   - each unexplained divergence gets an ERROR log (throttled) and `RestingOrderAnomalyStore.declare`, which blocks new entries (oms.py:347-351). The quarantine lifts after 3 consecutive clean scans or an operator clear (domain/oms/resting_order_anomaly.py:46, 117-162; risk_console.py:477);
   - **Cancel:** only for **flat** symbols, only if `resting_order_cancel_enabled` (default False), and only after a fresh positions read plus tracked quantity 0. It then calls `broker.cancel_order` per leg directly, with no sign-off and no kill-switch check (oms.py:2687-2757).
6. **Exit leg release** `_release_protective_legs` (oms.py:553-658):
   - cancels every open SELL order on the symbol of type STP, STP LMT, LMT, TRAIL or TRAIL LIMIT (adapter.py:447-463), with no status filter;
   - re-reads; if any are still visible, or a read fails, returns False and the exit is refused.
7. **Corporate-action stop modification:** calls `broker.modify_order` directly when `corporate_action_mode=="act"` (domain/corporate_actions/monitor.py:306-317, 446-449). The default is `shadow`. `IBAdapter` has no `announcements`, so detection is marked unsupported (monitor.py:369-381; runtime.py:314-330).
8. **Kill switch and protection:** a trip does nothing at the broker; resting GTC legs stay (kill_switch.py:132-152). Re-arm proposals are still created but cannot transmit (gate rail 3, sign-off step 3). Exit paths still release legs while tripped (G and H).

**Stage F attributes**

- **Persistence:** `resting_order_anomalies.json`, `open_position_entries.json`.
- **Deterministic:** yes.
- **Broker influence:** yes. It proposes and places stops and OCA pairs through sign-off, and cancels legs directly.

## G. Kill switch (domain/risk_engine/kill_switch.py)

**Trip paths** (`trip()` does nothing if already tripped, so the first reason is kept, 146-147):

| Path | Mechanism | Ref |
|---|---|---|
| Daily loss | `EquityMonitor.poll` every `equity_poll_seconds`: (day_start − equity)/day_start ≥ `daily_loss_limit_pct` (0.03). The day comes from the exchange trading date. | domain/autonomy/equity_monitor.py:106-153, 164-188; kill_switch.py:154-161 |
| Drawdown | (HWM − equity)/HWM ≥ `max_drawdown_limit_pct` (0.20) | equity_monitor.py:138-140; kill_switch.py:163-170 |
| Reconciliation | unexplained quantity divergence | oms.py:2576 |
| Manual | Risk Console button, after a confirm dialog | risk_console.py:679-685 |
| IB reconnect exhausted | `KillSwitchEvent` → `KillSwitchEngine` | ib_adapter.py:470-476; kill_switch.py:212-213 |
| IB unrecognised order-scoped error (HALT) | `KillSwitchEvent` | ib_adapter.py:1460-1474 |
| Staleness | **none**: `DataStaleEvent` is not subscribed | kill_switch.py:199-207 |
| Reconciliation poll timeout | **none** | reconciliation.py:114-141 |

- **Comment claims** in the module docstring that the switch trips on "data-staleness" and "overrides every strategy and the AI layer" (kill_switch.py:1-4). The code has no staleness trip, and `StrategyEngine` does not read the switch. main_window.py:80 mentions "a staleness trip", which has no counterpart in the code.
- **Persistence:** `kill_switch.json` `{tripped, reason}`, written on every trip and reset and loaded at construction. An unreadable file starts the switch clear and logs ERROR (kill_switch.py:25, 48-103).
- **Reset:** the Risk Console button when tripped calls `reset(operator)` with **no confirmation** (risk_console.py:675-677). `reset` has no other caller in `src`.
- **What a trip blocks:**
  - `OMS.submit_order` (oms.py:369);
  - `RiskEngine.evaluate_order` (engine.py:197-200) and `evaluate_exit` (engine.py:392-393);
  - `AutonomyGate` for all orders, including protective (gate.py:123-124);
  - `OMS._sign_off_locked` for all orders (oms.py:906-920);
  - `PositionCloser.close_position`, before touching the broker (position_closer.py:599-608).
- **What a trip does not block:**
  - creating protective proposals (`submit_protective_stop` has no check);
  - `_release_protective_legs` inside `submit_exit_order`, which **runs before** `evaluate_exit` (oms.py:731-747);
  - the resting-order cancel loop (oms.py:2694-2757);
  - corporate-action `modify_order`;
  - absorption, reconciliation and verification;
  - the strategy engine;
  - the de-lever sweep (delever.py:125-191);
  - existing resting orders.
- **Risk Console trip dialog claims** "Halt ALL new order flow, including exits and protective-stop re-arming … Resting orders … NOT cancelled" (risk_console.py:658-660). No transmission happens, which matches. The dialog does not say that exit paths cancel legs.

## H. Exits

- **Signal exit:**
  - a `SignalEvent` sell → skipped if the symbol has a pending order (signal_bridge.py:1321-1322) → held from `broker.positions()` (1330-1334);
  - minimum hold: `enforce_min_holding_period`, 10 weekdays, lifted if the loss ≥ 0.5R; signal exits only (1352-1398, 277-313, 210-223);
  - `submit_exit_order(symbol, held, price, "signal")` (1403);
  - with no holding and `allow_short_selling` False, the signal is dropped (1405-1406).
- **Time stop:**
  - runs on every `MarketDataEvent` tick (1280-1282) when `enforce_time_stop` is on, the entry record is ≥ 30 weekdays old, and the broker holds > 0;
  - the symbol is added to `_time_stopped` **before** submitting, and removed only when a flat fill is seen (1304, 1153). A refused time-stop exit is therefore not retried by the time stop in that session;
  - submits `submit_exit_order(..., "time_stop")` (1284-1310);
  - if the broker is flat it pops the entry without saving the file (1301-1303).
- **`OMS.submit_exit_order`** (oms.py:660-765):
  1. `symbol_allow_list` (None at runtime);
  2. position anomaly: a `delever` exit is refused; any other exit is resized to the broker quantity, or refused if the broker is unreadable (680-710);
  3. `_release_protective_legs` unless `legs_already_released` (731-742);
  4. `evaluate_exit`: kill switch and qty > 0 only (engine.py:371-406);
  5. no per-order cap, no `broker_max_order_shares` ceiling, no pending-corporate-action gate, no resting-anomaly gate (749-765).
  - The result is a pending MKT order, GTC at IB.
- **Manual close** (`PositionCloser.close_position`, position_closer.py:570-755):
  - full close only; refuses if the kill switch is tripped, the position is short, it is not held, or there is no entry record;
  - `_cancel_legs` refuses non-protective working orders, and refuses zero legs on a held symbol; it cancels, then re-reads with a verification predicate where only absent or terminal statuses count as gone, plus a book-credibility check (251-385);
  - re-reads the holding, then calls `submit_exit_order(..., entry.price, "manual_close", legs_already_released=True)`;
  - signs off as the operator, or re-reads if the executor already signed it (498-568);
  - `transmitted` or `filled` counts as success. Otherwise `_recover` re-places the protective order via `submit_protective_stop` and sign-off `"auto-reprotect"`, with guards against live sells, empty reads, short and flat positions (757-983).
  - The Dashboard has a re-entrancy flag (dashboard.py:699-726).
- **De-lever:**
  - `DeleverSweep.poll` every 300 s (a constructor default, not a setting, delever.py:55, 77-80);
  - fraction = 1 − (cap × 0.9 × equity)/risk-at-stop, when over `max_aggregate_risk_at_stop_pct` (domain/risk_engine/governor.py:505-534);
  - logs the breach; if `delever_sweep_enabled` (default False) it trims `floor(held × fraction)` on every position via `submit_exit_order(..., price=pos.avg_price, "delever")` (delever.py:125-191).
- **Rails that exempt sells:**
  - the governor, the portfolio VaR/ES/concentration check, the cost rail, the earnings scalar and the cash rule are buys only (engine.py:155, 241, 266, 297-310, 332);
  - gate rails 10-17 are skipped for sells (gate.py:187-195);
  - the entry allow list, corporate-action pending and resting-order anomaly checks sit only in `submit_order`;
  - the sign-off cash re-check is buys only (oms.py:1018);
  - the per-order cap and the broker share ceiling are in `submit_order` only.
- **Rails sells still pass:** the kill switch at three points; gate rails 1-8 (mode, live, kill, status, qty, market open, opening auction); the position anomaly; leg release.

## Execution paths

| Path | Controls passed (in order) | Order type / TIF (IBKR) | Can it transmit while the kill switch is tripped? |
|---|---|---|---|
| **Entry buy** | Bridge: no pending order, ≥ 2 bars, not held, no live buy, turnover ≤ `max_entries_per_week`, ATR > 0, account readable → `submit_order`: allow lists, position anomaly, resting anomaly, pending corporate action, **kill switch**, RiskEngine (kill switch, sizer, stop budget, regime × earnings scalar, no-leverage, governor count/aggregate/name/sector/cluster/gap, portfolio VaR/ES, cost rail), whole shares, cash known, per-order cap trim, broker share ceiling → gate rails 1-18 (auto) or Blotter confirm → sign-off: status, `_transmitted`, **kill switch**, cash re-check | Parent MKT GTC `transmit=False` | No (oms.py:369; engine.py:197; gate.py:123; oms.py:906) |
| **Protective stop at entry** | Same as the entry (it is part of the entry order) | STP GTC child, parentId, OCA `qat-<id>`, ocaType 1, `transmit=True` if last | No |
| **Target at entry** | Same as the entry; only if a strategy target exists | LMT GTC child, same OCA group | No |
| **Signal exit** | Strategy sell with held > 0 → no pending order → minimum hold (loss escape) → `submit_exit_order`: position anomaly, **leg cancel and verify**, `evaluate_exit` (**kill switch**) → gate rails 1-9, or human → sign-off: status, `_transmitted`, **kill switch** | MKT GTC | No transmission. **Legs are cancelled at the broker before the kill-switch refusal** (oms.py:731 then 745). No test combining the two was found |
| **Time-stop exit** | `enforce_time_stop`, ≥ 30 weekdays, broker held > 0, once per session → same as signal exit (no minimum hold) | MKT GTC | No transmission. Legs are cancelled before the refusal, and the time stop does not retry that session (signal_bridge.py:1304) |
| **Manual close** | Dashboard confirm → full close only, **kill switch**, not short, held, entry record → `_cancel_legs` (intruders, zero legs, cancel, verify, credibility) → re-read → `submit_exit_order` (anomaly, `evaluate_exit`) → sign-off as operator (gate bypassed) → recovery on failure | MKT GTC; recovery is STP GTC or LMT+STP OCA GTC | No. Refused before the broker is touched (position_closer.py:599) |
| **De-lever trim** | `delever_sweep_enabled` (default False), over cap, qty = floor(held × fraction) → `submit_exit_order` (anomaly refuses trims, **leg cancel** even when partial, `evaluate_exit`) → gate or human → sign-off | MKT GTC | No transmission. When enabled, legs are cancelled before the refusal |
| **Re-arm** | Startup and every 300 s: naked (no working STP), not quarantined, no pending corporate action, entry stop known → `submit_protective_stop` (qty > 0, stop > 0, no pending duplicate) → gate rails 1-6 (session ignored) or human → sign-off: status, `_transmitted`, **kill switch**, held re-read | STP GTC, or LMT+STP OCA (ocaType 1, no parent) GTC | No (gate.py:123; oms.py:906). The proposal is still created and stays pending |
| *(Orphan cancel)* | Flat symbol, `resting_order_cancel_enabled`, fresh flat check, tracked 0 | Cancel only | Not gated by the kill switch (oms.py:2694-2757) |

## (1) Configurable parameters in scope (config.py)

| Field | Default | Line |
|---|---|---|
| `trading_mode` | "paper" | 45 |
| `execution_mode` | "recommend" | 55 |
| `allow_autonomous_live_trading` | False | 62 |
| `autonomous_strategies` | "" | 67 |
| `deployed_strategies` | "" | 85 |
| `autonomous_pause_buys_below_day_pnl_pct` | −0.04 | 89 |
| `autonomous_halve_size_below_day_pnl_pct` | −0.02 | 90 |
| `autonomous_price_drift_limit_pct` | 0.03 | 94 |
| `equity_poll_seconds` | 60.0 | 98 |
| `broker` | "mock" | 164 |
| `ibkr_host` / `ibkr_port` / `ibkr_client_id` | 127.0.0.1 / 4002 / 1 | 167-169 |
| `per_trade_risk_pct` | 0.01 | 172 |
| `atr_stop_multiple` | 2.5 | 183 |
| `daily_loss_limit_pct` | 0.03 | 185 |
| `max_drawdown_limit_pct` | 0.20 | 186 |
| `max_order_pct_of_cash` | 0.10 | 225 |
| `broker_max_order_shares` | None | 299 |
| `max_cost_to_risk_pct` | 0.10 | 407 |
| `enforce_min_holding_period` | True | 412 |
| `min_holding_trading_days` | 10 | 413 |
| `min_holding_loss_escape_r` | 0.5 | 425 |
| `enforce_time_stop` | True | 431 |
| `time_stop_trading_days` | 30 | 432 |
| `max_entries_per_week` | 10 | 437 |
| `max_aggregate_risk_at_stop_pct` | 0.05 | 444 |
| `max_concurrent_positions` | 10 | 449 |
| `entry_allow_list` | "" | 464 |
| `delever_target_fraction_of_cap` | 0.9 | 469 |
| `delever_sweep_enabled` | False | 475 |
| `reconciliation_poll_seconds` | 300 | 477 |
| `reconciliation_poll_timeout_seconds` | 120 | 492 |
| `ibkr_call_timeout_seconds` | 60 | 504 |
| `ibkr_permid_wait_seconds` | 5.0 | 519 |
| `protection_sweep_seconds` | 300 | 530 |
| `resting_order_reconcile_enabled` | True | 539 |
| `resting_order_cancel_enabled` | False | 550 |
| `corporate_action_mode` | "shadow" | 564 |
| `data_staleness_seconds` | 900 | 579 |
| `promotion_min_trades` / `promotion_min_average_r` / `promotion_min_win_rate` / `promotion_max_loss_to_avg_win` | 30 / 0.2 / 0.4 / 3.0 | 586-591 |
| `enforce_promotion_evidence` | False (forced True when live, 614-616) | 599 |
| `allow_short_selling` | False | 623 |
| `min_cash_reserve` | 1.0 | 630 |
| `data_dir` | `%LOCALAPPDATA%\QuantAdvisoryTerminal\data` or `QAT_HOME` (paths.py:36-66) | 636 |
| `market_data_source` | "synthetic" | 687 |
| `market_data_delay_seconds` | 1200 | 879 |
| `market` | "US" | 901 |

**Hard-coded values that are not Settings:**

- executor retry 60 s (executor.py:61); de-lever poll 300 s (delever.py:55);
- IB heartbeat 10 s, backoff 1-30 s, 5 reconnects, 6 connects (ib_adapter.py:234-241);
- quote wait 2 s (ib_adapter.py:75); cancel re-check 3 × 0.7 s (137-138);
- wide-replay warning 2 h and absorbed-id retention 30 days (oms.py:126, 129);
- stop-level and announced-price tolerance 1e-4 (oms.py:134, 140);
- stop-versus-target classification ×1.02 (oms.py:2447);
- resting quarantine clears after 3 clean scans (resting_order_anomaly.py:46);
- CRITICAL after 3 poll timeouts (reconciliation.py:32).

## (2) Present but not active in the default configuration

- The autonomous executor is inert unless `execution_mode="auto"` (executor.py:139-140, 160-161).
- `allow_autonomous_live_trading` is False, so live autonomy is off (config.py:62, 959-962).
- The de-lever trim is off (delever.py:166-167). The resting-order cancel is off (oms.py:2694-2701).
- Corporate-action `modify_order` does nothing in shadow mode (monitor.py:210-217, 306-315), and with IBKR detection is unsupported (monitor.py:369-381).
- `CorporateActionMonitor.reconcile_observed` has no caller in `src`.
- `OMS.symbol_allow_list` is never passed by the runtime (runtime.py:590-602). `entry_allow_list` is empty, so it is `None` (config.py:942-951).
- `broker_max_order_shares` is None, so there is no trim (oms.py:524-535). Promotion-evidence enforcement is off on paper (config.py:599, 614-616).
- `OMS.cancel_order` (oms.py:1247-1256) has no production caller.
- `IBAdapter` read-only mode, and live mode (it raises because `live_trading_confirmed` is never passed) (runtime.py:336-350; ib_adapter.py:244-249).
- The bracket and OCA `UnrepresentableOrderError` branches in `to_ib_order` cannot be reached through `place_order` (ib_translate.py:131-167; ib_adapter.py:887-890).
- The default broker is `mock`, whose `open_orders` returns `[]`, so the resting scan sees nothing there (mock_broker.py:173-191).

## (3) Places where two or more mechanisms guard the same thing

1. **Kill switch on entries** in four places: oms.py:369, engine.py:197, gate.py:123, oms.py:906. On exits: engine.py:392, gate, sign-off. On manual close: position_closer.py:599 and sign-off.
2. **Duplicate transmission:** status check (oms.py:882), the `_transmitted` set (oms.py:900), the gate's status rail (gate.py:125), and IB's unmapped-status default of `"transmitted"` (ib_translate.py:367).
3. **Duplicate entries:** the bridge pending check (signal_bridge.py:1321), held (1340), `has_live_buy` (1347), and the governor counting pending buys as slots and exposure (governor.py:136-154, 290-308).
4. **Cash:** the RiskEngine no-leverage rule (engine.py:241-254), the per-order cap trim against spendable cash (oms.py:456-519), and the sign-off re-check (oms.py:1018-1056).
5. **Protective duplicates and oversize:** the `awaiting_signoff` duplicate guard (oms.py:1741-1758), `naked_positions` detection (oms.py:1674-1686), and the sign-off held re-read (oms.py:951-1010).
6. **Leg cancel before exit** has two implementations with different verification predicates:
   - `PositionCloser._cancel_legs` treats an order as gone only if it is absent or has a terminal status (position_closer.py:219-249);
   - `OMS._release_protective_legs` treats any visible protective leg as still resting, regardless of status (oms.py:637-651);
   - plus the adapter's own re-cancel loop (ib_adapter.py:1103-1112).
   - The `legs_already_released` flag stops both running on one close (oms.py:725-742).
7. **Two quarantine stores both refuse entries:** position anomaly and resting-order anomaly (oms.py:338-351). Position anomalies also block re-arm (signal_bridge.py:1037) and de-lever (oms.py:682-690).
8. **Protection monitoring:** `verify_position_stops` (belief versus broker), `naked_positions` (broker only), and the resting-order excess scan.
9. **Reconciliation halt** twice: the OMS trips directly (oms.py:2576), and the monitor publishes `KillSwitchEvent`, which `KillSwitchEngine` handles as a second `trip`. The second is a no-op because the switch is already tripped (reconciliation.py:159-165).
10. **Day-P&L:** the equity monitor trips at a loss of 3% (`daily_loss_limit_pct`), while the gate halves buys at −2% and pauses them at −4%, using fresh equity per order (gate.py:260-281; executor.py:176-184). The kill-switch rail comes before these in the gate order.
11. **Price freshness for buys:** the gate's absent / previous-session print rail (gate.py:211-225) and the per-symbol staleness exclusion in the strategy engine (subscribed to `DataStaleEvent`, domain/strategies/engine.py:181-188).
12. **Live-trading gating:** the `IBAdapter` constructor, the gate's rail 2, and the `autonomy_enabled` property.

## (4) NOT DETERMINED

- **The deployed `.env` values** (broker, execution mode, market, flags). The file is outside the permitted folders.
- **ib_async and TWS behaviour the code relies on but I cannot verify from source:**
  - whether `reqExecutions` with a default `ExecutionFilter` returns other clientIds' executions, and how far back (ib_adapter.py:716-724 records this as unmeasured);
  - which statuses `reqAllOpenOrders` returns after a cancel;
  - whether `avgFillPrice` is populated at the `place_order` return;
  - whether the parent order's permId arrives while the parent is untransmitted;
  - Gateway TIF presets.
  - I would need the library source or broker logs.
- **Derived chain: a 202 on a bracket child leg.** When a leg's OCA sibling is cancelled by IBKR after a stop or target fill:
  - the 202 matches the entry's app id through `_ib_groups` (ib_adapter.py:1253-1255);
  - if the entry is still `transmitted` (not yet marked filled by an absorb pass), it is marked `rejected` (test_ib_adapter_hears_rejections.py:114-127 confirms the status write);
  - that publishes an `OrderRejectedEvent` carrying the placement-time `filled_quantity`, and the OMS then reverses the booking (oms.py:1349-1356).
  - Whether this sequence occurs in practice, and whether it leads to a reconciliation mismatch, is not determined. No end-to-end test was found.
- **Derived chain: an adopted leg filling.** `_adopt_from_broker` publishes `BrokerOrderIdResolvedEvent` for *any* order it adopts, including previous-session protective legs resolved during `cancel_order` or `modify_order` (ib_adapter.py:970-978). That registers the leg's permId as the app's own (oms.py:1296-1308). If such a leg later fills, `_is_foreign_unrecorded` returns False and the fill is not absorbed as foreign (oms.py:1914-1918). No test covering this was found.
- **Derived chain: a short position with an entry record.**
  - `naked_positions` includes shorts (oms.py:1685);
  - the entry record is kept when not flat (signal_bridge.py:1151-1169);
  - `submit_protective_stop` always proposes a SELL;
  - the sign-off re-read uses `abs()` (oms.py:1700-1703, 972-990).
  - Whether this situation arises, and no test with a held short was found.
- **Derived chain: a pending exit and a re-arm in recommend mode.** A signal exit awaiting a human releases its legs at proposal time (oms.py:731). The next re-arm sweep does not check for a pending exit on the symbol (signal_bridge.py:1036-1053). The combined outcome depends on the order of human sign-offs, which is not determined.
- **Code I did not read:** the `CostModel` conversion formula (`fill_price_from_average_cost`); `MarketDataFeed.last_print_at` semantics; `PortfolioRiskChecker` internals; `TradeLedger` restore and correction internals beyond the lines cited; `SessionController` effects on tick delivery; `AlpacaAdapter` and `SimulatedBroker` paths.
