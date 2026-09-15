# QAT Design Recovery & Design Intent Audit, report section 3: Current Baseline

> **Final report section, issued 15 September 2026** for the operator's review (Checkpoint B). Findings made after a section was drafted are recorded as dated correction notes in place; nothing has been silently rewritten.

**Brief §2 (the plan's retired "Stage 1")** (`docs/superpowers/plans/2026-09-12-design-recovery-audit-plan.md`).
**Measured:** Saturday 12 September 2026, 20:10–20:30 AEST. Read-only: nothing
in the system was changed to take these readings.
**Boundary:** only the locations the operator approved (plan, Stage 0 item
9): `C:\Claude Programming`, `C:\QuantAdvisoryTerminal`,
`%LOCALAPPDATA%\QuantAdvisoryTerminal`. Anything outside them is marked
**NOT MEASURED (outside the approved boundary)**.

This section records what exists. It makes no judgement about whether any of
it is right. Judgement belongs to later sections, where it has to cite
evidence.

---

## 3.1 Source and build

| Item | Value | Source |
|---|---|---|
| Git commit (HEAD) | `1eace83e870ecd6fa0b5ea9acdc2a5146a1aea13` | `git rev-parse HEAD` |
| Branch | `master`, 2 docs-only commits ahead of `origin/master` at measurement (pushed with this section) | `git status -sb` |
| Application version | `M175` | `src/qat/version.py` (`MILESTONE`) |
| Deployed commit | `5e322ca` | `scripts/handoff_state.py` (`DEPLOYED`); `C:\QuantAdvisoryTerminal\BUILD_MANIFEST.json` |
| `src/` changed since the deployed commit | **No** (empty `git diff 5e322ca HEAD -- src`) | git |
| Commits in history | 958 (first: `fa9ba47`, 25 Jul 2026) | `git rev-list --count HEAD` |
| Source modules | 184 Python files under `src/qat/` | file count |
| Source lines | 45,143 (physical lines, including comments and blanks) | line count |
| Test files | 382 (`tests/**/test_*.py`), 49,661 lines | file count |
| Tests collected | 3,703 | `scripts/handoff_state.py` |
| Test run (full suite) | 3,677 passed, 26 skipped (see 3.2) | pytest |

## 3.2 Quality gates, run separately on 12 Sep

| Gate | Result |
|---|---|
| Tests | **3,677 passed, 26 skipped, 0 failed**, 1,096 warnings, 316.6 s (`pytest -q`, exit 0, 12 Sep about 20:45). Which tests are skipped, and what the warnings are, is not assessed here |
| ruff (`src tests scripts`) | All checks passed, exit 0 |
| black `--check` (`src tests scripts`) | 627 files unchanged, exit 0 |
| mypy (`src`) | Success, 184 files, exit 0 |
| bandit (`-r src`, quiet) | 0 issues reported, exit 0 |
| CI (GitHub Actions) | Last run passed on `6008cb0` (12 Sep) |

**Suppressions in `src/`**, recorded because a clean gate means less where a
check is switched off locally:

| Marker | Occurrences | Files |
|---|---|---|
| `# noqa` (ruff) | 120 | 46 |
| `# type: ignore` (mypy) | 66 | 23 |
| `# nosec` (bandit) | 10 | 8 |
| `# pragma: no cover` | 6 | 5 |

Whether each suppression is justified is not assessed here.

## 3.3 Deployment

| Item | Value |
|---|---|
| Install location | `C:\QuantAdvisoryTerminal` |
| Installed executable sha256 | `64F132CEA9419C04E8BF5F338C522D7F39549573C1C1EB20B213D0C5C0E9678E` |
| Signature | Valid. Signer subject `CN=MyLocalAppPublisher` |
| Build manifest | `{"milestone": "M175", "commit": "5e322ca", "built_at": "2026-09-12T00:48:54Z"}` |
| Last build stamp in the app's log | `Build: M175 (5e322ca, built 12/09/2026 10:46:46 AEST, packaged)`, logged at the 12 Sep 10:55:08 launch |
| Deployed with | `scripts/deploy.ps1 -Apply`, 12 Sep 10:51 |
| Rollback directories | **NOT MEASURED (outside the approved boundary).** They sit beside the install at `C:\`, not inside it |
| Configuration file | `%LOCALAPPDATA%\QuantAdvisoryTerminal\.env` (resolved by `qat.config.env_path`) |
| Data directory | `%LOCALAPPDATA%\QuantAdvisoryTerminal\data` |

## 3.4 Operating state at measurement (about 20:15, 12 Sep)

| Item | Value |
|---|---|
| QAT app | **Not running.** Last equity sample 11:18 AEST, 12 Sep |
| IB Gateway / TWS | **Not running.** Nothing listening on 4001, 4002, 7496 or 7497 |
| LM Studio | Running, listening on port 1234 |
| Kill switch | `{"tripped": false, "reason": null}` (`data\kill_switch.json`) |
| Positions | **Not read from the broker** (Gateway down). Last recorded by the app, 12 Sep 10:56:09: ANZ 640, ASX 1314, BOQ 13586, COH 363, JHX 1097, SUN 3192, TAH 64229, TWE 10412, WOW 1098, each with a stop resting at the broker |
| Last equity row | equity 989,604.29, cash 495,714.44 (`equity_curve.csv`, 01:18:09Z) |

**Record files** (`%LOCALAPPDATA%\QuantAdvisoryTerminal\data`):

| File | Lines | Last modified | sha256 (first 16) |
|---|---|---|---|
| `closed_trades.csv` | 13 (12 rows + header) | 12 Sep 10:52 | `688B709185CB1F8F` |
| `open_position_entries.json` | 83 | 12 Sep 10:56 | `B389974E6286EAEB` |
| `risk_decisions.csv` | 4,959 | 11 Sep 15:59 | `41C838A260906B00` |
| `decision_journal.csv` | 478 | 11 Sep 15:55 | `FCC60F8163E21D19` |
| `equity_curve.csv` | 9,173 | 12 Sep 11:18 | `A768B21F30BA3045` |

## 3.5 Configuration

The effective values were taken from QAT's own loader (`qat.config.Settings()`),
which merges the code defaults with the live `.env` the way the app does.
There are 110 settings. **16 differ from the code default**; the other 94,
including every risk limit, run on code defaults. Values that look like
secrets are masked. Secrets live in the OS keyring, not in the settings.

### Settings overridden by the live `.env`

| Setting | Effective | Code default |
|---|---|---|
| `market` | `ASX` | `US` |
| `broker` | `ibkr` | `mock` |
| `market_data_source` | `yfinance` | `synthetic` |
| `fundamentals_source` | `yfinance` | `mock` |
| `execution_mode` | `auto` | `recommend` |
| `deployed_strategies` | `swing` | (empty) |
| `autonomous_strategies` | `swing` | (empty) |
| `min_cash_reserve` | 1000.0 | 1.0 |
| `watchlist_category` | `megacap` | `curated` |
| `watchlist_max_symbols` | 100 | 10 |
| `watchlist_curated_asx` | `RIO.AX,APA.AX,AMC.AX,MGR.AX,SGP.AX,NHF.AX` | `STW.AX,BHP.AX,CBA.AX,CSL.AX` |
| `general_request_provider` | `local` | `demo` |
| `sensitive_request_provider` | `local` | `demo` |
| `local_llm_model` | `openai/gpt-oss-20b` | `local-model` |
| `ui_level` | `professional` | `standard` |
| `data_dir` | `%LOCALAPPDATA%\QuantAdvisoryTerminal\data` | (resolved at runtime) |

### Trading and execution

| Setting | Value |
|---|---|
| `trading_mode` | `paper` |
| `execution_mode` | `auto`. The autonomy gate signs off orders without a human, for strategies on the autonomous list. Operator decision, 12 Sep: keep it |
| Autonomous strategies | `swing` (the only deployed strategy) |
| `allow_autonomous_live_trading` | `false` |
| `enforce_promotion_evidence` | `false` (on paper; the code enforces it on any live account) |
| Gate: pause buys below day P&L | −4% |
| Gate: halve size below day P&L | −2% |
| Gate: price drift limit | 3% |
| `allow_short_selling` | `false` |
| `entry_allow_list` | empty (all watchlist symbols enterable) |

### Broker

| Setting | Value |
|---|---|
| Broker | IBKR through IB Gateway, `127.0.0.1:4002` |
| Client id | 1 |
| Account | `DUQ200898`, paper, AUD base (IBKR statement, 24 Aug – 11 Sep) |
| Pricing model | `fixed` |

### Market data

| Setting | Value |
|---|---|
| Price source | yfinance (daily bars and polled quotes) |
| Modelled feed delay | 1,200 s (`market_data_delay_seconds`) |
| Staleness threshold | 900 s beyond the delay (`data_staleness_seconds`) |
| Watchlist | megacap ASX, up to 100 symbols; benchmark `STW.AX` (from the app's log, 12 Sep: "benchmark=STW.AX, 99 breadth symbols") |
| Fundamentals | yfinance |
| Macro | FRED: `DGS3MO`, `DGS10`, `T10Y3M`, `VIXCLS`, `BAA10Y` (from the app's log, 12 Sep) |

### Risk (all at code defaults)

| Setting | Value |
|---|---|
| Per-trade risk | 1% of equity |
| Stop distance (sizing) | 2.5 × ATR |
| Kelly fraction | 0.5; measured inputs after 20 closed trades (`edge_min_trades`) |
| Aggregate risk-at-stop cap | 5% |
| Concurrent positions | 10 |
| Single-name concentration | 15% |
| Sector concentration | 30% |
| Correlated-cluster concentration | 30% at correlation ≥ 0.70 |
| Gap budget | 5% of equity at a 6% gap |
| Portfolio expected-shortfall limit | 3% |
| Order size cap | 10% of available cash |
| Cash reserve | AUD 1,000 |
| Cost-to-risk cap | 10% |
| Costs in paper | on |
| Commission settings | `commission_bps` 5.0 and `broker_min_commission` 6.60 in the settings. The cost model applied the ASX Fixed profile instead: 8.8 bp, floor 6.60, 0.0 bp third-party. Evidence: `repair_fill_basis.py` printed that profile on 12 Sep 10:52. How the two relate is a Stage 3 question |
| Modelled slippage | 5 bp (`slippage_bps`) |
| Earnings | on; half size within 5 days of a scheduled announcement |
| Minimum hold | on; 10 trading days, with an escape at 0.5R against |
| Time stop | on; 30 trading days |
| Entries per week | 10 |
| Kill switch: daily loss / drawdown | 3% / 20% |
| De-lever sweep | **off** |
| Resting-order cancel (orphan rail) | **off** |
| Protection sweep | every 300 s |
| Promotion bar | 30 trades, average R ≥ 0.20, win rate ≥ 40%, worst loss ≤ 3 × average win |

### Regime

| Item | Value | Source |
|---|---|---|
| Features | `log_return`, `realized_vol`, `vix_level`, `yield_curve_slope`, `credit_spread`, `breadth` | `settings.regime_features` |
| VIX series | `VIXCLS` (FRED, US) | `settings.regime_vix_series` |
| Bar interval | daily (86,400 s) | `settings.bar_interval_seconds` |
| HMM states | 4 | `RegimeEngine` default; `runtime.py:874` passes no override |
| Refit interval / minimum bars | 20 bars / 60 bars | `RegimeEngine` defaults |
| Hysteresis | margin 0.15, 3 consecutive updates | `HysteresisGate` defaults (`fusion.py:194`) |
| VIX axis thresholds | < 15 low, > 25 high | `fusion.py:27-28` |
| Labels and exposure scalars | bull 1.0, low_vol 1.0, recovery 0.9, sideways 0.7, bear 0.5, high_vol 0.4, recession 0.3 | `fusion.py:30-38` |
| Strategy eligibility | probability mass ≥ 0.5 across a strategy's suitable regimes | `settings.regime_eligibility_mass` |

### AI / LLM

| Item | Value |
|---|---|
| General requests | local model |
| Position-sensitive requests | local model |
| Local model | `openai/gpt-oss-20b` at `http://localhost:1234/v1` (LM Studio, running at measurement) |
| Anthropic model setting | `claude-sonnet-5` (configured, not selected by either request class) |

## 3.6 Not measured in this section

* Rollback directories: outside the approved boundary.
* Broker-side positions and orders at measurement: Gateway not running.
* Anything in `C:\ShareTrader`: not approved (plan, Stage 0 item 9).
* Behaviour. This section records configuration, not what the code does with
  it. That is Stage 3.
