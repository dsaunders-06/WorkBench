# Quant Advisory Terminal

An AI-assisted, multi-strategy share-trading **advisory and paper-trading**
desktop application for Windows. It detects the market regime, generates and
backtests strategy signals, enforces risk limits, integrates with Interactive
Brokers, and uses an LLM as an analyst that proposes and explains — while a
human approves every live order.

> **Educational / paper-trading software.** This project is for research and
> paper trading. Live trading is at your own risk; nothing here is investment
> advice. The default and only shipped configuration is paper trading — going
> live requires a deliberate configuration change and an in-app confirmation,
> and no component of this system places, modifies or cancels an order
> without an explicit human sign-off.

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
```

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
- No order reaches a broker without explicit human sign-off — `OMS.submit_order()`
  only ever creates a `pending_signoff` order; only `OMS.sign_off(...)`, an
  explicit operator-attributed call, can transmit it. There is no auto-trade
  toggle, now or planned.
