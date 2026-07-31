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

## Which build am I running?

The Settings tab opens with a read-only **This Build** panel, and the same
line is written to the session log at startup:

```
Build: M27a (db4a8e3, built 2026-07-30 22:17 UTC, packaged)
```

Four facts, deliberately shown together rather than one version string. The
install ran M26 while the repository was four milestones ahead, and nothing in
the running application could have told you so. `pyproject`'s `0.1.0` would not
have helped either — it has never been bumped, so it reads identically on every
build ever made.

- **Version** — `qat.version.MILESTONE`, bumped by hand when a milestone ships.
  The only part that can go stale, and it goes stale *visibly*, because the
  commit and build date beside it disagree with it.
- **Commit** — `git describe --tags --always --dirty`. There are no release
  tags today so this is the short SHA; starting to tag upgrades the display
  without a code change. A `-dirty` suffix means the build came from a working
  tree with uncommitted changes and cannot be reproduced from the commit it
  names — the panel says so in amber.
- **Built** — when it was packaged, which catches an old executable carrying a
  correct label.
- **Running from** — `packaged` or `source checkout`, so the two can never be
  mistaken for each other.

A frozen application has no git and no repository, so `invoke package` captures
this into a generated `src/qat/_build_stamp.py` before freezing and deletes it
afterwards. It is a Python module rather than a data file so PyInstaller's
import analysis collects it without an `--add-data` entry that could silently
drift out of step. Its life is that one build: left behind, the next run from
source would report itself as a packaged build of whatever commit was last
frozen.

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
  Every trip and reset is logged and pushed to registered listeners
  (`KillSwitch.add_listener`), which is how the main window's execution
  banner stays truthful. Until M24 it did not: `trip()` wrote no log line at
  all, and three paths - the staleness detector, the Risk Console button, and
  every direct `trip()` call - changed the state without announcing it, so a
  halted session went on displaying **AUTO-TRADE ACTIVE** and a reset session
  went on displaying **EXECUTION HALTED**. Notification travels by callback
  rather than by bus event for two reasons: it fires on every path
  structurally, so the next trip site added cannot be silent by omission, and
  it needs no running event loop, where an async publish from a Qt slot does.
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

## Where settings and records live

Everything the application owns sits in one per-user directory:

```
%LOCALAPPDATA%\QuantAdvisoryTerminal\
  .env          settings written by the Settings screen
  data\         trade ledger, equity curve, journals, reports, logs, exports
```

Settings names the location on screen, so it is never a guess. `QAT_HOME`
relocates the lot — that is what the test suite uses, and what a portable
install would set.

Before M22 both paths were resolved **relative to the process working
directory**: `env_file=".env"` and `data_dir="./data"`. Run from a checkout
that meant the repository; run from the packaged build it meant wherever the
zip was unpacked. Three consequences, each found the hard way:

- the same installation read a different configuration depending on how it was
  started, and neither copy was discoverable from the other;
- every new build shipped as a fresh folder started with no settings, and the
  previous ones were stranded where they lay;
- an edit to the checkout's `.env` had no effect on the packaged app actually
  running — and looked, from outside, like it had worked.

On first launch a legacy `.env` and `data/` in the working directory are
brought across. Three rules govern it:

**Copy, never move.** This runs automatically without asking, and the source
may be your repository. Removing a file the operator did not know was about to
be touched is data loss with a helpful name. The originals stay put.

**Never overwrite.** If the destination already has the file, that is the live
copy and the legacy one is a stray. Migration must not be able to make a first
run worse than no migration.

**Say what happened.** A silent migration and a silent no-op look identical
from outside, which is the exact failure this replaces. The result is logged
and the count appears in the log at startup.

## Account balances on the Dashboard

The Dashboard leads with a Balances panel laid out like the broker's own page:
portfolio value, today's P/L, cash, buying power, long and short market value,
initial and maintenance margin, day-trade count and account status.

Two rules govern it.

**Nothing is recomputed that the broker already reports.** Today's P/L is
Alpaca's `equity` against its own `last_equity`, not a figure derived here.
When two screens disagree about money you have to work out which is lying, and
that is worse than one number with a caveat.

**A figure the broker did not report renders as a dash, never zero.** An Alpaca
paper account returns nothing for `daytrade_count`, `pattern_day_trader` or
`daytrading_buying_power`; "0 day trades" would be a quiet claim about PDT
status. Note that `account()` still coerces to a concrete float — a buy must
never proceed on an unknown balance, so `0.0` is right there and `None` is not.

### Spendable here vs buying power

The one figure on the panel that is *not* the broker's is **Spendable here** —
`cash − min_cash_reserve`, what the no-leverage rule will actually allow a buy
to spend. On a live paper account that reads:

| | |
|---|---|
| Broker buying power | $365,206.54 (4x) |
| **Spendable here** | **$69,844.06** |

Alpaca offers four times cash on margin; this application uses none of it.
Seeing six figures of buying power beside an order refused for insufficient
cash is the most confusing thing about running the two side by side, so both
appear together.

### Rate limits

Alpaca documents a per-account limit, read straight off the response header:

```
X-Ratelimit-Limit: 200
```

The Dashboard's two-second timer was calling `account()` **and** `positions()`
on every tick — **60 requests a minute, permanently, to repaint one tile**,
before the market data feed, equity monitor and reconciliation asked for
anything.

`AccountPoller` replaces that: one throttled fetch shared by every screen,
`QAT_ACCOUNT_POLL_SECONDS` (default 5s). Account, balances and positions
together now cost about **12 requests a minute** — cheaper than what it
replaced, despite showing far more.

On a broker failure the last good reading keeps displaying with its **real**
timestamp and the error beside it. Blanking the panel would be its own lie —
the money did not disappear — but a stale number presented as current is the
thing that must not happen, so the age is always shown.

## Judging a strategy: the metrics panel

The Performance screen's **Metrics** tab reports what a strategy *is*, where the
trade list only reports what it did. Each row carries a one-line explanation of
what it tells you, because the panel exists to support a promotion decision
rather than to display numbers.

**Expectancy leads.** `PerformanceStats` had carried expectancy, average win,
average loss and best/worst since M16, and `summary_line()` dropped every one —
so the single most decision-relevant figure a trading system has, expected
dollars per trade, was computed on every refresh and discarded. Win rate alone
is not merely incomplete but misleading: 80% winners at a negative expectancy is
a losing system that feels like a winning one.

Added at M23, all derived from data already on disk:

| Metric | Why it earns its place |
|---|---|
| **Holding period** | The rails are session-phase aware and the daily-loss rail resets each morning. A strategy holding hours meets them constantly; one holding weeks barely notices. Nothing else tells you which is running. |
| **Exposure** (avg and peak) | The missing denominator under every return figure: 2% on 10% deployed is not 2% on 95%. Also the direct read on whether the no-leverage cash rule is throttling the strategy. |
| **Recovery factor** | Net profit against the drawdown that produced it. Preferred to Calmar on short samples because it does not annualise — a fortnight annualised is a number with no meaning. |
| **Trades / week** | Turnover over the period actually traded. During testing it is the read on whether the system is doing anything, which the M18 abstention rules made a real question. |
| **Avg win / avg loss** | The promotion gate already judges on this ratio; until M23 you could not see what it was judging. |

Two rules hold throughout. Every metric returns `None` below
`MIN_TRADES_FOR_STATS` and renders as a dash — a figure from three trades is
noise with a decimal point. And **a dash is never a zero**: "not enough trades
to say" and "measured, and it is zero" are different claims.

Rates carry a second floor. `MIN_SPAN_DAYS_FOR_RATE` requires a day of elapsed
history before a weekly rate is reported, because eight trades closed seconds
apart divide out to hundreds of millions per week — which is exactly what the
first implementation printed before the floor was added.

The same figures appear in the daily and weekly reports, so the post-close
review reads what the screen reads.

**Deliberately not built yet:** skewness and kurtosis need hundreds of
observations before the estimate stops moving, and at paper-test trade counts
they would be noise carrying four significant figures. Ulcer index is a better
drawdown measure than max drawdown, but recovery factor covers most of the same
ground for less. Neither belongs in a first tranche.

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

## Trading costs (M27)

IBKR charges a **minimum of $6 per transaction**, so a round trip costs at least
$12 before the market moves. Three things were wrong before M27, and the third
was the worst.

`CostModel` was purely proportional, so it could not express a floor at all: at
5bps a $20,000 trade modelled as $10 and a $2,000 trade as $1, against a real
$6. The error was largest exactly where it matters, because a fixed fee is
trivial on a large position and ruinous on a small one.

Costs existed **only in the backtester**. The risk engine, sizer, OMS and
autonomous executor had no cost awareness at all, so nothing would have stopped
the system taking a trade whose entire expected profit was fees.

And `ClosedTrade.pnl` was `(exit - entry) x quantity` with no fee term, so every
performance metric - expectancy, average R, profit factor - and the promotion
gate that consumes them were computed **gross**. Fixed in M28, below.

**The rail** lives in `RiskEngine.evaluate_order`, so it is audited like every
other decision, and it runs *last* - the cash cap and the governor both shrink
orders, and a trade worth its fees at full size may not be after being trimmed.

It measures cost against **risk, not notional**. Every order has a stop so 1R is
always known, where a profit target is optional strategy metadata; and the ratio
scales the right way. Measured with the shipped defaults:

| Stop width | Notional per $1,000 risk | Round trip | Cost as % of risk |
|---|---|---|---|
| 1% | $100,000 | $200 | **20.0%** |
| 2% | $50,000 | $100 | 10.0% |
| 5% | $20,000 | $40 | 4.0% |
| 8% | $12,500 | $25 | 2.5% |

The default limit is **10%**, chosen from that table rather than from taste. A
5%-wide swing stop - the profile these settings target - spends about 4% of its
risk on costs and clears comfortably. A 1%-wide stop spends 20% and is refused:
against a 0.2R promotion floor, costs at that level consume the entire edge. The
first draft used 2% and rejected 74 existing tests, which was the calibration
telling me the number was wrong, not the tests.

Costs apply **in paper too** (`apply_costs_in_paper`, default on). Alpaca charges
nothing, so a commission-free measurement would promote a strategy onto a broker
where the same trades lose money. Exits are never gated by cost: refusing to
close a position because it is expensive is the same error as refusing to
de-risk.

**Why frequency matters**, with ten concurrent positions at $12 a round trip:

| Average hold | Round trips/yr | Annual cost | % of a $100k account |
|---|---|---|---|
| 1 week | 520 | $6,240 | 6.2% |
| 2 weeks | 260 | $3,120 | 3.1% |
| 4 weeks | 130 | $1,560 | 1.6% |

### ASX pricing (IBKR Australia, inclusive of GST)

Live trading starts on **ASX**, so `CostModel.from_settings` is market-aware:
`MARKET_COST_PROFILES` is keyed on `(market, ibkr_pricing_model)` and an
explicitly-set `commission_bps` or `broker_min_commission` always wins, so a
deliberate override is never silently replaced by a published schedule.

| | Fixed | Tiered, Tier I |
|---|---|---|
| Rate | 0.088% of trade value | 0.088% |
| Minimum per order | AUD 6.60 | AUD 5.50 |
| Exchange + clearing | **None** | passed through (~0.454bps) |

Verified against IBKR's own worked example: 400 shares at AUD 50 is a trade
value of AUD 20,000, and the model returns **AUD 17.60** inclusive, **AUD
16.00** exclusive - both as published. Reproducing both confirms the basis, not
just the multiplication.

**Fixed is the right choice at Tier I.** The rates are identical, so below
about AUD 7,130 a trade Tiered is cheaper on its lower floor - by at most about
AUD 1.10 - and above it both pay 0.088% while only Tiered adds pass-through
fees, so Fixed wins by a margin that *grows* with trade size. Trade values are
expected to grow.

**The floor binds below AUD 7,500** (6.60 / 0.088%). This corrects something I
said earlier: cost-to-risk improves as position size grows only *up to* that
point. Above it the charge is proportional and the ratio goes flat, so scaling
up is a cost lever with a ceiling rather than an open-ended one.

Third-party fees are modelled at the **ASX venue** rate (exchange 0.00001815 +
clearing 0.000027225 = 0.454bps). Cboe Australia is slightly cheaper at
0.417bps and SmartRouting picks the venue, not us, so the more expensive of the
two is the conservative default. Auction trades carry a higher exchange fee
(~0.61bps all-in) and are not separately modelled, so an auction-heavy strategy
is understated by roughly 0.16bps a side.

`third_party_bps` is deliberately separate from the commission rate, because
the per-order minimum applies to the **commission only**. Folding pass-through
fees into the rate would let the floor swallow them on small orders -
understating exactly the trades where every dollar is a large share of the risk.

**No US profile exists yet**, so US trading falls back to the configured
defaults rather than quietly charging Australian rates.

### Still open



Live trading starts on **ASX**, with US as a later option, and IBKR prices the
two differently - so the flat `broker_min_commission` shipped in M27 is a
placeholder that conflates them. The replacement is a `CostProfile` per market,
selected by the existing `market: Literal["US", "ASX"]` setting.

**No currency handling exists.** `Position` and `AccountSummary` carry a
currency and `to_ib_contract` defaults to USD, but nothing reconciles them:
`min_cash_reserve`, `per_trade_risk_pct` and every dollar figure in the risk
engine are unit-less. Single-market trading hides this; extending from an
AUD-denominated ASX account into US positions would mix currencies inside the
risk arithmetic without complaint. Cheaper to introduce alongside the market
profiles than afterwards.

**Not yet built**, and deliberately listed rather than quietly dropped: the
minimum holding period for signal-driven exits (agreed at 10 trading days,
configurable, never delaying a protective exit); and a turnover budget on
`trades_per_week`. Fees on `ClosedTrade` landed in M28, below.

## Cost-truthful measurement (M28)

Every performance figure this application reports is now **net**. Expectancy,
average R, profit factor, win rate, best and worst trade, and the promotion
gate that reads them: all of it after costs.

Each `ClosedTrade` carries `entry_cost` and `exit_cost` and reports `gross_pnl`,
`costs` and `net_pnl` separately, so the charge is a number you can act on
rather than an adjustment applied out of sight. What it looks like at the
shipped defaults, on a 2% gain against a 5%-wide stop:

| Notional | Gross | Costs | Net | Gross R | Net R |
|---|---|---|---|---|---|
| $2,000 | $40.00 | $15.22 | $24.78 | 0.40 | **0.25** |
| $10,000 | $200.00 | $23.30 | $176.70 | 0.40 | 0.35 |
| $20,000 | $400.00 | $40.40 | $359.60 | 0.40 | **0.36** |
| $50,000 | $1,000.00 | $101.00 | $899.00 | 0.40 | 0.36 |

The per-order floor is what makes the small trade bleed — the same error the
M27 cost model was built to express, now visible in the results as well as in
the rail. Against a 0.2R promotion floor, the gap between 0.40R and 0.25R
decides whether a strategy qualifies.

**There is deliberately no `pnl` attribute any more.** Redefining it to mean
net would have silently changed every existing call site, which is the failure
this codebase keeps finding — a name that no longer means what it says. Callers
must now write `gross_pnl` or `net_pnl` and mean it, and the compiler-equivalent
(a failing test at every site) forced each one to be reviewed.

**A stop-out costs more than 1R.** A trade closed at exactly its stop loses the
1R of price movement plus the cost of having been in the trade at all. A system
sized on the assumption that a stop costs exactly 1R understates every loss it
takes.

**The commission floor is charged once per order, not once per closed trade.**
A position closed in three pieces pays one entry commission, apportioned across
the three by quantity; a single sell closing several lots has its cost split the
same way. Charging the floor per trade would have invented fees that were never
billed — which, for a system whose whole purpose here is honest measurement,
would have been its own kind of lie.

**The backtester had the same defect in reverse**, found while doing this work:
it deducted costs from equity but recorded gross P&L on each trade, so the same
backtest reported a net CAGR beside a gross profit factor and win rate. Both
sides now agree.

**These are modelled costs, not billed ones.** A paper broker charges nothing,
so measuring the paper account's own fees would report zero and promote a
strategy onto a broker where the same trades lose money. Real per-fill
commissions from a live broker are not read back yet — that is a separate
wiring job, and until it exists the figures are as good as the model.

## The regime gate reads the distribution (M27b)

A strategy trades when at least `regime_eligibility_mass` (default 50%) of the
regime probability distribution lies inside its suitable regimes — not when the
single winning label happens to be one of them.

On 30 July the engine published `high_vol=0.31, bull=0.29, recovery=0.20`.
Swing trades bull and recovery and not high_vol, so **0.49 of the mass sat
where it could trade against 0.31 where it could not**, and a 0.02 gap between
the top two labels kept it out of the market for the whole session. The model
had already computed its confidence; collapsing to the argmax and then testing
set membership threw it away.

**In aggregate this changes very little, which is the honest result.** Over the
same 300 sessions swing goes from 57.3% eligible to 58.1%, and trend-following
from 42.7% to 41.9% — it moves in both directions. The top-two margin is under
5 points on only 6.2% of sessions, because the hysteresis gate already smooths
the label. This is a correctness fix for the coin-flip case, not a way to trade
more. 30 July was one of the 6%.

One property worth stating: with seven regimes and a flat distribution, a
four-regime strategy sits at 0.57 and trades while a one-regime strategy sits
at 0.14 and does not. When the classifier knows nothing, breadth of mandate
decides rather than an arbitrary argmax.

Eligibility changes are logged with the numbers behind them — a strategy
silently ineligible for a session used to look exactly like one that found no
setup, and that ambiguity cost four sessions.

## Autonomy must be earned on live money (M29)

`enforce_promotion_evidence` shipped `False`, so the policy said "earn
autonomy" and the code granted it anyway. Turning it on during the paper phase
would have been circular: the bar is 30 closed trades, paper is where those
trades come from, and enforcing it there means nothing trades, so no evidence
is produced, so the bar is never met.

Enforcement is now bound to what is at stake rather than to a flag anyone has
to remember. `Settings.promotion_evidence_enforced` is true on **any live
account**, whatever the flag says. Paper collects the evidence; live requires
it. An operator can opt in early on paper; nobody can opt out on live.

This had to follow M28 — before it, the gate would have enforced a bar computed
on gross figures already known to be optimistic.

## Market data resilience

The first unattended session produced no trades, and none of the reasons were
the ones being tested. `BRK-B` sat in the watchlist - Yahoo Finance's spelling
of `BRK.B`. Alpaca fails a multi-symbol request **whole**, so one unknown
ticker among a hundred returned HTTP 400 and no prices for any of them, every
minute. Five empty polls later the feed shut itself down, permanently, and the
session ran **6h17m of an open market with no market data at all** while the
execution banner read AUTO-TRADE ACTIVE.

Nothing downstream was broken. The strategies, risk engine and execution path
were healthy and were never handed a price. Four separate things had to be
wrong at once for that to be invisible, and all four are now fixed:

- **One canonical symbol, translated per vendor** (`data/symbols.py`). Canonical
  is the *broker's* form, because positions, fills and reconciliation all speak
  it - a symbol that round-trips wrongly against the broker is a reconciliation
  mismatch and a halted session, which beats a missing fundamentals lookup.
  yfinance gets `to_yfinance()` at its own boundary. The watchlist, sector map
  and instrument-name map are asserted to agree; renaming the watchlist alone
  missed the third one and only a test caught it.
- **One bad ticker can no longer mute the feed.** `_prune_unknown()` probes the
  batch once at stream start and, if it fails, bisects to isolate the offenders,
  drops them and names them at ERROR. The healthy path costs exactly one extra
  request. If *every* symbol fails that is an outage or a bad key, not a hundred
  simultaneous delistings, so the watchlist is kept intact rather than emptied.
- **A dead feed retries instead of ending.** Terminating the stream was the M17
  design, on the reasoning that a dead feed must not look alive. It made a
  transient outage permanent for the session, and the staleness rail it delegated
  to could never fire (below). It now backs off exponentially to a five-minute
  ceiling and announces its own recovery.
- **Feed health is reported at the feed, not per symbol.** `DataStaleEvent` reads
  `_last_seen`, which a symbol only enters *after* its first tick - so a source
  that failed from the very first poll left the map empty, every symbol was
  skipped, and no staleness and no halt ever followed. `MarketDataFeedEvent`
  is about the feed itself and so can be raised on exactly that case. The main
  window shows **MARKET DATA DOWN** in amber; a kill-switch halt still outranks
  it, because a halt is a decision needing a human and an outage is a condition
  that may clear.

Feed death deliberately does **not** trip the kill-switch. No ticks means no
feature snapshots, so no signals and no orders - the danger is not that it
trades wrongly but that nobody notices it stopped. The answer to that is to say
so, not to demand a manual reset for an outage that may fix itself.

Known asymmetry: `YFinanceMarketDataSource` still ends its stream after
repeated failures. It is not the configured source here, and the feed-level
health check now makes that visible wherever it happens, but the retry
behaviour has not been brought across.

## Performance history survives a restart

`EquityCurve` wrote every sample to CSV and never read one back, so `points()`
held only the current process's history. The first session was restarted
mid-morning, after the account had gone flat, and the daily report announced
the day as `100,660.56 -> 100,660.56, +0.00%, average exposure 0.0%`. The real
day ran `100,462.97 -> 100,660.56` at 17.26% average and 30.67% peak exposure.
Nothing miscalculated - the report could not see the morning. The curve now
loads its persisted points on construction, and `build_report` already filters
by date, so a restart no longer rewrites the day.

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

That correct decision had a consequence nobody was told about. `PortfolioGovernor`
counts an unknown stop as no protection, so an adopted position contributes its
whole value to aggregate risk-at-stop. Measured against the real paper account,
seven adopted holdings put that figure at **30.01% against a 5% cap** — every new
entry refused, for the whole session, with the reason visible only to whoever
went looking in the audit log. Each part worked as designed; together they
produced a system that had quietly stopped trading.

`domain/oms/adopted.py` names the condition. `assess_adopted_positions()` returns
`None` when nothing was adopted (the normal case, and no news), and otherwise a
report carrying the count, which holdings are unprotected, and what share of the
risk budget they consume. It **reuses `PortfolioGovernor.snapshot()`** rather
than recomputing the arithmetic, so the number shown is the number that does the
blocking and the two cannot drift. The Dashboard renders it directly under the
market-session panel — amber while it is merely consuming budget, red once the
cap is breached and entries are actually being refused — and hides it entirely
when there is nothing to say. Adoption also logs at WARNING rather than INFO now,
and states the consequence rather than only the fact.

The report follows live positions, not the frozen baseline, so closing or
stopping the holdings makes the warning disappear: it can never outlive the
condition it describes.

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

## The regime gate and the data under it (M27a)

The regime label is not a display. `strategies/engine.py` skips any strategy
whose `suitable_regimes()` excludes the current label, so the classification
decides which strategies are allowed to trade at all. Three of the six
features it is computed from — VIX, the yield-curve slope, the credit spread —
came from `MockMacroSource`, which returns `round(random.uniform(-1, 5), 3)`.
Built in M2, wired in at `runtime.py` directly, and never once replaced.

On 29 July that fabricated data classified the market as low-vol. Swing's
suitable regimes are `{SIDEWAYS}`, so swing was ineligible for the entire
session, `scalar=1.00` meant nothing else looked unusual, and the system
recorded a normal day. A random number generator switched the only promoted
strategy off and nothing anywhere said so.

**`resolve_macro_source()`** now sits beside `resolve_broker`,
`resolve_market_data_source` and `resolve_fundamentals_source`: real FRED when
`FRED_API_KEY` is in the keyring, `MockMacroSource` otherwise with a warning
that names the consequence rather than the mechanism — that the regime is then
invented, and the regime decides who trades. The missing resolver was the root
cause here, not the mock. Every other synthetic default in this application is
reached through a function that announces itself; this one was reached by
being hard-coded, which is how it survived twenty-five milestones.

**`MacroFeed` publishes the current reading, not the history.** `fetch_series`
returns a series' full history because the daily-bar warm-start needs an as-of
join against past dates — VIXCLS is 9,239 observations back to 1990, and the
five configured series total **57,878**. The feed had been publishing one
`MacroEvent` per observation, which the mock's single-observation response
concealed completely; against real FRED it would have put all 57,878 on the
bus, to the regime engine and the Regime Monitor alike, every hour, to say
what five numbers currently are.

**The poll loop survives a failed poll.** `while True: await self.poll_once()`
was safe against a mock that could not fail. A network source that raises once
would have killed the task with the exception never retrieved, freezing every
macro feature at its last value for the rest of the session — the same class
of silent-degradation bug this milestone exists to remove.

### The regime engine says what it is doing

It had no logger. Not one line, through twenty-seven milestones. Its only
visible traces were `hmmlearn`'s own warnings and whatever the bus caught when
it crashed, which is why 29 July had to be reconstructed afterwards from a
blank field on screen.

It now logs every classification (transitions at INFO naming both labels, the
exposure scalar and the fact that strategies are now being skipped; unchanged
classifications at DEBUG), its warm-up progress against `min_fit_bars` so a
blank regime field is never ambiguous, every refit, and any fit or posterior
failure at ERROR with the per-feature numbers instead of a bare traceback.

A failed fit publishes nothing, exactly as before — the difference is that the
`StrategyEngine` fail-open to `SIDEWAYS` is now visible in the log rather than
inferred. Making it visible *on screen* is the remaining half, and is M27a's
fourth item.

**Zero movement is measured as max − min, not as standard deviation.** A
constant column is what makes the covariance matrix singular, and 28 July's
`startprob_ must sum to 1 (got nan)` is what that looks like from outside.
Sixty copies of `14.0` have a standard deviation of exactly `0.0`; sixty
copies of a real VIX print of `18.21` have `3.5e-15`. The first draft used
standard deviation and passed its test on round numbers while reporting
nothing at all against live FRED data.

**Real FRED does not by itself fix the fit, and slightly sharpens the
problem.** FRED series update daily, so on one-minute bars all three macro
columns are constant for the whole session. The mock re-drew a fresh random
number every hourly poll, which gave those columns spurious variation across
rows — the wrong data was also, incidentally, the better-conditioned data. A
simulated session on today's real readings (VIX 18.21, T10Y3M 0.84, BAA10Y
1.62) fits without crashing and publishes `sideways`, so this is not fatal;
but the columns carry no information until the bars are daily, which is what
the warm-start seeding is for.

## The live path runs on daily bars (M27a)

`bar_interval_seconds` was 60, so swing's EMA20/EMA50 were 20 and 50 *minutes*
and the regime HMM's 60-bar fit window was one hour of market. Both were
specified in daily bars. No strategy in this system had ever been evaluated on
the data it was designed for.

The interval alone would have left the system inert — ten weeks to fill an
EMA50, about three months for the HMM — because every buffer was built from
live ticks starting at zero at every process start. So the cadence and the
warm start are one change.

`WarmStart` is registered first with the orchestrator, which starts engines in
order, so every buffer is seeded before the feed delivers a tick.
`BarAggregator.seed` refuses to run once any bar exists — seeded history
appended after live bars would put an older bar after a newer one and corrupt
every rolling window read from the buffer — and it drops the vendor's bar for
today, which is a partial session the live feed is still forming.

**All three aggregators are seeded.** `SignalToOrderBridge` keeps its own, and
its ATR sets the stop distance which sets the position size. Moving the
strategies to daily bars while sizing them from an empty buffer would have
been a sizing bug shipped inside a milestone about honest measurement.

**Bulk fetching, and no synthetic fallback.** Measured on this account a single
symbol takes 1.3s, so 101 of them would block startup for over two minutes;
one multi-symbol request returns all of them in 3.2s. `get_daily_bars_many`
therefore has no synthetic fallback, unlike `get_daily_bars`: degrading a
*screen* to a clearly-labelled random walk is reasonable, seeding a buffer that
positions are sized from with one is not. Symbols the vendor did not return
stay unseeded and are named at WARNING.

**One feature row per bar, not per tick.** The regime engine appended a row on
every benchmark tick. Left alone, 390 intraday rows a day would have swamped
300 seeded daily ones inside a single session, restoring the exact mismatch
this milestone removes. The row for the bar in progress is now rewritten as its
price moves and rolls over at the boundary.

**Gap filling now depends on the interval.** On a daily interval every gap is a
weekend or a holiday, and Friday→Monday is a two-bar gap — well inside the
ten-bar intraday allowance, so it would have invented flat bars for days the
market never opened.

Macro readings are joined as-of each bar's own date and carried forward, never
interpolated. Pairing every seeded bar with one constant value would leave the
macro columns flat across the matrix, which is the singular covariance matrix
that crashed the fit on 28 July.

Verified against the live account: 101 symbols and 300 daily bars seeded in
17s, every feature column moving (VIX 13.47–31.05, curve −0.17–1.00, credit
1.50–1.88, breadth 0.12–0.74), and the HMM classifying on the first live bar.

### Swing's regime gate, widened by decision

The paper names Sideways alone for Swing. Measured over the 300 real sessions
to 29 July 2026, the regime engine classified:

| regime | share |
|---|---|
| bull | 32.0% |
| bear | 26.6% |
| high_vol | 24.9% |
| low_vol | 10.4% |
| **sideways** | **6.2%** |

So the only promoted strategy in the system was eligible about one session in
sixteen, and the zero-signal sessions of 28 and 29 July were the ordinary case
rather than an anomaly. `suitable_regimes()` now returns Sideways, Bull,
Low-Vol and Recovery — a pullback to EMA20 inside an EMA20>EMA50 uptrend is a
trend-continuation setup whose own entry condition already requires the
uptrend, so excluding Bull gated it out of the regime it was designed for.
Bear, High-Vol and Recession stay excluded. The exposure scalar travels with
the label, so this widens position size as well as eligibility.

This is a decision-changing change, made deliberately and with sign-off, and
recorded here because it departs from the reference paper.

### A dead classifier is now visible

`StrategyEngine` falls open to its default regime, so a crashed classifier
keeps the application trading with the regime gate silently disabled. On
28 July the HMM crashed on every fit for a whole session and nothing on screen
changed. The engine now publishes `RegimeHealthEvent`, and the main window
carries a third banner state — **REGIME ENGINE DOWN**, naming the reason and
the default the strategies are being gated on instead.

It is ranked below the kill-switch halt and MARKET DATA DOWN: a halt needs a
human, an outage may clear, and a dead classifier means the app is still
trading normally with the gate not gating. Least urgent of the three and the
easiest to never notice, which is why it is on the banner at all.

The banner is driven by events only and never asserted at startup. Lighting it
before the first bar would warn on every launch, and a banner that always warns
is one nobody reads; a run that never receives a tick is already covered by
MARKET DATA DOWN. Health is published on change, but *always* on the first
report — an engine whose very first fit fails has never been healthy, and
treating that as an unchanged state would have published nothing at all for
precisely the session this exists to make visible.

`StrategyEngine` also says so directly, naming every strategy and whether it is
eligible, the first time it gates on the default rather than on a classified
regime.

**Widening swing's regimes made this sharper.** `SIDEWAYS` is now inside
swing's suitable set, so a dead classifier means swing trades as though the
market were sideways, rather than being gated off by accident. The 28 July
silence partly protected against that; it no longer would.

### Persistence, deliberately not built

M27a's plan called for persisting the buffers so a restart does not reset them.
The warm start already re-seeds all 101 symbols from the vendor in a few
seconds, from the authoritative source rather than a local file that can go
stale or disagree with it. A second, worse copy of that is maintenance cost for
no benefit.

The one thing it would genuinely have covered is a **mid-session restart**,
which loses the day's forming bar — restarted at noon, the aggregator would
believe the day opened at noon, and the day's range is what ATR, the stop and
the position size are computed from. The fix is not a local file either: the
vendor's partial bar for today is loaded as the *forming* bar rather than
discarded. Same source, no new storage, and it closes the actual hole.

### The label is not yet a stable function of the input

Three replays over the same 300 days produced three different current labels —
`recovery`, `high_vol`, `low_vol` — differing only in when the last HMM refit
landed and what path the hysteresis took. The full live replay is the
trustworthy one; the `high_vol` run had breadth pinned at a constant 0.5, which
is the degenerate-column case the new zero-variance warning exists to catch,
and it was caught on a test harness rather than in the app.

No single day's label should be read as authoritative until this is understood.
A wider regime set is less sensitive to it, which was an argument for the
change above rather than against it.

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
