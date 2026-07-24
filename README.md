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

Milestones 1–8 are complete: architecture/config/logging/EventBus (M1), the
real-time data pipeline (M2), all 15 strategies (M3), the backtester (M4),
the regime engine (M5), the risk engine + OMS sign-off gate (M6), IBKR
integration (M7), and the AI advisory service (M8 — `AnthropicEngine` +
`LocalEngine`, the router, and the input/output guards). Final packaging
(M9) is not built yet. The Workbench, Regime Monitor, and AI Advisor screens
are still placeholders — wiring them to real output is pending, mechanical
follow-up work.

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

3. **Secrets** (IBKR credentials, Anthropic/LLM API keys) are read from the
   OS keyring via `qat.security`, never from plaintext config or logs. Use
   `keyring.set_password("qat", "<NAME>", "<value>")` to store one locally,
   or set the equivalent environment variable for local dev only.

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

## Verifying the AI advisory service yourself

Same situation as IBKR: `AnthropicEngine` and `LocalEngine`
(`src/qat/domain/ai_advisory/llm_engine.py`) are built against the real
Anthropic SDK and Ollama's real OpenAI-compatible REST shape, and their
request-building/response-parsing/retry logic is unit-tested against fakes —
but nothing here proves a live call actually works, since this environment
has no Anthropic API key or running Ollama server. To check it yourself:

- **Anthropic**: `keyring.set_password("qat", "ANTHROPIC_API_KEY", "<your key>")`,
  then construct `AnthropicEngine()` with no `client` argument (it builds a
  real `anthropic.Anthropic` client from that key) and call
  `await engine.complete(SYSTEM_PROMPT, "Summarise a hypothetical calm, low-vol regime.", AdvisoryRecommendation)`
  (`qat.domain.ai_advisory.prompts.SYSTEM_PROMPT`, `qat.domain.ai_advisory.schema.AdvisoryRecommendation`).
- **Local/Ollama**: start Ollama locally (`ollama serve`, with a model pulled),
  construct `LocalEngine(model="<your model>")` (defaults to
  `http://localhost:11434/v1`), and call `complete(...)` the same way.

Confirm you get back a schema-valid `AdvisoryRecommendation`, not an error.

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
  an in-app confirmation dialog (not yet wired — presentation layer) should
  ever set to `True`.
- A kill-switch (`domain/risk_engine/kill_switch.py`) trips on daily-loss,
  drawdown-from-HWM, data staleness, broker-reconciliation mismatches, an
  exhausted IBKR reconnect budget, or a manual trigger, and halts new
  orders. It's built and tested; wiring it into the Risk Console UI as an
  always-visible control is pending.
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
