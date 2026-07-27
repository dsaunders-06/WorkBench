# Quant Advisory Terminal

An AI-assisted, multi-strategy share-trading **advisory and paper-trading**
desktop application for Windows. It detects the market regime, generates and
backtests strategy signals, enforces risk limits, integrates with Interactive
Brokers, and uses an LLM as an analyst that proposes and explains — while a
human approves every live order.

> **Educational / paper-trading software.** This project is for research and
> paper trading. Live trading is at your own risk; nothing here is investment
> advice. The default and only shipped configuration is paper trading — going
> live requires a deliberate configuration change and an in-app confirmation.
> Order execution defaults to **recommend** mode, where every order awaits an
> explicit human sign-off. Unattended execution is opt-in, confined to paper
> accounts, and granted per strategy — see "Execution mode" below.

## Status

Ten milestones are complete: architecture/config/logging/EventBus (M1),
the real-time data pipeline (M2), all 15 strategies (M3), the backtester
(M4), the regime engine (M5), the risk engine + OMS sign-off gate (M6), IBKR
integration (M7), the AI advisory service (M8 — `AnthropicEngine` +
`LocalEngine`, the router, and the input/output guards), UI wiring +
packaging (M9), and AI-provider selection + market/watchlist configuration +
the Screener (M10). All eight screens (Dashboard, Strategy Workbench, Regime
Monitor, Risk Console, AI Advisor, Order Blotter, Screener, Settings) are
wired to a real, live engine graph (`src/qat/presentation/runtime.py`)
running on synthetic/mock data by default — see "Building the Windows
executable" below to produce a standalone `.exe`.

## Setup

1. **Python 3.12** is required (this project targets 3.12 specifically for
   compatibility with the quant/ML stack). Create and activate a venv:

   ```powershell
   py -3.12 -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -e ".[dev]"
   ```

2. **Storage.** SQLite is used by default (`QAT_STORAGE_BACKEND=sqlite`,
   zero setup). To use TimescaleDB instead:

   ```bash
   docker-compose up -d timescaledb
   ```

   then set `QAT_STORAGE_BACKEND=timescale` and `QAT_DATABASE_URL` in `.env`
   (see `.env.example`).

3. **Secrets** (IBKR credentials, Anthropic API key) are read from the
   OS keyring via `qat.security`, never from plaintext config or logs. The
   Settings screen (see "Configuring the AI provider and market/watchlist"
   below) is the normal way to set the Anthropic key; `keyring.set_password("qat", "<NAME>", "<value>")`
   or the equivalent environment variable both work too, for local dev.

4. **IB Gateway / TWS**: run IB Gateway or TWS locally in **paper mode**
   (default ports 4002 Gateway / 7497 TWS). The app connects only to
   `127.0.0.1`. See "Verifying the IBKR connection yourself" below —
   `IBAdapter` is built and unit-tested against a fake client, but nothing
   in this repo can prove a real Gateway connection works end-to-end
   without you actually running one.

## Development

```powershell
invoke install   # pip install -e ".[dev]"
invoke test      # pytest
invoke lint      # ruff + black --check + mypy + bandit
invoke format    # ruff --fix + black
invoke run       # launch the desktop app
invoke package   # build an unsigned Windows executable (see below)
invoke manual    # regenerate the Word user manual
```

## User manual

`docs/Quant_Advisory_Terminal_User_Manual.docx` documents every screen and tab
for an end user. It is a **build artefact, not a hand-maintained document** —
`invoke manual` regenerates both the prose (`scripts/manual_body.py`) and the
figures, which are captured from the real widgets driven by
`Runtime.build_demo()`. That is deliberate: the first edition was produced by a
throwaway script and drifted six milestones behind the app, still describing
Screener and Settings as empty placeholders long after they shipped. Capturing
figures from the running widgets means a screen that changes shape shows up in
the manual instead of quietly diverging from it.

Regeneration needs no network, no broker and no keys, and every figure shows
demo data — nothing from a real account can leak into the document. Rerun it
after any change to a screen, and update the matching section in
`scripts/manual_body.py` in the same commit.

## Verifying the IBKR connection yourself

`IBAdapter` (`src/qat/data/broker/ib_adapter.py`) is built against `ib_async`'s
real, documented API and its own logic (reconnect backoff, heartbeat, the
live/paper safety gate, translation to/from `ib_async` types) is unit-tested
against a fake client — but no automated test here proves an actual socket
connection to a running IB Gateway works, since this dev environment has no
Gateway to connect to. To check it yourself:

1. Install and start **IB Gateway** (or TWS), log in with a **paper** account,
   and confirm its API settings allow local connections on the paper port
   (4002 for Gateway, 7497 for TWS).
2. With `QAT_TRADING_MODE=paper` and the matching `QAT_IBKR_PORT` in `.env`,
   run:

   ```python
   import asyncio
   from ib_async import IB
   from qat.config import Settings
   from qat.domain.bus import EventBus
   from qat.data.broker.ib_adapter import IBAdapter

   async def main():
       settings = Settings()
       adapter = IBAdapter(IB(), EventBus(), settings=settings, read_only=True)
       await adapter.connect()
       print(await adapter.get_market_data("AAPL"))
       await adapter.disconnect()

   asyncio.run(main())
   ```
3. Confirm you see live (delayed, if you lack a market data subscription)
   paper-account quotes rather than a connection error.

## Connecting an Alpaca paper account

Settings → Broker lets you trade against a real **Alpaca paper account**
instead of the built-in simulator: Alpaca then supplies real positions, cash
and fills, which is what makes the no-leverage rule operate on real balances.
Enter your API key and secret in Settings (stored in the OS keyring, never in
`.env`), press **Test Broker Connection** to confirm it reports your actual
cash and equity, then restart.

Two caveats worth knowing:

- **Alpaca is US equities only.** Selecting it while Market is set to ASX is a
  misconfiguration — Settings shows an inline warning and the app logs one.
- Scope is **execution and account state only**; market data still comes from
  the configured `MarketDataSource`, so `get_market_data()` on this adapter
  raises rather than pretending to be a price feed.

Reaching Alpaca's *live* endpoint needs the same two-key gate as IBKR:
`trading_mode='live'` **and** an explicit `live_trading_confirmed`, so real
money can never be one config edit away.

## Configuring the AI provider and market/watchlist

The **Settings** screen is the normal way to configure both of these — every
field on it is **restart-required**, not live-applied (the whole engine
graph is built once at startup around these values), so save your changes
and relaunch the app to pick them up.

**AI provider.** Every AI request the app makes lands in one of two
`LLMRouter` slots (`domain/ai_advisory/router.py`): *general* requests (e.g.
the regime narrative) and *position-sensitive* requests (anything that
touches your current positions — an absolute privacy override, regardless of
settings). Settings lets you choose each slot's real backing provider
independently — Anthropic, Local (LM Studio), or Demo — so you can, for
example, use Anthropic for general requests while keeping the sensitive slot
local-only. Choosing "Anthropic" for the sensitive slot shows an explicit
on-screen warning, since it means position/portfolio data leaves the machine
for Anthropic's cloud API. A misconfigured real provider (no key configured,
or a local server that isn't reachable) degrades to the canned Demo response
rather than crashing the app — check the "Test Connection" button on
Settings, or the app's log output, if a provider you selected isn't
producing real responses after a restart.

Local LLM support targets **LM Studio** by default (`http://localhost:1234/v1`)
but works with any OpenAI-compatible server, Ollama included — just point
"LM Studio base URL" at Ollama's own URL (typically `http://localhost:11434/v1`)
and set the model name to match what you've loaded. The `/v1` path segment is
appended automatically if you leave it off, and the structured-output mode is
negotiated per server (`json_schema`, falling back to `json_object`, then
plain text), since servers disagree on which they accept. Use **Test
Connection** to confirm a setup before restarting: it runs a real completion,
not just a reachability ping, so a wrong URL or an unreachable server is
caught there rather than showing up later as a request that does nothing.

**Market & watchlist.** Choose US or ASX, a category (curated / index ETFs /
mega-cap), the max number of symbols to track, and a minimum average daily
volume liquidity filter. `qat.data.universe` resolves these into the actual
watchlist the app streams and trades against (`Runtime.build_demo`); the
curated/ETF/mega-cap ticker lists are static snapshots ported from the
original ShareTrader reference app, so they'll drift from real market
composition over time — edit `watchlist_curated_us`/`watchlist_curated_asx`
in Settings (or `data/universe.py`'s tables directly) if you want them
current.

## Verifying the AI advisory service yourself

Same situation as IBKR: `AnthropicEngine` and `LocalEngine`
(`src/qat/domain/ai_advisory/llm_engine.py`) are built against the real
Anthropic SDK and LM Studio/Ollama's real OpenAI-compatible REST shape, and
their request-building/response-parsing/retry logic is unit-tested against
fakes — but nothing here proves a live call actually works, since this
environment has no Anthropic API key or running local server. To check it
yourself, either use the Settings screen (above) and restart, or drive the
engines directly:

- **Anthropic**: `keyring.set_password("qat", "ANTHROPIC_API_KEY", "<your key>")`,
  then construct `AnthropicEngine()` with no `client` argument (it builds a
  real `anthropic.Anthropic` client from that key) and call
  `await engine.complete(SYSTEM_PROMPT, "Summarise a hypothetical calm, low-vol regime.", AdvisoryRecommendation)`
  (`qat.domain.ai_advisory.prompts.SYSTEM_PROMPT`, `qat.domain.ai_advisory.schema.AdvisoryRecommendation`).
- **Local (LM Studio or Ollama)**: start a local server exposing an
  OpenAI-compatible endpoint (LM Studio's local server, or `ollama serve`)
  with a model loaded, construct `LocalEngine(model="<your model>")`
  (defaults to LM Studio's `http://localhost:1234/v1`; pass
  `base_url="http://localhost:11434/v1"` for Ollama), and call `complete(...)`
  the same way.

Confirm you get back a schema-valid `AdvisoryRecommendation`, not an error.

## Building the Windows executable

```powershell
invoke package
```

This runs PyInstaller (`--onedir --windowed`, with `--collect-all` for
`hmmlearn` and `sklearn` — both ship data files/compiled submodules that
PyInstaller's default import analysis misses) and produces
`dist/QuantAdvisoryTerminal/QuantAdvisoryTerminal.exe`, launchable standalone
without a Python install. It has been built and smoke-tested this way: the
executable starts, all engines wire up, and the window stays open with no
console attached (`--windowed`).

**This build is unsigned.** No code-signing certificate is available in this
environment, so Windows SmartScreen will warn on first run. To sign it
yourself once you have an Authenticode certificate:

```powershell
signtool.exe sign /f <path-to-your.pfx> /p <password> /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 dist\QuantAdvisoryTerminal\QuantAdvisoryTerminal.exe
```

## Architecture

Three layers, communicating only through typed events on an in-process
async `EventBus` (`src/qat/domain/bus.py`):

- **presentation/** — PySide6 views only, no trading logic.
- **domain/** — asyncio engines: orchestrator, strategies (15 modules),
  regime engine (HMM + rules + fusion), risk engine + OMS, backtester,
  AI advisory service (router + guards + LLM engines).
- **data/** — broker adapters (`BrokerAdapter` interface, `MockBroker`,
  `IBAdapter` over `ib_async`), storage (SQLite/TimescaleDB + Parquet).

Every external dependency sits behind an interface with a mock
implementation so the domain core is independently testable.

## Safety

- Default trading mode is **paper**; switching to live requires an explicit
  config flag *and* `IBAdapter`'s `live_trading_confirmed` flag, which only
  an explicit human action should ever set to `True`.
- A kill-switch (`domain/risk_engine/kill_switch.py`) trips on daily-loss,
  drawdown-from-HWM, data staleness, broker-reconciliation mismatches, an
  exhausted IBKR reconnect budget, or a manual trigger, and halts new
  orders. It's always visible and colour-coded on the Risk Console
  (`presentation/risk_console.py`), and a single click can trip or reset it.
- The Order Blotter (`presentation/blotter.py`) never calls `OMS.sign_off()`
  except from inside a confirmed modal dialog - selecting pending orders
  and clicking Sign Off always asks first. Bulk sign-off is supported, but
  the dialog itemises every order it is about to transmit, so approving a
  batch stays an informed decision; each order is still transmitted through
  the same individual `sign_off()` call.
- **The account can never be leveraged.** A buy is capped so its cost can
  never exceed available cash less a minimum reserve, and cash can never be
  fully depleted — `min_cash_reserve` is validated `> 0`, so the rule is
  adjustable but cannot be switched off. Enforced twice: once when the
  Risk Engine sizes the order, and again at sign-off against the *current*
  balance. The second check is load-bearing rather than redundant, because
  bulk sign-off can approve several individually-affordable orders that
  collectively overdraw the account; those are rejected rather than silently
  resized, since quietly changing a quantity a human just approved would
  defeat the approval. Sells are exempt — they raise cash, and refusing to
  let the account de-risk because it is short of cash would be backwards.
- **Long-only by default.** Strategies emit a directional signal on every
  tick for as long as their condition holds, so `SignalToOrderBridge`
  treats a signal as a *state* rather than an instruction: a symbol that
  already has an order awaiting sign-off, or already holds the position
  being signalled, produces no further orders. A `sell` closes an existing
  holding (sized to what is actually held, never re-sized by the entry
  sizer) and is otherwise dropped rather than opening a short. Set
  `QAT_ALLOW_SHORT_SELLING=true` to opt into shorting.
- The AI advisory layer never places, modifies or cancels an order —
  `AIAdvisoryService` has no reference to `OMS` or a broker at all — and
  its output is independently re-checked against `RiskEngine` before a
  human ever sees it endorsed, regardless of the model's own self-reported
  confidence or risk flags. Prompt-injection attempts embedded in "fetched"
  context data (e.g. a news blurb) are rendered as clearly-labelled inert
  data, never as instructions.
- No order reaches a broker except through `OMS.sign_off(...)` — `submit_order()`
  only ever creates a `pending_signoff` order. In the default **recommend**
  mode the caller of `sign_off` is always a human in the Order Blotter. See
  "Execution mode" below for the opt-in autonomous path, which goes through
  that same gate rather than around it.
- **The kill-switch's economic rails are live.** `EquityMonitor`
  (`domain/autonomy/equity_monitor.py`) polls account equity, persists
  day-start equity and a running high-water mark across restarts, and feeds
  `check_daily_loss`/`check_drawdown`. Before M13 both methods existed and were
  unit-tested but were called from nowhere in `src/` — the rails were real code
  and no part of the running system.
- **The sign-off cash check fails closed.** If no price can be determined for a
  buy — no limit price, no broker quote, no recorded submission price — the
  order is rejected rather than costed at zero. This previously failed *open*,
  which mattered because `AlpacaAdapter` raises on `get_market_data` by design,
  so on a real Alpaca account the no-leverage check passed unconditionally on
  every market buy.
- Sign-off is serialised by a lock, so several individually-affordable orders
  approved together cannot each pass a cash check against the same pre-spend
  balance.

## Market data

Settings → Market Data chooses the price source:

- **Simulated** (default) — the seeded random walk every milestone up to M13
  ran on. Kept as the default so the app and test suite work offline, with a
  standing on-screen warning: nothing observed in this mode tells you how a
  strategy behaves on real prices.
- **Real market data (Yahoo)** — live daily and intraday bars via yfinance.
  Free, unofficial, typically delayed ~15 minutes, and rate-limited. Covers
  both US and ASX.
- **Real market data (Alpaca)** — the feed belonging to your own Alpaca
  account, used for both live ticks and daily bars (M17). **US equities only**;
  selecting it with Market = ASX warns on-screen and in the log. Requires the
  same `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` keyring entries as the broker, so
  choosing Alpaca for both means one set of credentials.

Choosing Alpaca is what makes the prices the app trades on and the account it
trades into come from the same venue. With Yahoo, the two disagree slightly by
construction, and a fill price never quite matches the tick that triggered it.

Alpaca serves three feeds, selectable in Settings once Alpaca is the source:

| Feed | Latency | Coverage | Account |
|---|---|---|---|
| `iex` (default) | real time | single exchange, a small share of US consolidated volume | any, including free paper |
| `sip` | real time | full consolidated tape | paid Algo Trader Plus |
| `delayed_sip` | 15 min | full consolidated tape | free tier |

`iex` is the default because it is the only real-time option a free paper
account can actually use. It is a genuine trade print, not a synthetic price —
but it is one exchange, so thinly-traded names will show gaps that the
consolidated tape would not. Requesting `sip` without the subscription fails
outright rather than quietly degrading, which is the correct behaviour: you
find out immediately instead of trading on data you did not get.

Ticks come from the latest *trade* rather than a quote midpoint, so the price
is one that actually executed and the volume is the real trade size rather than
an invented figure.

Any real feed can return nothing without warning, so the app degrades to
simulated data with a logged warning rather than stopping — never silently. A
persistently dead feed ends the stream deliberately, which lets the staleness
detector raise `DataStaleEvent` and trip the kill-switch, rather than leaving
the app looking alive while trading on nothing.

**Ticks are aggregated into real OHLC bars** (`data/bars.py`). Up to M13 each
tick was recorded as a single-point bar with `open == high == low == close`,
which made ATR collapse to `|close - prev_close|` — a tick-to-tick delta with
no traded range in it. Since ATR sets the stop distance and the stop distance
sets the position size, that was a correctness problem at the base of the
stack, not a refinement. Quiet intervals are gap-filled with price carried
forward and **zero** volume; long gaps are treated as session breaks rather
than filled, so an overnight close does not invent a night's worth of bars.

Daily bars are deliberately never gap-filled. A live pull caught why: Yahoo
already returns one row per *trading* day, so reindexing onto a calendar
timeline turned a 251-day year of SPY into 365 rows, and the invented
zero-return days dragged realized volatility about 17% below its true value.

## What a session leaves behind

Everything needed to reconstruct a session afterwards is written to `data/`,
not held in memory. Before M20 a `recommend`-mode session left fills, an equity
curve and a report — enough to answer *"what did I make"*, nothing to answer
*"why did it do that"*.

| File | Answers |
|---|---|
| `closed_trades.csv` | what was traded and what it made |
| `equity_curve.csv` | how account value moved |
| `decision_journal.csv` | **every order decision and its reason**, in every mode |
| `risk_decisions.csv` | how the risk engine sized or refused each order |
| `daily_reports.md` / `weekly_reports.md` | the close-triggered reports, with AI analyst notes |
| `logs/qat.log` | the application log, rotating, 5 MB × 10 |

Three of those are new at M20, and each closed a real hole:

- **The log file.** `configure_logging` installed only a `StreamHandler` on
  stdout, and the packaged build is `--windowed` — no console. Every line was
  discarded in the build actually shipped: session transitions, degraded-feed
  warnings, staleness, kill-switch trips, sign-off rejections. The logging was
  never the problem; nothing was reading it. Logging is now also configured
  *before* the runtime is built, so the broker and data-source resolution
  warnings — the ones most worth having — are no longer emitted into the void.
- **The decision journal**, formerly the autonomy journal, was written only by
  the autonomous executor. `recommend` is the default and the mode anyone runs
  first, so the file stayed empty exactly when it mattered. The OMS now records
  every proposal, sign-off and rejection with its reason and the operator.
- **The risk audit trail** lived in a list and died with the process, so "why
  was that order sized at 12 shares, and why was the next refused" lasted only
  as long as the session that raised the question.

**Export Session** on the Performance screen zips the lot, plus a manifest, into
`data/exports/`. It copies rather than moves — the running session keeps
writing.

Secrets are redacted on both handlers. A key must not reach the console, and
certainly not a file that outlives the process.

## Trading session and market hours

The Dashboard's top panel shows which market is in play, a `HH:MM:SS` countdown
to the next open or to the close, and whether the trading session is actually
running. The countdown turns amber inside **30 minutes** of an open or a close.
Holidays and early closes come from the same calendar the report scheduler and
the autonomy gate use, so a Friday closure reads "US closed - public holiday"
rather than an unexplained "closed".

`SessionController` stands the market data feed and strategy-signal emission
down at the close and brings them back at the open. Up to M18 both ran around
the clock, which was harmless on synthetic prices and two real faults once the
data became real:

- the feed polled a rate-limited vendor all night, and the strategy engine kept
  emitting signals computed from the previous day's closing price;
- **the staleness rail tripped the kill-switch every single night** — a closed
  market means every symbol stops updating, and the default staleness window is
  sixty seconds. You would arrive to a tripped rail with nothing wrong.

Tick history keeps accumulating while suspended, so the first signal after an
open is computed against a warm buffer rather than an empty one.

**It controls when the app is awake, never who approves an order.** Execution
mode, the risk engine, the cash rule and the sign-off gate are untouched.
Standing a session up does not place a trade.

Two escape hatches: **Start session now** on the Dashboard runs the session
against a closed market until the next close (deliberately not permanent — the
app never acquires a standing exemption from its own schedule), and the gate is
inert on simulated prices, which have no trading hours. Backtesting, the
Screener and the Blotter work regardless.

## Walk-forward analysis

The Workbench's Walk-Forward panel replays a strategy across rolling,
non-overlapping out-of-sample windows and reports a per-window table plus a
headline. `walk_forward.py` had existed since M4 and was reachable from nowhere
until M19, which left a single in-sample backtest and a bootstrap as the whole
evidence base for deploying a strategy — and both are computed from one pass
over one period.

The headline leads with **how many windows were profitable**, not the mean
Sharpe, because a strategy can post a strong average off one exceptional window
and lose money in every other, and the average is exactly what hides that. It
also flags when the spread between windows exceeds the average, and says so
plainly below three windows rather than scoring noise.

## Company fundamentals

Settings → Market Data → Company fundamentals chooses between the seeded
generator and real reported figures from Yahoo. Simulated is still the
default, so the app stays offline out of the box.

This matters more than it sounds. **Nine of the fifteen strategies select on
fundamentals** — value, quality, GARP, growth, CAN SLIM, dividend growth,
multi-factor, and sector rotation via its sector map. On the simulated source
every one of the sixteen figures is invented for every symbol, so those
strategies were picking stocks on numbers with no connection to the companies.

### Missing is a value

A real vendor cannot answer every field for every symbol, and that is usually
correct rather than a failure: an index ETF has no return on equity, and some
listings publish no PEG. Every numeric field on `FundamentalSnapshot` is
therefore `float | None`, and **a strategy that needs a missing field abstains
on that symbol** rather than scoring it (`strategies/base.py::unavailable`).

The alternative — substituting zero or a universe median — was rejected
deliberately. A real company silently out-ranked by a placeholder is
indistinguishable afterwards from one out-ranked on merit.

Measured on the shipped watchlist: SPY produced fundamentals-driven buy signals
under **8 of 12** mock seeds. On real data it produces none, at any threshold,
because the fields do not exist. Live coverage for comparison — AAPL 14/15
fields, MSFT 14/15, BHP.AX 13/15 (no PEG), SPY 4/15.

**Expect noticeably fewer signals on real fundamentals.** That is the feature.

### Units are converted at the boundary

Two of Yahoo's fields are percent-scaled where this codebase uses fractions,
and both were verified against the live API rather than assumed:

| Field | Vendor returns | Means | Unconverted consequence |
|---|---|---|---|
| `dividendYield` | `0.95` | 0.95% | Screener renders "95.00%" |
| `debtToEquity` | `30.271` | 0.30 | GARP's 1.5 leverage cap rejects every real company |

Both have named regression tests. A unit error here throws nothing and changes
no types — every figure stays numeric and every comparison still runs — so it
is only catchable by asserting a converted value against a known input.

Four fields have no vendor equivalent and are derived: ROIC as NOPAT over debt
plus equity less cash, EV/EBIT from the statements, EPS acceleration from three
years of EPS, and the dividend streak from the dividend history (excluding the
in-progress year, which would otherwise break every streak each January).

`relative_strength_rank` is not a company property at all but a percentile
against the universe, so it is computed from price history
(`data/relative_strength.py`). Below ten comparable symbols it returns nothing
rather than a confident "100" that means "best of three".

Results are cached to `data/fundamentals_cache.json` for
`QAT_FUNDAMENTALS_CACHE_DAYS` (default 7 — fundamentals move quarterly). The
cache is an optimisation and never a source of truth: a missing, unreadable,
corrupt or stale-schema entry degrades to a refetch. Synthetic snapshots are
never written to it.

Fundamentals are fetched once per symbol per session and cached across
restarts, so real data costs a handful of requests, not one per tick.

## Position protection

Every position now has a way out. Before M14 `SwingStrategy` emitted buy-only
and no protective stop was ever placed at a broker, so a position it opened had
no exit path short of a human noticing.

- **A bracket rests at the broker.** A strategy's proposed stop and target are
  submitted with the entry as one bracket order, so the protection outlives
  this process. A stop held only in memory disappears the moment the app does,
  which is exactly the wrong property for something meant to run unattended.
- **Sizing and the bracket use the same stop.** When a strategy supplies a
  stop, `RiskEngine` sizes from that distance instead of its own ATR multiple.
  Sizing against one stop while resting a different one would make the
  per-trade risk limit describe a trade nobody placed.
- **Strategies can see positions** (`FeatureSnapshot.positions`) and emit
  exits. `SwingStrategy` sells on the EMA20/EMA50 crossover breaking, checked
  on the bare crossover with no minimum-gap buffer — the buffer that filters
  weak *entries* would only delay a needed exit, and being quick to protect is
  the safer error.

## Portfolio limits

`PortfolioRiskChecker` covers ES, single-name and sector concentration.
`PortfolioGovernor` (`domain/risk_engine/governor.py`) adds the three the
reference implementation only added after they bit:

- **Aggregate risk-at-stop** (`max_aggregate_risk_at_stop_pct`, default 5%) —
  the total loss if every open position hit its stop at once. A per-trade limit
  bounds one trade and says nothing about ten trades each within budget. With
  the 1% per-trade default this allows five full-size positions.
- **Max concurrent positions** (default 10) — a plain count.
- **Pending orders count as committed exposure.** The subtle one: a governor
  that only looks at *filled* positions approves a tenth candidate while nine
  sit in the blotter. That is precisely how eight setups passed a six-position
  cap in the original.

A candidate over the cap is **trimmed to the remaining headroom** rather than
rejected outright, and only rejected when there is not a whole share of room
left. OMS supplies the portfolio state itself, so no caller can bypass a cap by
omitting an argument — the same reasoning as the cash check.

**Every buy now carries a broker-side stop.** If the strategy proposes one it
is used; otherwise the ATR stop the sizer already computed is attached as the
bracket. Previously an order from a strategy with no stop reached the broker
naked, and to the governor counted its *entire value* as at risk — correctly,
since nothing was protecting it. Attaching the sizing stop makes the position
protected and the risk arithmetic honest at once. A position with genuinely
unknown protection (an adopted one) still counts full value: unknown protection
is treated as no protection.

**De-levering** (`domain/risk_engine/delever.py`) is the active half — the
governor only blocks *new* risk, which unwinds a breach passively as stops hit.
It trims every position by the same proportion, targeting slightly under the
cap so ordinary price movement does not immediately re-trigger it. **Off by
default** (`delever_sweep_enabled`): it sells, and a rail that sells uninvited
is a larger delegation than one that declines to buy. Disabled, a breach is
still measured, logged and blocking. Its trims go through `submit_exit_order`
like any other order, so the sweep decides *what* to trim, never whether it
transmits.

## Broker reconciliation

`OMS.check_reconciliation` existed since M6 and, like the equity rails before
M13, was called from nowhere in `src/`. `ReconciliationMonitor` runs it.

At startup it **adopts** whatever the account already holds as the baseline.
Without that, an OMS that has filled nothing compared against an Alpaca paper
account carrying positions from a previous session reports a mismatch on the
first poll and trips the kill-switch on every launch — training an operator to
ignore the one signal meaning "my view of this account cannot be trusted".
Adoption is explicit and logged, because silently absorbing an unexpected
position is exactly the event reconciliation exists to catch.

Adopted positions carry **no stop** in this app's records: it did not open them
and does not know what protects them.

## Performance and promotion

The **Performance** tab is the only screen that answers whether any of this
worked. Everything else shows what the system is doing or intends to do.

`TradeLedger` (`domain/performance/trades.py`) matches fills FIFO per symbol
into closed round-trips. FIFO rather than average-cost because average-cost
collapses five entries and five exits into one blended number, destroying the
per-trade distribution the promotion gate needs. Each trade carries its
**R-multiple** — profit over the risk originally taken to the stop — because a
$500 win risking $100 and a $500 win risking $2,000 are not the same result.

Results are attributed to the strategy that **opened** the position. A stop
sweep or a delever trim closes a position it did not open, and crediting the
closer would attribute the outcome to the wrong strategy.

Metrics return **None rather than a placeholder** when the sample is too thin:
a Sharpe from three trades is not a rough Sharpe, it is noise wearing a
number's clothes, and a gate that accepts it will promote noise. Profit factor
is None rather than infinite without a loss; a strategy with no losses yet has
simply not had one.

### The promotion gate

`autonomous_strategies` was previously a free-text list — a statement of intent
with no evidence behind it. `StrategyScorecard` makes "fine tuned" falsifiable.
A strategy is eligible only when it clears every criterion on **realised**
trades:

| Criterion | Default |
|---|---|
| Sample size | 30 closed trades |
| Profitable | net P&L > 0 |
| Average R | ≥ +0.20R |
| Win rate | ≥ 40% |
| Worst trade | loss ≤ 3× the average win |

The last one exists because a good average hides a single catastrophic trade.

Four states are reported, because *promoted* and *eligible* are independent and
the disagreements are the interesting cases: `promoted`, `eligible`,
`not-eligible`, and — the row that matters most — **`promoted-below-bar`**, a
strategy trading unattended on a record that no longer supports it.

The gate **advises by default**. You can promote a strategy it has not cleared;
the scorecard shows you doing it. Setting `QAT_ENFORCE_PROMOTION_EVIDENCE=true`
makes it binding, so a strategy that degrades stops trading unattended without
anyone having to notice and edit a setting. It ships off only because a fresh
install has no history and would otherwise block everything for a reason that
looks like a bug.

Evidence is necessary but never sufficient: a strategy the operator never
promoted does not start trading because its numbers look good.

### Reports

`PerformanceReporter` writes a daily report after each market close and a
weekly one after the week's **last trading day** — asked of the calendar, not
assumed to be Friday, so a Friday holiday moves it to Thursday rather than
skipping the week. State is on disk, so a restart mid-evening does not produce
a second copy.

Reports count **blocked** autonomy decisions alongside trades. A day with no
trades because nothing qualified and a day with no trades because a rail
stopped eleven candidates are different states of the world.

Figures are computed in code and handed to the model as established fact for
narration only. A narrative failure costs the commentary, never the report.

## Execution mode

Settings → Execution Mode chooses how orders are approved:

- **Recommend** (default) — every order waits in the Order Blotter for your
  sign-off, carrying the reasoning behind it. This is the only behaviour the
  app had before M13.
- **Auto-trade** — `AutonomousExecutor` may sign off qualifying orders with no
  per-order confirmation.

Switching to auto-trade requires a separate confirmation dialog, not just
changing the dropdown, and the current state is shown in an always-visible
banner with three distinct readings: recommend, auto-trade active, and
halted-with-a-reason.

An order is auto-signed only if **all** of these hold, and a buy faces every one:

| Gate | Buy | Sell |
|---|---|---|
| Execution mode is `auto` | yes | yes |
| Paper account (live needs a second flag with no UI) | yes | yes |
| Kill-switch not tripped | yes | yes |
| Market open (holidays and early closes included) | yes | yes |
| Session phase eligible (not the opening or midday windows) | yes | **no** |
| Strategy on the promoted list | yes | **no** |
| Day P&L above the pause threshold | yes | **no** |
| Price drift within tolerance | yes | **no** |
| No-leverage cash re-check at sign-off | yes | n/a |

Sells are deliberately exempt from the appetite gates: a rail whose effect is
"the account may not de-risk" is a broken rail. Only the full-halt conditions
(kill-switch, closed market) stop a protective exit.

Autonomy is granted **per strategy** via `QAT_AUTONOMOUS_STRATEGIES`, which
ships empty. A strategy that is not listed still produces recommendations for
sign-off, so promoting one is a deliberate act per strategy rather than a
single switch that clears all fifteen at once.

Every decision — taken *and* blocked — is appended to
`data/autonomy_journal.csv` with the reason, the market and session phase,
the account state at the time, and the strategy responsible. The blocked rows
are the point: a journal of only what fired cannot distinguish a day with no
setups from a day when the rails stopped everything.

No LLM sits anywhere in this path. The gate is arithmetic and clock checks.
This is deliberate — in the reference implementation a model asked to confirm
sell signals declined 100% of 494 of them in a single day, which turns
"be cautious" into a portfolio that can only ever grow.

## Macro market analysis

The Regime Monitor's macro panel is two independent halves:

- **The deterministic read** (`domain/macro_analysis/signal.py`) — realized
  volatility, position against the 50-bar trend, and drawdown from a recent
  high, computed from the benchmark's own bars. Pure arithmetic, always
  available, identical for identical input.
- **The AI synthesis on top of it** — the numbers are handed to the model as
  established facts it is told not to recompute, and its job is what a formula
  cannot do. It may reach a different conclusion than the deterministic read;
  that disagreement is shown rather than reconciled away.

Any exposure scalar the model returns is a **proposal**. Nothing applies it —
the panel displays it and you decide. `RiskEngine.regime_scalar` stays owned by
the HMM regime engine, so the applied exposure always has one attributable
source.
