# QAT Design Recovery & Design Intent Audit, report section 5: Current Architecture

> **Final report section, issued 15 September 2026** for the operator's review (Checkpoint B). Findings made after a section was drafted are recorded as dated correction notes in place; nothing has been silently rewritten.

**Brief §4 (the plan's retired "Stage 3"). Reviewed at Checkpoint A (14 Sep).**
**Prepared:** 14 September 2026, from four fresh-context investigator reports
(12 September) and cross-checks against the code and logs.
**What this section is:** what the code *does*, established from executable
statements, with file:line evidence. It makes no judgement. Judgement starts
in section 6, where each point has to cite this section.

## 5.0 How this was produced

Four investigators traced the system, one part each. Each read only
`src/qat` and `tests`, with no documentation, git history or narrative. Each
treated code comments as claims and reported "NOT DETERMINED" rather than
guessing. The reports are kept verbatim as evidence:

| Report | Scope |
|---|---|
| `stage3/investigator-1-data-to-signal.md` | market data → data quality → features → regime → strategy signal |
| `stage3/investigator-2-signal-to-pending-order.md` | signal → sizing → risk engine → governor → costs → pending order |
| `stage3/investigator-3-signoff-to-reconciliation.md` | sign-off → broker → fills → reconciliation → protection → kill switch → exits |
| `stage3/investigator-4-wiring-ledger-ai.md` | runtime wiring, ledger and evidence files, the AI/LLM boundary |

**Configuration.** The investigators could not read the live `.env`, so they
describe code defaults. Where the deployed value differs (report §3.5), this
section states the **deployed** behaviour: market ASX, broker IBKR, yfinance
prices and fundamentals, execution `auto`, `swing` deployed, both LLM slots
local.

**Cross-verified by the auditor on 14 September** (code re-read, and logs
where marked):

| Claim | Result |
|---|---|
| Exit cancels protective legs before the kill-switch check (Inv. 3) | **Confirmed in code** (`oms.py:731` then `745`) **and in the logs**: IAG.AX had no broker stop from 11:21:46 to 12:20:40 on 9 Sep. Logged as **CE-017**; reported to the operator, who chose "decide later, continue audit" |
| Swing evaluates on the forming (intraday) bar (Inv. 1) | **Confirmed**: `strategies/engine.py:391` calls `bars.frame(...)`, and `data/bars.py:290` includes the forming bar by default |
| Quantity booked at sign-off whatever status the broker returned (Inv. 3) | **Confirmed**: `oms.py:1134-1137`, with no status check after `place_order` returns |
| No gap filter on swing entries (Stage 2) | **Confirmed**: no minimum trend gap anywhere in `src` |
| Earnings calendar built as US for an ASX book (Inv. 2) | **Confirmed**: `runtime.py:402` passes no market; `earnings.py:107` defaults to `"US"`. Active in the deployed configuration (`fundamentals_source=yfinance`) |
| Regime fields blank on restored lots (Inv. 4) | **Consistent with the ledger**: all 12 rows are blank, and the app is closed and relaunched daily, so every position held overnight is a restored lot. Not yet traced row by row |

The remaining facts stand as reported and are open to challenge at
Checkpoint A.

## 5.1 The actual flow

This follows the audit brief's flow, amended where the implementation
differs:

```
Market data ─ yfinance, one 1-minute download per 60 s poll, modelled 20-min delay (inv-1 A)
   │           (only during ASX hours; warm start seeds 300 daily bars at launch)
   ▼
Data quality ─ per-symbol staleness only (> 2,100 s old ⇒ symbol excluded from signals);
   │           feed-health event (UI only). validation.py is NOT on the live path (inv-1 B)
   ▼
Features ───── FeatureEngine publishes FeatureEvent to NO subscriber; the strategy
   │           engine and the bridge each compute their own (inv-1 C)
   ▼
Regime ─────── HMM (4 states) + rules + fusion + hysteresis, recomputed on EVERY benchmark
   │           tick; label → exposure scalar; probabilities → strategy eligibility (inv-1 D)
   ▼
Strategy ───── swing only; daily bars INCLUDING today's forming bar; BUY = EMA20>EMA50 and
   │           yesterday's close ≤ EMA20 and the running price > EMA20 (inv-1 E)
   ▼
Candidate ──── signal bridge: pending/held/live-buy de-dup, weekly entry budget (10),
   │           minimum hold on signal exits, time stop (30 weekdays) (inv-2 A)
   ▼
Sizing ─────── min(Kelly f × equity / price, 1% × equity / (2.5 × ATR)); Kelly inputs are
   │           placeholders (0.55 / 1.5) until 20 closed trades (inv-2 B)
   ▼
Risk engine ── stop budget → regime × earnings scalar → no-leverage cash rule →
   │           PORTFOLIO GOVERNOR (count, aggregate risk-at-stop, name, sector, cluster, gap)
   │           → portfolio ES/concentration check → cost-to-risk rail (inv-2 C-E)
   ▼
OMS submit ─── allow lists, position/resting anomalies, pending corporate action,
   │           kill switch, whole shares, 10%-of-cash per-order cap → PENDING SIGN-OFF (inv-2 G)
   ▼
Autonomy gate  18 rails (mode, live, kill switch, session, opening auction, freshness,
   │           strategy list, promotion evidence [off on paper], day P&L, price drift) (inv-3 A)
   ▼
Sign-off ───── lock; duplicate-transmission guard; kill switch; protective re-read;
   │           buy cash re-check; broker.place_order (the ONLY caller) (inv-3 A)
   ▼
Broker ─────── IBKR: MKT parent GTC + STP and LMT children, OCA, GTC (inv-3 B)
   ▼
"Fill" ─────── OrderFilledEvent is published AT TRANSMISSION, usually at the reference
   │           price; real executions are absorbed only in the 5-minute reconciliation poll
   ▼
Reconciliation quantity-only compare with broker; unexplained mismatch ⇒ kill switch (inv-3 E)
   ▼
Ledger ─────── lot opened at transmission; later corrections applied by order id (inv-4 §2)
   ▼
Reporting ──── daily/weekly Markdown reports (+ AI narrative), CSV journals (inv-4 §2.17-2.21)
```

**Protection runs alongside** this flow (inv-3 F): brackets at entry; re-arm at
startup and every 300 s; `verify_position_stops` on every reconciliation poll;
the resting-order scan (reports, never cancels, because
`resting_order_cancel_enabled` is false).

## 5.2 Per-stage summary

| Stage | Module(s) | Decides | Persists | AI? | Reaches the broker? |
|---|---|---|---|---|---|
| Market data | `data/market_data.py`, `data/yfinance_source.py`, `domain/warm_start.py` | which prices exist, and when | none | no | indirectly (prices drive signals and sizing) |
| Data quality | `MarketDataFeed` staleness; gate freshness rail | per-symbol exclusion from signals; buys need a same-session print | none | no | blocks signals and buys |
| Features | `data/feature_engine.py` (output unused), strategy engine, bridge | none | none | no | via the strategy and bridge copies only |
| Regime | `domain/regime_engine/*` | size multiplier; strategy eligibility | none (memory only) | no (statistical HMM, seed 0) | scales every buy |
| Strategy | `domain/strategies/engine.py`, `swing.py` | whether a signal exists | none | no | yes, originates entries and trend-break exits |
| Candidate | `domain/oms/signal_bridge.py` | de-dup, hold, time stop, weekly budget | `open_position_entries.json` | no | yes |
| Sizing and risk | `domain/risk_engine/*` | approve / trim / reject; share count; stop | `risk_decisions.csv` | no | yes |
| OMS | `domain/oms/oms.py` | pending creation; sign-off; exits; leg release | `absorbed_fills.json`, `decision_journal.csv` | no | yes, the only path to `place_order` |
| Autonomy | `domain/autonomy/gate.py`, `executor.py` | unattended sign-off | journal rows | no | yes, signs orders without a human |
| Broker | `data/broker/ib_adapter.py`, `ib_translate.py` | order construction; error classification (HALT ⇒ kill switch) | none | no | is the broker path |
| Reconciliation and protection | `domain/oms/reconciliation.py`, OMS protection methods, `signal_bridge.rearm_protective_stops` | mismatch ⇒ kill switch; re-arm proposals | anomaly stores | no | yes (re-arm; leg cancels) |
| Kill switch | `domain/risk_engine/kill_switch.py` | blocks every sign-off | `kill_switch.json` | no | blocks it |
| Ledger and evidence | `domain/performance/*` | nothing about orders (EdgeEstimator feeds sizing after 20 trades) | `closed_trades.csv`, `equity_curve.csv`, reports | narrative only | only through Kelly inputs, once measured |
| AI advisory | `domain/ai_advisory/*` | nothing | report narratives, log | yes | **no path found** (inv-4 §3.7) |

## 5.3 Facts that bear most on the audit questions

Stated as facts only. Their significance is assessed in sections 8–16.

**Execution and protection**

1. **An exit releases the position's protective legs when the exit is
   *proposed*, before the kill-switch check and before any sign-off**
   (`oms.py:731-747`). While the kill switch is tripped, the re-arm proposals
   cannot transmit (gate rail 3; `oms.py:906`). This happened live on 9 Sep
   (CE-017).
2. **The quantity is booked at sign-off from the ordered size**, whatever
   status the broker returns (`oms.py:1134-1137`). `OrderFilledEvent` is
   published at transmission, usually carrying the sizing reference price
   (`oms.py:1164-1208`). Real executions are absorbed only inside the
   reconciliation poll, every 300 s (`oms.py:2516`).
3. **The kill switch does not trip on data staleness.** Its docstring says it
   does (`kill_switch.py:1-4`), and so does the paper's §18.2. The trip paths
   are daily loss, drawdown, reconciliation mismatch, manual, IBKR reconnect
   exhaustion, and any unrecognised order-scoped IBKR error (inv-3 G).
4. **Reset needs no confirmation**; tripping does (`risk_console.py:675-685`).
5. **Two leg-cancel implementations** with different "gone" tests exist: the
   OMS exit path and the manual-close path (inv-3 §3.6).

**Strategy and signal**

6. **Swing decides on the forming bar.** `close[-1]` is today's running
   (delayed) price, so a BUY can fire intraday and the day can then close
   back below the EMA20. The operator's methodology says to wait for the
   daily candle to close (report §4.3).
7. **The swing entry rule is the first commit's rule, unchanged**, with its
   parameters hard-coded in the constructor. `settings.atr_stop_multiple` is
   not read by swing (inv-1 E).
8. **A stale symbol is excluded from all strategy evaluation, exits
   included.** The exclusion can outlast a feed restart (derived; no test)
   (inv-1 B).

**Regime**

9. **Only three of the five FRED series feed the regime**: VIXCLS, T10Y3M and
   BAA10Y. DGS3MO and DGS10 are fetched and ignored (inv-1 D).
10. **Hysteresis and the "recovery" slope term are counted per tick, not per
    bar** (inv-1 D).
11. **The VIX thresholds (15 / 25) are hard-coded.** `settings.vix_shock_level`
    is not read by the regime engine (inv-1 D).

**Sizing and risk**

12. **Kelly sizing runs on placeholder inputs**: W 0.55, R 1.5, giving
    f = 0.125 of equity notional at half-Kelly. It is taken as the minimum
    against the ATR risk cap. The paper's "blended with volatility
    targeting" is a minimum, not a blend (inv-2 B).
13. **The governor values positions on two bases**: the broker mark for
    aggregate risk and the gap budget, average cost for name, sector and
    cluster (inv-2 D).
14. **VaR 95 and VaR 99 are computed and never gated**; ES 97.5 is gated at
    3% (inv-2 D).
15. **The earnings calendar is built with `market="US"`**, so it counts
    distances on the US calendar and in the US timezone for ASX symbols. It
    is active in the deployed configuration because
    `fundamentals_source=yfinance` (inv-2 A.12).

**Evidence and ledger**

16. **Regime fields are set only on lots opened live after a RegimeEvent.**
    Restored lots never carry them, and `open_position_entries.json` does not
    persist them (inv-4 §2.7). The ledger has 12 of 12 blank.
17. **The ledger has no handler for broker rejections or cancellations.** A lot
    booked at transmission stays after a later rejection (inv-4 §2.10).
18. **`audit_closed_trades` has no caller in the application** (inv-4 §2.12).
19. **The promotion scorecard does not filter by market; the Kelly
    EdgeEstimator does** (inv-4 §2.19-2.20).
20. **The report heading "Autonomy decisions blocked" counts every
    non-auto-signed journal row**, including proposals and sign-offs
    (inv-4 §2.17).

**AI boundary**

21. **No code path was found from any AI output to strategy selection,
    sizing, sign-off, the OMS, the broker or settings** (exhaustive import and
    reference search, inv-4 §3.7). AI output reaches Qt panels, the log, and
    the daily/weekly report files (the narrator). `get_trade_rationale`, the
    only AI path that would call the risk engine, is not wired.
22. The engine is chosen once at startup. With LM Studio unreachable then,
    the slots fall back to a demo engine for the session (inv-4 §3.2).

**Present but not wired** (inv-1 §2, inv-4 §1.7, §2)

23. The list:
    - `data/validation.py` (including corporate-action adjustment);
    - `FeatureEvent` consumers;
    - `preflight.py` (run only as a script);
    - `Orchestrator.stop_all`;
    - `audit_closed_trades`;
    - `regenerate_daily`;
    - the storage modules;
    - the replay/ablation research modules (used by scripts, not by the app);
    - `get_trade_rationale`.

## 5.4 Still NOT DETERMINED

Carried from the reports. These need runtime observation or library source.

- whether IBKR `avgFillPrice` is populated when `place_order` returns
- whether the permId is present at transmission
- whether `reqExecutions` returns other client ids' executions
- whether the 202-on-bracket-child chain causes reconciliation mismatches
  (inv-3 §4)
- startup race between feeds and subscribers (inv-1 §3)
- whether Yahoo's daily history includes today's partial bar
