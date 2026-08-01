# Quant Advisory Terminal — Product Description

**As at 1 August 2026. Build M36.**

This document describes what the software currently does, verified against the
code and against a live paper-trading account. It is written for evaluation, so
it states capability and limitation with equal weight. Nothing here is
aspirational: where a feature exists but has not yet been exercised against real
market conditions, that is said explicitly.

---

## 1. What it is

Quant Advisory Terminal (QAT) is a Windows desktop application for **algorithmic
paper trading of US equities**. It combines live market data, a statistical
market-regime detector, fifteen rules-based strategies, a backtester, a
multi-layer risk engine, a broker connection and an optional AI research
assistant into a single workstation.

It is a **decision-and-execution system with an evidence layer**, not a signal
generator. Its distinguishing characteristic is the amount of machinery devoted
to *not* trading: refusing, resizing, halting, and recording why.

It runs as a signed single-executable Windows application. Configuration and
records live under the user's local application data; API credentials are held
only in the Windows Credential Manager and never in configuration files.

### Current operating state

| | |
|---|---|
| Market | US equities, Alpaca paper account |
| Mode | Paper trading, unattended execution enabled for one strategy |
| Deployed strategy | `swing` |
| Watchlist | 100 symbols |
| Live since | 27 July 2026 |
| Closed trades to date | 0 |

That last line is the most important fact in this document and is expanded in
§7.

---

## 2. What it actually does

### 2.1 Market data and warm start

Live quotes and daily bars come from Alpaca. At launch the application seeds its
rolling buffers with 300 daily bars per symbol, so the regime detector and the
strategies are usable immediately rather than after days of accumulation.
Macroeconomic series (Treasury yields, VIX, credit spreads) are pulled from FRED
with retry; a failed fetch keeps the previous value rather than substituting
zero, and says so.

A per-symbol staleness check refuses to size a trade against a quote that is too
old. It is scoped to the symbol deliberately — a thin or halted ticker is a
reason to stop trading that ticker, never to halt the account.

### 2.2 Regime detection

A Gaussian Hidden Markov Model runs over six features (benchmark returns,
realised volatility, breadth, yield-curve slope, VIX level, credit spread),
fused with rule-based signals and passed through a hysteresis filter to produce
one of seven named regimes plus a probability distribution across them.

Each regime carries an **exposure scalar** that multiplies every position size.
Strategies declare which regimes they suit, and are gated on the **probability
mass** across those regimes rather than on the single most likely label — so a
strategy suited to three regimes holding 60% of the probability is not switched
off because a fourth holds 35%.

*Observed in production:* classifies within seconds of the opening bell, has
returned `high_vol` (exposure scalar 0.40) on every classification to date.

### 2.3 Strategies

Fifteen rules-based strategies with fixed parameters: trend following,
momentum, CAN SLIM, growth, value, GARP, quality, dividend growth, mean
reversion, swing, breakout, volatility, pairs statistical arbitrage, sector
rotation, multi-factor.

They are **not fitted to data and not machine-learned.** There is no training
step and no parameter optimisation. This is a deliberate constraint — it removes
overfitting as a failure mode, at the cost of the strategies being no better
than the rules they encode.

### 2.4 Risk engine

Every order passes a fixed sequence: position sizing → stop confirmation →
portfolio checks → regime scalar → gate. Each decision, including every
refusal, is written to an audit log with its inputs.

Portfolio-level limits, all enforced by **trimming** the order to what fits
rather than refusing it outright:

| Limit | Default |
|---|---|
| Per-trade risk (entry to stop) | 1% of equity |
| Aggregate risk-at-stop, all positions | 5% |
| Single-name concentration | 15% |
| Sector concentration | 30% |
| Correlated-cluster concentration | 30% at 0.70 correlation |
| Overnight gap budget | 5% loss at a 6% gap |
| Concurrent positions | 10 |

Plus a no-leverage rule re-checked against live cash at sign-off, a kill-switch
on broker reconciliation mismatch, and daily-loss and drawdown rails.

The correlated-cluster limit is measured rather than labelled: holdings whose
returns actually track a candidate are capped together, on the basis that eight
positions at high pairwise correlation are one position taken eight times.
Sector is retained as a coarser proxy alongside it.

### 2.5 Churn control

A minimum holding period (10 trading days, with an escape if a position moves
0.5R against its stop), a time stop forcing an exit after 30 trading days, and a
weekly turnover budget. These exist because commission is a fixed $6.60 per
transaction: ten positions turned over weekly costs 6.2% of a $100k account per
year before a single losing trade.

### 2.6 Order lifecycle and execution

The invariant is that **nothing reaches the broker without sign-off**. Orders
are created as `pending_signoff` and only an explicit, operator-attributed
sign-off transmits them. In `recommend` mode that operator is a human at the
Order Blotter; in `auto` mode it is the autonomy gate, which applies its own
rails: market hours, price drift, daily P&L, kill-switch state, and per-strategy
authorisation.

Autonomous execution is confined to paper accounts by a separate flag from the
paper/live setting, so reaching live unattended trading requires a code change
rather than a configuration edit.

### 2.7 Position protection

Every entry is submitted as a **bracket** — buy, protective stop, profit target
— with the exit legs linked as an OCO so that filling one cancels the other.
Protective orders are Good-Til-Cancelled, so they survive the application
closing, the machine restarting, and the market closing.

The application then defends that protection:

- **Verification** on every reconciliation poll: asks the broker what is
  actually resting and discards any belief that is not matched.
- **Re-arm at startup**: proposes a replacement OCO for any held position the
  broker is not protecting, using the levels the position was originally sized
  against.
- **Protection sweep** every five minutes: the same repair on a timer, so
  protection lost mid-session is replaced without a restart.

Replacement levels always come from the recorded entry, never a fresh
calculation — the risk budget was spent on the original distance. A position
with no recorded stop gets nothing and is logged as unprotected, because an
invented level would be indistinguishable from a real one on screen.

*Observed in production:* on 1 August 2026 the application detected a
deliberately cancelled stop, proposed a replacement OCO, signed it off through
the autonomy gate and placed it at Alpaca — unattended, with no restart, within
one sweep interval.

### 2.8 Evidence layer

A trade ledger records closed trades with FIFO matching and per-fill cost
apportionment, separating gross P&L, costs and net P&L. Executions the broker
performs without the application's involvement — a stop or target firing — are
fetched and absorbed at their real fill prices, both so reconciliation does not
read them as discrepancies and so they are recorded as genuine closed trades.

A decision journal records what was proposed and why, including refusals,
distinct from the ledger's record of what actually happened. Daily and weekly
reports are written automatically, covering opened and held positions as well as
closed ones.

A **promotion gate** scores each strategy against an evidence bar: a minimum of
30 closed trades, positive net P&L, and floors on win rate and average R. It is
advisory during paper trading and **unconditionally enforced on a live account**,
regardless of configuration.

### 2.9 Position sizing that learns

Sizing uses fractional Kelly bounded by a volatility target and the per-trade
risk cap. The win rate and payoff ratio feeding it come from each strategy's own
closed trades once it has 20 of them; until then, documented defaults are used.
Measured values are clamped (win rate 0.25–0.75, payoff 0.5–4.0) because Kelly
reacts violently to small samples.

*This is built and inert.* With zero closed trades, every strategy currently
sizes on the defaults.

### 2.10 Backtesting and validation

A vectorised backtester with a cost model matching live economics, Monte Carlo
trade-sequence resampling, and walk-forward evaluation across non-overlapping
out-of-sample windows. A headless runner executes all of it across the watchlist
and reports.

### 2.11 AI assistance

An optional research assistant, routable per request class between a local model
(LM Studio) and Anthropic's API. It is **advisory only**: no AI output can place,
size or approve an order. Position-sensitive requests can be pinned to the local
model so that holdings never leave the machine.

---

## 3. Architecture

An in-process asynchronous event bus with typed events and independent engines
subscribing to them. Sixteen engines are registered and started in a defined
order — warm start before the feed, the autonomy gate before the order bridge —
so that no engine can observe a partially-initialised system.

Roughly 134 source modules, **1,201 automated tests**, with static type checking
and linting enforced. Safety-critical invariants have dedicated tests: no order
without sign-off, paper mode by default, no leverage, protective orders never
double-placed.

---

## 4. What it does not do

Stated plainly, because omissions matter in evaluation:

- **No ASX or non-US market support.** The data path is US-only. ASX is
  specified but blocked on the absence of a data source.
- **No live-money trading.** Paper accounts only. Unattended live trading is
  structurally prevented, not merely discouraged.
- **No machine learning in the strategies.** The HMM classifies regime; it does
  not select or size trades.
- **No parameter optimisation.** Strategy parameters are fixed by hand.
- **No portfolio optimiser.** Position sizing is per-candidate against caps,
  not a joint allocation.
- **No intraday or high-frequency operation.** The live path runs on daily bars.
- **No options, futures, FX or crypto.** Equities only.
- **No multi-account or multi-user support.**
- **No live re-configuration.** Every setting, including the risk limits, is
  restart-required: Save writes the environment file and the change takes
  effect on the next launch. This is deliberate for numbers a running risk
  engine has already sized positions against.

---

## 5. Verified behaviour

The following have been observed against a live Alpaca paper account, not
merely tested:

- Regime classification within seconds of the opening bell
- Order submission, rejection and fill through the full risk pipeline
- Bracketed entries with broker-side stop and target
- Detection of protection lost overnight, and its repair
- Standalone OCO placement accepted by Alpaca on first attempt
- Unattended detect-propose-sign-place with no human involvement
- Reconciliation adopting pre-existing holdings without false alarms
- Warm start seeding 300 daily bars across 100 symbols
- Daily and weekly report generation

---

## 6. Known limitations in current behaviour

- **`swing` rarely exits on its own signal.** Measured across 30 symbols over
  1.19 years of daily bars: 29 entries, zero signal-driven exits. In practice
  every position closes via its stop, its target, or the 30-day time stop. The
  strategy is closer to a scaled buy-and-hold than its name suggests.
- **The regime has classified `high_vol` on every occasion to date**, carrying a
  0.40 exposure scalar — so live positions are sized at 40% of nominal. Whether
  this reflects the market or a bias in the fusion has not yet been separated.
- **Backtest results for `swing` are not evidence of an edge.** Out-of-sample
  Sharpe across 115 windows: mean 0.19, median −0.05, 49.6% of windows positive,
  standard deviation 2.24. The mean is under one standard error from zero.
- **Broker-side fill absorption has not been exercised.** No protective order
  has yet fired. The code path is tested but unobserved, and Alpaca's response
  shape is the same class of assumption that proved wrong three times during
  development.

---

## 7. Maturity assessment

The **machinery is built and substantially verified**. The rails work, the
protection self-heals, the evidence layer records, and the safety invariants
hold under test and in production.

What the system lacks is **evidence about itself**. It has zero closed trades.
The promotion gate requires 30 per strategy before its verdict means anything,
and at the observed entry rate against a 30-trading-day time stop that is
approximately three to four months of continuous paper operation.

Until then:

- No strategy has demonstrated an edge in forward trading.
- Position sizing runs on default assumptions rather than measured performance.
- The promotion gate has nothing to assess.

This is the correct state for a system at this stage, and it is the reason the
current phase is data collection rather than feature development. The
appropriate evaluation question is not "does it make money" — it cannot yet
answer that — but "is it built such that the answer, when it arrives, can be
trusted". On that question the evidence is favourable: nine defects were found
and fixed during a single weekend of live operation, seven of them invisible to
a test suite because the code was behaving exactly as written against
assumptions about broker behaviour that turned out to be wrong.

---

## 8. Development posture

The project maintains a roadmap recording each milestone, what prompted it, what
was measured, and what was deliberately deferred. Defects are documented with
the reasoning that produced them, including cases where an earlier decision was
wrong and why.

The prevailing discipline is **measure before changing**: gap risk was sized
from 28,987 observed overnight holds, the concentration caps were set from
observed position sizing, and the commission floor's impact was measured at two
account scales before the cost model was corrected. Changes that alter trading
decisions are gated behind explicit approval during the data-collection phase.
