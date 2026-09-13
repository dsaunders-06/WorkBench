# Quant Advisory Terminal: capability and gap assessment (technical)

**Build assessed:** M175, commit `5e322ca`, deployed 12 September 2026 10:51 AEST
and read back off the application log at the 10:55:08 launch.
**Date of assessment:** Saturday 12 September 2026.
**Account:** IBKR paper account, AUD base, ASX equities. No real money is at risk.
**Audience:** a reviewer auditing whether the system does what it claims and how
far it is from its stated objective.

> ⚠️ **Correction, 14 September 2026 (CE-018).** Section 1 states the design
> objective as the README and the paper put it. Those documents were written
> by Claude. The paper's "a human approves every order" was Claude's own
> addition. The operator's statement of original intent, given at audit
> Checkpoint A, is authoritative instead (see
> `docs/audit/2026-09-design-recovery/04-original-design-intent.md` §4.00,
> §4.001):
> - an app making recommended trades **using AI**, around **different
>   trading strategies**;
> - decisions **human or AI autonomous**, acting on its recommendation within
>   the safety rails and the selected strategy;
> - philosophy and strategies from the paper.
>
> The rest of this document is left as written.

---

## 0. Basis, and how to check it

Every figure here comes from one of three places. The source is named each time.

| Source | What it is | How to reproduce |
|---|---|---|
| Code | `src/qat/` at `5e322ca` on `origin/master` | read the named file |
| Live configuration | `%LOCALAPPDATA%\QuantAdvisoryTerminal\.env` | read it in PowerShell (a Bash sandbox serves a stale snapshot of this directory and does not report an error) |
| Live records | `%LOCALAPPDATA%\QuantAdvisoryTerminal\data\` (ledger, journals, `logs\qat.log`) | `scripts\session_check.ps1` (no arguments) and `scripts\handoff_state.py` |

Operational history comes from `docs/HANDOFF.md`, which dates each measurement.

**Documents that should not be used as evidence of current capability.**
`README.md` still describes build M111, and `docs/PRODUCT_DESCRIPTION.md` describes
M37 on a US market. Both carry a banner saying so. `docs/LIVE_TRADING_READINESS.md`
still states the reasoning for the live-money bar correctly, but its sections 3
and 6 predate the move to ASX.

Scale at `5e322ca`: 184 source modules (45,143 lines), 382 test files (49,661
lines), 3,703 tests collected, 952 commits since 25 July 2026. The build gate on
12 September passed 3,677 tests and skipped 26. ruff, black, mypy (strict on
`src`) and bandit are clean. CI (GitHub Actions) passed on `33d75d6`.

---

## 1. Design objective

`README.md` states the product: a multi-strategy share-trading advisory and
paper-trading desktop application for Windows. It detects the market regime,
generates and backtests strategy signals, enforces risk limits, trades through
Interactive Brokers, and uses a language model as an analyst that proposes and
explains. A human approves every order on a live account.

`docs/LIVE_TRADING_READINESS.md` sets the bar the project applies to itself.
The system may trade real money only once three things hold:

1. **The machinery is trustworthy.** Protection rests at the broker, fills
   reconcile, records are correct, and the risk rails bind.
2. **A strategy has demonstrated an edge net of costs, in the target market.**
   The system's own promotion gate encodes this: 30 closed trades, average net
   R of at least +0.20, a win rate of at least 40%, and a worst loss no larger
   than three times the average win.
3. **The gaps that turn an ordinary market event into a loss are closed.** The
   named gaps are corporate actions, trading halts, earnings gaps and execution
   quality.

Then the live-money locks open one at a time, starting in `recommend` mode.
In that mode a human signs every order.

The target market is the **ASX** through **Interactive Brokers**. Market data
comes from **yfinance**.

---

## 2. Operating configuration as deployed

Read from the live `.env` on 12 September. Code defaults in brackets where they
differ.

| Setting | Value | Note |
|---|---|---|
| `trading_mode` | `paper` | the default |
| `market` | `ASX` | [`US`] |
| `broker` | `ibkr`, IB Gateway, port 4002 | [`mock`] |
| `market_data_source` | `yfinance` | [`synthetic`]. Free, unofficial, delayed. The app models a 1,200 s delay (`market_data_delay_seconds`) |
| Watchlist | 99 ASX large caps plus `STW.AX` (the benchmark), 100 polled | category `megacap`, minimum average volume 100,000 |
| `execution_mode` | `auto` | [`recommend`]. Unattended sign-off through the autonomy gate, paper only |
| `deployed_strategies` / `autonomous_strategies` | `swing` | one strategy of fifteen |
| `per_trade_risk_pct` | 1% of equity | capped at 2% by validation |
| `max_aggregate_risk_at_stop_pct` | 5% | the binding constraint today (section 6) |
| `max_concurrent_positions` | 10 | |
| Single-name / sector / correlated-cluster caps | 15% / 30% / 30% at ρ ≥ 0.70 | the governor trims to fit before it refuses |
| Gap budget | 5% of equity lost at a 6% overnight gap | |
| `max_order_pct_of_cash` | 10% of available cash per order (code default) | |
| `kelly_fraction` | 0.5 | measured inputs from 20 closed trades (`edge_min_trades`) |
| Minimum hold / time stop | 10 / 30 trading days | escape at 0.5R against |
| `max_entries_per_week` | 10 | |
| `max_cost_to_risk_pct` | 10% | refuses a trade whose round-trip cost exceeds 10% of its risk |
| Daily loss / drawdown kill limits | 3% / 20% | |
| `min_cash_reserve` | AUD 1,000 | no leverage (section 4.4) |
| `delever_sweep_enabled` | `false` | a breach blocks new entries but does not sell |
| `resting_order_cancel_enabled` | `false` | the orphan-order rail reports but cannot cancel |
| Earnings sizing | on (code default): half size within 5 days of a scheduled announcement | |
| Local language model | LM Studio, `openai/gpt-oss-20b`, `http://localhost:1234/v1`, both request classes local | no position data leaves the machine |

---

## 3. Architecture

Three layers, communicating through typed events on an in-process asyncio event
bus (`src/qat/domain/bus.py`):

* **`presentation/`**: PySide6 views, no trading logic. Screens: Dashboard
  (balances, session panel, adopted positions, per-symbol verdict), Strategy
  Workbench, Regime Monitor, Risk Console, AI Advisor, Order Blotter, Screener,
  Performance, Settings.
* **`domain/`**: the engines. Strategies, regime, risk, OMS, autonomy,
  performance and evaluation, backtester, corporate actions, macro analysis,
  and AI advisory.
* **`data/`**: broker adapters behind `BrokerAdapter` (`IBAdapter` over
  `ib_async`, `MockBroker`, `SimulatedBroker`), market data sources, and storage.

`presentation/runtime.py` builds the engine graph and starts it in a fixed
order. The 12 September launch log shows that order: broker connection, warm
start, kill switch, risk, equity monitor, reconciliation, de-lever sweep, trade
ledger, reporter, market data, features, macro, strategies, autonomous
executor, corporate actions, signal-to-order bridge, regime, book risk, session
controller.

The application ships as a signed PyInstaller `--onedir` executable.
`scripts/deploy.ps1` installs it. The script refuses if the app is running, if
the build is unsigned or predates HEAD, or if the tree is dirty. It keeps the
previous install as a rollback directory, verifies the installed hash and
signature, and records the deployed commit. The first log line of every run
states the build (`Build: M175 (5e322ca, built ..., packaged)`).

---

## 4. What the system does today, by subsystem

### 4.1 Market data

* **Warm start.** 300 daily bars for each of the 100 symbols from yfinance
  before the feed starts, so indicators and the regime model are usable at the
  first bar. The 12 September launch seeded 100 symbols in 51 s.
* **Live feed.** yfinance polled every 60 s. The ASX feed publishes nothing for
  about the first 20 minutes of the session. This was measured on consecutive
  days: recovery at 10:20:34 on 9 September and 10:20:33 on 10 September. The
  app suppresses the resulting per-symbol errors inside that known window, and
  `session_check.ps1` states that the ERROR count at the open is expected.
* **Staleness.** Per symbol, by the trade's own timestamp, 900 s beyond the
  modelled feed delay (2,100 s real age). A stale symbol is excluded from
  signals. It never halts the account. Feed liveness is reported separately as
  MARKET DATA DOWN.
* **Macro.** FRED series `DGS3MO`, `DGS10`, `T10Y3M`, `VIXCLS` and `BAA10Y`, all
  US series. Section 6 covers the consequence.
* **Fundamentals.** yfinance, cached for 7 days. A missing field makes the
  strategy abstain on that symbol. The system never substitutes zero or a
  median.

### 4.2 Regime detection

`domain/regime_engine/`. A Gaussian HMM (`hmmlearn`, 4 states, diagonal
covariance) runs on six standardised daily features (`feature_matrix.py`):
benchmark log return, realised volatility, VIX level, yield-curve slope, credit
spread and breadth across the 99 names. It refits every 20 bars and needs 60
bars before its first fit.

`fusion.py` combines the HMM posterior with rules: a recession probit on the
curve, a bull block below the 200-day average, and a VIX axis. A hysteresis
gate then produces one of seven labels. Each label carries an exposure scalar
that multiplies every position size: bull 1.0, low_vol 1.0, recovery 0.9,
sideways 0.7, bear 0.5, high_vol 0.4, recession 0.3.

Strategies gate on **probability mass** across their suitable regimes (50% by
default), not on the top label. Until the engine publishes its first
classification, the strategy engine refuses **all entries** and logs that it is
doing so (`strategies/engine.py:408-418`). Exits are unaffected.

*Observed:* on 11 September the engine classified `sideways` (scalar 0.70) with
probabilities sideways 0.46, low_vol 0.31, recovery 0.22.

### 4.3 Strategies

Fifteen rules-based strategies with fixed, hand-set parameters. There is no
fitting and no optimisation (`domain/strategies/`): breakout, CAN SLIM, dividend
growth, GARP, growth, mean reversion, momentum, multi-factor, pairs statistical
arbitrage, quality, sector rotation, **swing**, trend following, value and
volatility.

**Only `swing` is deployed.** It enters on a pullback to EMA20 inside an
EMA20 > EMA50 uptrend. Its stop sits at 2.5 × ATR(14) and its target at 2R. It
exits on the crossover breaking (`strategies/swing.py`). Suitable regimes are
sideways, bull, low_vol and recovery. That set was widened from sideways-only
by operator decision on 30 July, and the decision is recorded in the code.

The other fourteen strategies are built and backtestable but have produced no
live trades. Their live behaviour is unmeasured.

### 4.4 Risk and sizing (every buy)

`domain/risk_engine/`. The fixed sequence is: sizing, stop confirmation,
portfolio governor, portfolio checks, regime scalar and earnings scalar, cash
cap, then the cost rail last. Every decision, including each refusal, is written
with its inputs to `risk_decisions.csv`.

* **Sizing** (`sizing.py`, `kelly.py`): half-Kelly, bounded by a volatility
  target and the 1% per-trade risk cap. The stop distance is the strategy's own
  stop, so the size and the resting stop describe the same trade. The Kelly
  inputs are **defaults** (win rate 0.55, payoff 1.5) until the strategy has 20
  closed trades. It has 8 today (section 5), so every position so far was sized
  on the defaults.
* **Governor** (`governor.py`): aggregate risk-at-stop measured at current
  prices, concurrent positions, and single-name, sector and correlated-cluster
  concentration. Pending orders count as committed exposure. Over-cap candidates
  are trimmed to the remaining headroom and refused only when not one whole
  share fits.
* **No leverage.** A buy may not spend more than cash less the reserve. The
  check runs twice, at sizing and again at sign-off against the current balance
  under a lock. It fails closed if no price is available. Sells are exempt.
* **Cost rail.** Round-trip cost against 1R. ASX pricing is IBKR Fixed at 0.088%
  with an AUD 6.60 minimum per order. On 11 September commission was confirmed
  equal to this model, to the cent, on 17 of 17 logged orders.
* **Earnings.** Half size within 5 days of a scheduled announcement.
  `earnings_at_entry` and `held_through_earnings` are recorded on each trade
  (M174). Whether to hold through an announcement is an open policy decision
  (section 7).

### 4.5 Order management and execution

`domain/oms/`, `domain/autonomy/`.

* **Nothing reaches the broker without sign-off.** `submit_order()` only creates
  a `pending_signoff` order. `OMS.sign_off()` is the only path to transmission,
  and a second guard refuses a repeat transmission independently of any status
  field (M139, after the 24 August duplicate-order incident in section 5.2).
* **Autonomy gate** (`autonomy/gate.py`). These rails apply to every order:
  execution mode, the live-account block, the kill switch, and order status.
  After those, a resting protective stop is allowed even when the market is
  closed, because it rests GTC. When the market is closed, market orders are
  refused. During the ASX opening auction every order except a resting stop is
  refused, because a market order would fill at the auction price. For buys the
  gate also checks: a current-session print for the symbol, an eligible session
  phase, the strategy on the autonomous list, the promotion evidence (see
  below), day P&L above −4% (size halves below −2%), and price drift of 3% or
  less from the sizing price.
* **Entries are bracket orders.** A market buy, a GTC protective stop and a GTC
  target travel together, with the two exit legs linked one-cancels-other. The
  protection outlives the process, a restart and the market close.
* **Signal-driven exits** are market sells. They respect the 10-day minimum hold
  unless the position is 0.5R against its stop. The 30-day time stop forces an
  exit.

**Promotion evidence** is enforced unconditionally on a live account
(`Settings.promotion_evidence_enforced`). On paper it is advisory, because paper
is where the evidence gets produced.

### 4.6 Protection and reconciliation

* **Reconciliation** polls broker positions. Pre-existing positions are adopted
  at startup as the baseline. On 12 September at 10:56:09, 9 of 9 positions
  were adopted, each with a stop resting at the broker. A mismatch between
  tracked and broker positions trips the kill switch.
* **Broker-side fills.** A stop or target that fires at the broker is fetched
  through a persisted fill watermark and recorded as a closed trade at its real
  price. *Observed:* BHP.AX stopped out at the 11 September open, filling at
  60.40 against a 60.45 stop. The app absorbed it at 10:03:22 with no mismatch
  and no trip.
* **Re-arm and protection sweep.** At startup, and every 300 s after, any held
  position without a resting stop gets a replacement OCO at its recorded
  levels. A position with no recorded stop is reported as unprotected; the app
  does not invent a level for it.
* **Resting-order scan.** Every working order at the broker is matched against
  a position (`oms/resting_orders.py`). On 12 September it read 18 legs across 9
  symbols, nothing unjustified. It **reports orphans but cannot cancel them**
  (`resting_order_cancel_enabled = false`, a deliberate choice).
* **Kill switch** (`risk_engine/kill_switch.py`). It trips on daily loss (3%),
  drawdown from the high-water mark (20%), a reconciliation mismatch, or a
  manual trigger. Its state persists in `kill_switch.json`. While tripped it
  blocks **every** sign-off, exits and protective repairs included
  (`oms.py:906`, and first among the gate's rails). Stops already resting at
  the broker keep working. A human must reset it. It was clear on 12 September.
* **Entry-price correction (M65/M70/M175).** Recorded entry prices are corrected
  to the broker's figure. IBKR's `avgCost` includes commission, so M175 converts
  it back to the fill price. A record stamped as an observed `fill` is never
  overwritten. *Observed:* at the 12 September launch, M65 corrected exactly the
  five expected records (COH, JHX, TAH, TWE, WOW), each 8.8 bp lower. It did not
  touch the four stamped `fill` records.

### 4.7 Evidence layer

`domain/performance/`, `domain/evaluation/`.

* **Trade ledger** (`closed_trades.csv`). FIFO lot matching. One commission
  floor per order, apportioned across lots. Gross P&L, costs and net P&L are
  kept separate. Each row also records R, gross R, stop, holding days, exit
  reason, entry slippage against the sizing price, MAE and MFE in R, earnings
  flags, market and currency. `audit_closed_trades()` checks every stored
  derived column against its recomputation. It returned **0 findings** on the
  repaired file on 12 September, down from 15 before the repair. An exit
  stamped before its entry is refused (`trades.py:1190`).
* **Decision journal** and **risk audit trail**: every proposal, sign-off and
  refusal, with the reason and the operator.
* **Commission audit (M175, new).** `IBAdapter` totals IBKR's
  `commissionReport` per order. `CommissionAuditor` writes
  `commission_checks.csv` with `COMMISSION VERIFIED` or `COMMISSION DISAGREES`.
  The model stays authoritative and IBKR's figure checks it. **This has not yet
  run on a live order.**
* **Reports.** A daily report after the close and a weekly report, both
  including held positions.
* **Promotion scorecard** (`performance/scorecard.py`), fed by the net figures
  from the ledger.

### 4.8 Research tooling

`domain/backtester/`. The vectorised engine uses the live cost model, with
Monte Carlo trade resampling and walk-forward windows. `replay_session.py`
replays the live engine graph against historical bars through `SimulatedBroker`.
It also offers an ablation switch for regime features and a run manifest for
reproducibility. `evaluation/replay_agreement.py` compares replayed decisions
with live ones.

The walk-forward caveat recorded at M37 has not been re-examined for this
assessment. The windows slice the signal series, so a held position is
re-opened at each window boundary.

### 4.9 AI advisory

`domain/ai_advisory/`. A router with two request classes, general and
position-sensitive, each assignable to a local model, the Anthropic API or a
demo engine. Both are set to the local model. The advisory service holds no
reference to the OMS or the broker, so **no model output can place, size or
approve an order**. Its recommendations are re-checked against the risk engine.
Text inside fetched context is rendered as data, never as instructions. The
engine is chosen once at launch. If LM Studio is down then, the AI panels run on
the demo engine for the whole session. The trading path contains no language
model.

### 4.10 Operations

* **Pre-flight** (`src/qat/preflight.py`). Read-only checks of settings, the
  Gateway, the book, contracts, session hours against IBKR's own, the feed and
  the session. A check that could not run returns `UNKNOWN`, which blocks READY
  just as `FAIL` does.
* **`scripts/session_check.ps1`** reads the running or last session: the build
  stamp, five health checks, errors, staleness, the audit trail, the ledgers,
  equity and the daily report.
* **Live-money locks.** `trading_mode = live` alone makes the adapter refuse to
  start. Reaching live needs a code change (`live_trading_confirmed`, which no
  caller in `src/` passes). Unattended live trading needs a further separate
  flag. `paper` pointed at a live Gateway port is refused.

---

## 5. Live evidence to date

### 5.1 Closed trades

ASX live since 24 August 2026 (15 ASX trading days to 11 September). Source: the
repaired `closed_trades.csv` (12 rows, sha256 `688B7091…`), grouped into
positions. All rows are attributed to `swing`.

| Symbol | Opened | Closed | Shares | Net P&L (AUD) | Net R | Exit (as recorded) |
|---|---|---|---|---|---|---|
| LOV.AX | 25 Aug | 26 Aug | 3,217 | +13,522.87 | +1.84 | target (5 rows; one written by a 26 Aug repair script) |
| RHC.AX | 25 Aug | 26 Aug | 1,194 | +5,839.34 | +2.57 | target |
| PNI.AX | 25 Aug | 31 Aug | 2,973 | −7,074.12 | −1.64 | stop |
| TNE.AX | 24 Aug | 3 Sep | 60 | −139.17 | −1.03 | target (see 8.2) |
| A2M.AX | 25 Aug | 4 Sep | 9,636 | −5,028.41 | −0.71 | signal |
| IAG.AX | 25 Aug | 9 Sep | 6,699 | −1,766.66 | −0.41 | signal |
| SEK.AX | 26 Aug | 9 Sep | 2,978 | −5,851.70 | −0.94 | signal |
| BHP.AX | 9 Sep | 11 Sep | 793 | −2,997.17 | −1.04 | stop |
| **Total** | | | | **−3,495.02** | **mean −0.17** | 2 wins, 6 losses |

Costs across the eight positions were AUD 704.21. Measured against the
promotion bar, the record shows 8 of 30 trades, an average R of −0.17 against
+0.20 required, and a win rate of 25% against 40%. **Eight trades is not a
sample.** It shows neither an edge nor its absence, and the gate exists for
exactly that reason.

PNI's stop-out cost 1.64R rather than the 1R the sizing assumed, because the
price gapped through the stop.

**Open book on 12 September:** nine positions, all protected, 18 resting legs.
ANZ 640, ASX 1,314, BOQ 13,586, COH 363, JHX 1,097, SUN 3,192, TAH 64,229,
TWE 10,412, WOW 1,098. Day-start equity AUD 989,604.29, against about AUD 1.0M
at the start of the ASX phase.

### 5.2 What live operation found

Tests could not have found these. Each one came from running against the real
broker, and each is documented in `docs/HANDOFF.md`.

* **24 August.** A re-transmission defect sent the same order four times. The
  book took 68,268 DXS shares against 17,067 intended, and 12,304 TNE against
  3,076. That was about AUD 800k of exposure and sixteen orphaned GTC legs. The
  operator unwound it the same afternoon for −0.28% of equity. M139 fixed it,
  and a separate OMS guard now blocks a second transmission.
* **3 September.** TWS staged an order without transmitting it, and the app
  booked the position anyway. The kill switch caught the mismatch.
* **9 September.** Four kill-switch trips from two causes, and three deploys
  in one live session.
* **11 September.** The measurement that became M175. Commission was already
  correct, but the ledger's price basis was wrong: commission was charged twice,
  slippage was charged on real fills, and the floor was charged per absorbed
  piece. The repair moved net P&L from −4,065.73 to −3,495.02.

---

## 6. Assessment against the objective

**Machinery (objective 1): largely built and substantially verified live.**
Bracketed protection rests at the broker and survived restarts, closes and a
broker-side stop-out. Reconciliation catches phantom and duplicate positions.
The ledger now passes its own audit. Build, deploy and read-back are scripted.
What remains unproven live:

* **An app-driven market exit since the M173 time-in-force fix.** BHP's exit on
  11 September was a resting stop, not an app-transmitted market sell. This is
  the first thing to watch (IBKR error 10349).
* **The M175 commission check on a real order.** It has not run yet.
* **The opening-auction refusal.** Not exercised. The feed's 20-minute delay
  meant no signals existed in that window.

**Edge (objective 2): not demonstrated, and not currently accumulating.**
Eight closed trades, and the system has refused every new entry since 11
September:

* **The aggregate risk cap blocks entries.** Aggregate risk-at-stop was about
  7.6% against the 5% cap on 11 September, and the governor refused all 449
  entry decisions that day (`governor.py` rejects when headroom ≤ 0). Nothing
  enters until held positions close or move. At 1% per trade the 5% cap allows
  about five full-size positions, so the 10-position limit cannot bind first.
  `session_check.ps1`'s footer still names the position count as the gate. It
  is wrong today.
* **Throughput.** At the observed rate (8 positions in 15 trading days) the
  Kelly threshold of 20 would take about another 22 trading days and the
  promotion bar of 30 about another 41. That holds only if entries were
  flowing, and they are not.
* **Regime inputs are mostly US.** The five macro series are US FRED series.
  A feature ablation over 249 bars in late August found that `vix_level` alone
  changes 213 of 249 labels (86%). The only ASX-derived column, breadth,
  changes 27%. The label that scales every ASX position is driven largely by
  US conditions. The Australian FRED series are monthly and were 99 days stale
  when measured (M170).

**Event-risk gaps (objective 3): partly addressed.**

| Gap | State |
|---|---|
| Corporate actions (M39) | Machinery exists (`domain/corporate_actions/`, M60 quarantine). **IBKR serves no announcements**, so a split is invisible before its ex-date. The app states this at every startup. Closed by decision on 10 September. |
| Trading halts (M43) | No detection. A held position in a halted name cannot exit, and its stop cannot fill. |
| Earnings gaps (M41) | Detection and half-size entry are built (M57, M174). Holding through the announcement is an undecided policy. Nobody has measured how many of about 40 announcements a year gapped. |
| Execution quality (M44) | Every entry and every discretionary exit is a market order. Slippage is measured per trade (`entry_slippage`) but has not been analysed. |

---

## 7. Work remaining to reach the objective

Ordered by what blocks what.

**A. Make evidence accumulate again.**
1. Decide how the book gets back under the 5% aggregate cap (protection or
   targets closing positions, an operator decision, or a deliberate change to
   the cap or per-trade risk). Nothing else in section B moves until entries
   flow.
2. Correct `session_check.ps1`'s footer so it names the gate actually binding.

**B. Prove the unproven live paths.**
3. An app-driven market exit with no 10349, no trip and a clean resting-order
   scan (M173).
4. The first `COMMISSION VERIFIED` on an app-transmitted order. Separately,
   establish whether a broker-side stop ever produces one. A second client
   receives no commission report, so this is unmeasured.
5. The opening-auction refusal, on a day the feed publishes early.

**C. Reach the evidence thresholds.**
6. 20 closed `swing` trades, so Kelly sizing runs on measured inputs.
7. 30 closed trades, so the promotion gate can be read. Then judge the result
   net of costs against the bar in section 1.

**D. Close the gaps that matter with real money.**
8. Trading-halt detection (M43).
9. The earnings hold-through policy (M41), informed by a measurement of how
   often past announcements gapped.
10. An execution-quality review (M44) from the recorded `entry_slippage` and
    stop-gap outcomes. PNI's 1.64R stop-out is the first data point.
11. Sourcing Australian regime inputs (stage 4). This is a data problem first:
    there is no timely AU macro series to use.
12. A decision on letting the orphan rail cancel (`resting_order_cancel_enabled`).
13. Running `audit_closed_trades` on a schedule. The ledger failed its own
    audit for weeks and nothing reported it.

**E. Only then, the live locks.** Open them one at a time, with
`execution_mode = recommend`, per `docs/LIVE_TRADING_READINESS.md` section 6.
Out of scope today: tax and reporting, margin and settlement, and currency
handling beyond a single-currency AUD account.

**Also parked.** Saving weekly opens and closes from daily bars. Checking the
HMM's sensitivity to a seventh feature column (measured 1 September, not acted
on). Watching for a blank status cell inside a hold window.

---

## 8. Items for the auditor

Found while preparing this document and not yet resolved.

1. **`regime_at_entry` is blank on all 12 ledger rows.** The same holds for
   `regime_probability` and `exposure_scalar`. The diagnostic meant to explain
   why a trade happened is empty for every ASX trade. The cause has not been
   investigated.
2. **TNE.AX's row is a 60-share remnant of a 3,051-share entry.** The rest left
   through the operator's manual clean-up after the 24 August duplicate orders
   and is not in the ledger. The row records its exit as `target` at a loss.
   `docs/HANDOFF.md` records TNE stopping out at 30.69 on 3 September. The
   label is unverified.
3. **One LOV.AX row was written by a repair script** (exit reason
   `target (ledger repair 26 Aug - unabsorbed remainder)`), not by the app's own
   ledger path.
4. **The master CI run on the M175 merge (`a24faa9`) failed.** Two pre-flight
   tests built their fixture from the real clock and failed on the first
   weekend after they were written. The fix is test-only (`5e322ca`, 12
   September), and CI passed on `33d75d6`. Production code was correct.
5. **`README.md` and `docs/PRODUCT_DESCRIPTION.md` are stale**, as noted in
   section 0.
6. **The code base retains a US-market path from July 2026.** It is not
   configured and is outside the scope of this assessment.
