# Friday paper unwind: stopped at the data-source gate (16 October 2026)

**Outcome:** QAT was not started. No Friday Gateway request, cancellation, or
order was made. The approved BOQ, ANZ, SUN, ASX and TAH sequence was not begun.
The 15 October broker inventory remains a historical snapshot, not a current
position or order verification. DS's 15 October data-source ruling requires a
halt if settings alone cannot make Yahoo a logged cross-check while IBKR is the
primary source, or if configured Yahoo news or fundamentals can feed a
recommendation, sizing or order. Both conditions fail in the current code.

## Preparation and evidence

The evidence branch starts at `8738c40` and preparation commit `88b9897`
contains read-only broker-preflight and restorable store-copy scripts and their
offline tests. Local verification passed: ruff, `black --check .`, `mypy src`,
`bandit -q -r src`, and 4,530 pytest tests (26 skipped). [CI run
38719952806](https://github.com/dsaunders-06/WorkBench/actions/runs/38719952806)
passed. No production code or stored configuration was changed.

At 08:37:15–08:37:17 Sydney a restorable copy of the real QAT store was made
outside Git at
`C:\Users\mailm\Documents\Codex\phase3-unwind-20261016\snapshot-20261016T0840-AEDT`.
It contains 307 files, 137,784,184 bytes. Its `manifest.json` SHA-256 is
`acf6feafaebdb2c943af5b25ddf36e1d5634197a6a5558950128096d6d36ae3f`;
the manifest lists every source filename, size and SHA-256. A second read of
the live store immediately after the copy found no added, changed or removed
file. The directory name was chosen in advance; the manifest's timestamps are
the authoritative capture times. The accompanying committed manifest records
the paths and hashes, but no store contents.

The approved launch overrides were evaluated through `Settings()` in the
normal Windows environment, reading the existing
`C:\Users\mailm\AppData\Local\QuantAdvisoryTerminal\.env`. This constructed
settings only; it did not build `Runtime`, start QAT or contact the Gateway.
The relevant resolved values were:

| Setting | Resolved value |
| --- | --- |
| `market`, `broker` | `ASX`, `ibkr` |
| `ibkr_host`, `ibkr_port`, `ibkr_client_id`, `ibkr_account_id` | `127.0.0.1`, `4002`, `1`, `DUQ200898` |
| `execution_mode`, `trading_mode`, `delever_sweep_enabled`, `autonomy_enabled` | `recommend`, `paper`, `False`, `False` |
| `market_data_source` | `yfinance` |
| `yfinance_poll_seconds`, `market_data_delay_seconds` | `60.0`, `1200.0` |
| `news_source`, `news_min_sources` | `yfinance`, `1` |
| `fundamentals_source`, `fundamentals_cache_days` | `yfinance`, `7.0` |
| `enforce_earnings_event_risk`, `earnings_event_size_scalar` | `True`, `0.5` |
| `deployed_strategies` | `swing` |
| `bar_macro_series` | empty |
| `fred_series`, `regime_vix_series` | `DGS3MO`, `DGS10`, `T10Y3M`, `VIXCLS`, `BAA10Y`; `VIXCLS` |
| `FRED_API_KEY` | not configured (presence only was checked; no secret value read into the report) |
| `general_request_provider`, `sensitive_request_provider` | `local`, `local` |
| `reconciliation_poll_seconds` | `300.0` |

## Why settings cannot satisfy the Friday ruling

| Configured path | Actual consumers | Does the manual close depend on it? | Minimum change before a new run |
| --- | --- | --- | --- |
| Yahoo market ticks (`market_data_source=yfinance`) | `runtime.py::resolve_market_data_source` returns `YFinanceMarketDataSource`. `Runtime.build_demo` gives it to `MarketDataFeed`, which publishes ticks to feature, regime, strategy and signal-to-order engines. These can affect marks, recommendations, sizing and orders. The setting's only choices are `synthetic`, `yfinance` and `alpaca` (`config.py`). | `PositionCloser.close_position` obtains broker positions and open orders rather than a Yahoo quote. Starting the full app nevertheless activates the direct Yahoo trading feed. | Add a reviewed IBKR market-data source and make it the primary runtime feed; put Yahoo behind a separate fetch-and-log comparison path with no consumer that can trade. There is no settings-only IBKR choice. |
| Yahoo daily history (the same `market_data_source` setting) | `data/history.py::resolve_history_source` returns `RealHistorySource` backed by `YFinanceHistorySource`. `WarmStart` seeds strategy, signal-bridge ATR and feature buffers from it; screens and backtests also read it. | The close call itself does not fetch these bars; QAT startup does. | Add an IBKR history source to the resolver and keep any Yahoo comparison separate from warm-start and strategy inputs. |
| Yahoo news (`news_source=yfinance`) | `runtime.py::resolve_news_source` returns `YFinanceNewsSource`; `advisory_inputs.py::news_for` fetches and corroborates stories, then `build_advisory_context` puts them into the AI Advisor and Workbench model context. `ai_advisor.py` displays a `recommendation` based on that context. | No news fetch appears in `PositionCloser.close_position` or `OMS.sign_off`. | To retain the fetch while meeting DS's gate, remove Yahoo news from recommendation context and log it in an isolated comparison path, or obtain a separate DS decision on its role. Changing the setting to `none` would violate the instruction to keep it configured. |
| Yahoo fundamentals (`fundamentals_source=yfinance`) | `runtime.py::resolve_fundamentals_source` gives a cached Yahoo source to `StrategyEngine`; `strategies/engine.py` supplies its figures to deployed strategy rules. `runtime.py::_build_earnings_calendar` also selects `YFinanceEarningsCalendar`; `signal_bridge.py::_submit_sized` passes days to earnings to `risk_engine/engine.py`, where the configured 0.5 scalar can reduce buy size. Fundamentals also enter AI advisory, screener and Workbench screens. | The full manual close does not request fundamentals and the earnings scalar applies to buys only. The running app still lets Yahoo data influence recommendations and sizing. | Separate Yahoo fundamentals and earnings data from strategy, recommendation and sizing inputs while retaining their logging, or obtain a DS decision on their role. A setting alone cannot keep this source configured yet inert in those paths. |

The broker's typed quote path (`oms.py::_current_price_observation` through
`IBAdapter.price_observation`) is separate from the Yahoo feed; choosing
`broker=ibkr` does not change `market_data_source` or `resolve_history_source`.
The Yahoo feed has no comparison-only switch or log-only sink. A
`market_data_source=synthetic` override would replace primary prices with
invented data and would turn Yahoo off, so it does not meet the ruling either.
`operational/history.py` does define a log-only `YahooCrossCheck` protocol for
an `IBKRBarSource`, but there is no production IBKR history client or Yahoo
cross-check implementation wired into `qat.app:main`; `runtime.py` still uses
the separate Yahoo market feed and history resolvers.
With no FRED key, `runtime.py::resolve_macro_source` would also select its
synthetic fallback; that is recorded here, not used to justify a launch.

The source separation and recommendation/sizing failures are enough to apply
DS's explicit Friday halt. The read-only broker preflight was therefore not
sent, and the holdings and ten working orders were not re-verified today.
No startup adoption, legacy migration, missed-fill replay, resting-order scan,
protection sweep, dashboard confirmation, execution, closed-trade row or final
account capture occurred. The five holdings and their protective legs were
left untouched. The separate question of whether quantity-only legacy entry
migration is permitted under the startup halt rule remains open for the next
date.

**Decision needed for a new date:** DS must review the minimum data-path
changes or explicitly revise the source constraints, then re-authorise a
fresh broker preflight and exact unwind actions. No fallback source or order
sequence is proposed here.
