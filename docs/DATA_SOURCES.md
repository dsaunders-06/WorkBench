# QAT data-source inventory — 16 October 2026

DS changed [I-6](INTENT.md) on 15 and 16 October 2026: IBKR is the single data and
broker source; Yahoo is a logged cross-check only, except that Yahoo earnings
dates are approved as an event-risk input that can only reduce position size.
DS also decided on 16 October 2026 that Alpaca is retired as both broker and
data source. An Anthropic key is out of scope. [I-8](INTENT.md) limits QAT to
ASX equities; US trading is not part of its functionality. References below
to the still-present Alpaca code and historical US use describe inventory,
not an approved source or market.

A validated source, direct or indirect, is added, removed or changed only by
DS's explicit decision.
This inventory describes the **current code and resolved Friday launch
settings**, not an approval of the deviations below. No code or stored
settings were changed for this inventory. Friday's launch was
[halted before Gateway access](https://github.com/dsaunders-06/WorkBench/blob/81ebe6d/docs/phase3-paper-unwind-halt-2026-10-16.md).

DS decided on 16 October that live prices and history will move to IBKR, and
that synthetic fallbacks must fail closed in every mode that can trade. Both
implementation changes are scheduled separately, after this report. Yahoo
fundamentals in signals remain undecided pending the legacy-signal-path
analysis. FRED macro and Yahoo news for the AI Advisor remain open for DS.
The Friday unwind was halted; none of these decisions authorises a source
substitution or a new trading run.

The stored `.env` still says `execution_mode=auto`; Friday's approved
process-only overrides resolved to `recommend`, `paper`, IBKR on port 4002,
account DUQ200898, autonomy off and delever sweep off. Source values below
were read with `Settings()` in the normal Windows environment on 16 October.
The source selectors are the same in the stored file and the intended launch.
Secret *presence* was checked; values are not recorded here.

## Configured and reachable sources

| Provider and data | Selector, current resolved value | Code path and consumers | Can affect a price, recommendation, sizing or order? | Validation and status |
| --- | --- | --- | --- | --- |
| IBKR Gateway: paper account, positions, orders, executions, current quotes | `broker=ibkr`, `trading_mode=paper`, `ibkr_account_id=DUQ200898`, port 4002 | `presentation/runtime.py::resolve_broker` → `data/broker/ib_adapter.py` → OMS, reconciliation, position and quote observations. | **Yes**: broker holding/quote and execution authority. | ASX paper account and quote/order probes in [19 August plan](superpowers/plans/2026-08-19-ibkr-move.md), September [handoff](HANDOFF.md), and October [probe report](PHASE3_REAL_GATEWAY_PROBE_2026-10-10.md). Delayed type-3 observation on 15 October in [exit-readiness findings](phase-1-exit-readiness-findings.md). **DS decided 16 October** that IBKR supplies live prices; app feed wiring remains pending. Friday made no request. |
| IBKR daily TRADES, all-hours: intended operational history | Phase 3 contract specifies `useRTH=0`; **no application source selector or production IBKR history client exists** | `operational/history.py::IBKRBarSource` is an interface; `operational/adapter.py` can use an injected source, but `qat.app:main` has no production wiring. | Intended to determine cards and order levels; currently **not** the app's primary bar source. | October real-data probe and 13 October [price ruling](phase-3-step2-history.md); not validated as an end-to-end app feed. **DS decided 16 October** to move live prices and history to IBKR; implementation is pending. |
| Yahoo chart/latest-trade and daily history | `market_data_source=yfinance`; `yfinance_poll_seconds=60`; `market_data_delay_seconds=1200` | `presentation/runtime.py::resolve_market_data_source` → `MarketDataFeed` → feature, regime, strategy and signal bridge. `data/history.py::resolve_history_source` → Yahoo `RealHistorySource` → `WarmStart`/rolling buffers; also screens and research. `bar_macro_series` is empty, but could route Yahoo series into regime if enabled. | **Yes**: primary prices/marks, strategy signals, sizing and possible orders. This is **not** a logged cross-check. Construction failure may select a synthetic source. | 499-session ASX replay cited in the [19 August plan](superpowers/plans/2026-08-19-ibkr-move.md); 20–21 August real ASX observations in [archived handoff](archive/HANDOFF-2026-08-20-superseded.md). **DS decided 16 October** that Yahoo becomes log-only and IBKR supplies live prices/history; implementation is pending. Synthetic fallback must fail closed in any trading mode; implementation is pending. |
| Yahoo company news | `news_source=yfinance`; `news_min_sources=1` | `runtime.py::resolve_news_source` → `data/news.py::YFinanceNewsSource` → `presentation/advisory_inputs.py::news_for`/corroboration → `build_advisory_context` → AI Advisor and Workbench model output. | **Yes**, an AI recommendation can use it. The deterministic symbol verdict does not call the news source; no direct OMS/strategy/sizing call was found. Manual `PositionCloser.close_position` does not fetch it. | Real Yahoo ASX samples on 20 August; rule built 20 August, loosened by DS 21 August; [archived handoff](archive/HANDOFF-2026-08-20-superseded.md), `data/news.py`, `config.py`. Its recommendation role exceeds I-6. **Open for DS** under the 16 October decision; no expanded role is approved. |
| Yahoo company fundamentals and relative strength | `fundamentals_source=yfinance`, cache 7 days | `runtime.py::resolve_fundamentals_source` → Yahoo/cache and `StrategyEngine`; relative strength reads the selected Yahoo history source. Also Advisor, Workbench and Screener. | **Yes**: deterministic strategy recommendations and AI recommendations. Manual close does not fetch these. Resolver failure can select synthetic fundamentals. | The real-fundamentals option predates the freeze. **Open for DS** after the legacy-signal-path analysis requested 16 October; no new role is approved. Synthetic fallback must fail closed in trading modes, with implementation pending. |
| Yahoo earnings dates | `fundamentals_source=yfinance`, cache 7 days; `enforce_earnings_event_risk=True`, scalar 0.5 | `runtime.py::_build_earnings_calendar` → `YFinanceEarningsCalendar` → `signal_bridge.py::_submit_sized` → `risk_engine/engine.py::_earnings_scalar` and `evaluate_order`. | **Yes**: can change entry sizing. DS approved this indirect input on 16 October **only when it can reduce size**. | `config.py` restricts the scalar to `(0,1]`, and the risk engine multiplies proposed shares by it. However, the later portfolio expected-shortfall gate can turn a rejected unsized buy into an approved smaller buy. In an offline controlled example, no earnings date yielded 0 shares (5.00% expected shortfall over the 3.00% limit), whereas a date two days away yielded an approved 62.5 shares (2.50% expected shortfall). This can **add exposure relative to no date** and does not meet the literal reduce-only condition. No code changed; DS must decide the disposition. |
| FRED: DGS3MO, DGS10, T10Y3M, VIXCLS, BAA10Y | `fred_series` names all five; `regime_vix_series=VIXCLS`; **FRED_API_KEY present in QAT's keyring on 16 October** | `runtime.py::resolve_macro_source` selects FRED with a key, otherwise `MockMacroSource`; `MacroFeed` and `WarmStart` feed regime, features and exposure decisions. | **Yes**: FRED macro can affect the regime, features and exposure decisions when selected. | The [archived handoff](archive/HANDOFF-2026-08-20-superseded.md) and a rotated application log show real FRED polling through at least 23 August. DS restored the original key and reports a live DGS10 fetch on **16 October 2026 Sydney time**: 16,181 observations, latest 14 October. The 16 October response was not independently inspected in this docs-only work. FRED's role in the AI Advisor remains **open for DS**. If a key is absent in a trading mode, the mock fallback must fail closed under DS's 16 October ruling; implementation remains pending. |
| Local LM Studio model | `general_request_provider=local`, `sensitive_request_provider=local`; configured base URL `localhost:1234/v1` | `runtime.py::_resolve_engine` → `AIAdvisoryService` → Advisor/Workbench prose and recommendations. | **Yes**, for displayed AI recommendations; no direct trading/OMS edge was found. It is a model provider, not a market-data authority. | Local service/version reported in [handoff](HANDOFF.md) on 11–14 September; availability was **not** retested Friday. |

Other selectable but **not selected** sources remain in code: retired Alpaca for a US
broker/feed/history (`broker` and `market_data_source`), Anthropic for AI
(`general_request_provider`/`sensitive_request_provider`), synthetic market
data, mock fundamentals and mock macro. They must not be mistaken for approved
substitutes. `runtime.py::resolve_market_data_source` and
`resolve_fundamentals_source` can fall back to synthetic sources on
construction failure; `resolve_macro_source` does so without a FRED key.
DS decided on 16 October that these fallback paths fail closed in any mode
that can trade; implementation remains pending.

### Credential-name presence, 16 October 2026

A static scan of `src/qat/` found four names requested through
`security.get_secret`; the Alpaca source reuses the broker adapter's two
names. A presence-only check of QAT's Windows keyring service and the process
environment gave the following result. No credential value was displayed,
saved or committed, and this check made no vendor request.

| Requested name | Keyring | Environment | Current relevance |
| --- | --- | --- | --- |
| `FRED_API_KEY` | Present | Absent | `resolve_macro_source` can construct the real FRED client; DS reports the 16 October DGS10 fetch above. |
| `ALPACA_API_KEY` | Absent | Present | Retired by DS on 16 October 2026; the still-present code path is pending removal. |
| `ALPACA_SECRET_KEY` | Absent | Present | Same retired Alpaca path. |
| `ANTHROPIC_API_KEY` | Absent | Absent | Out of scope; current general and sensitive model-provider settings select the local model. |

The original FRED key was absent from QAT's credential store at an unknown
point before DS restored it on 16 October. The presence checks do not establish
when it disappeared, how long the mock macro source was selected, or whether
each historical macro request succeeded.

The Phase 3 ASX calendar, membership, halt and corporate-action authorities
are operator-supplied files with fixture-backed loaders
(`src/qat/operational/`). Real authority files have not been supplied or
validated. They are not vendor connections or a production data feed. The
separate `YahooCrossCheck` protocol in `operational/history.py` is log-only
by design, but is not wired into `qat.app:main`. IBKR's optional structured
corporate-announcement capability remains unavailable in the Phase 1 adapter.

## Position at the 12 September development freeze

This reconstruction uses the repository at `d39debc`, its
[handoff](HANDOFF.md), the [superseded handoff](archive/HANDOFF-2026-08-20-superseded.md),
the [19 August IBKR move plan](superpowers/plans/2026-08-19-ibkr-move.md) and the
[22 August symbol-verdict plan](superpowers/plans/2026-08-22-symbol-verdict.md).
The archived documents are dated observations; the source code and the
11 September settings backup (SHA-256
`74024f4db99d73ff2c918d5404703a9fdd81a07ae11bdbcb494bf3575731e1f3`,
read from the outside-Git store copy) establish the freeze configuration. The
`.env` is outside Git, so `d39debc` alone cannot prove its bytes.

* **Before the IBKR move:** Alpaca was a configured US paper broker and
  market/history option (July commits `52b0e4a`, `bb29cc9`). It was no longer
  selected for ASX at the freeze; its code was deliberately retained, not
  silently removed ([handoff](HANDOFF.md), item 13).
* **19–21 August:** the IBKR move established ASX paper execution and delayed
  broker quotes. The historical-bar and live strategy feed still resolved to
  Yahoo, not IBKR. The 19 August plan cited a 499-session Yahoo ASX replay and
  expressly warned that an IBKR history source and pacing were unwritten.
  Yahoo earnings dates and fundamentals were available; FRED macro polling
  was observed through at least 23 August. The 11 September settings backup
  selects
  `market=ASX`, `broker=ibkr`, `market_data_source=yfinance`,
  `fundamentals_source=yfinance`, local model providers and paper mode.
  The handoff records `auto` and deployed `swing` at the freeze.
* **22 August:** the symbol-verdict design kept the deterministic verdict
  separate from the model opinion. The Advisor and Workbench shared
  `build_advisory_context`; news and fundamentals were explicit model
  inputs. The plan caught and corrected prompt text that still claimed two
  independent outlets after the threshold became one.
* **4–10 September:** the 21 August claim of zero IBKR ASX headlines was
  retracted when eight provider codes were discovered. The 10 September
  positive-control probe then found no API headlines for ASX **or** AAPL/MSFT
  on the paper Gateway. DS decided not to pursue IBKR news and to keep
  `news_source=yfinance` and `news_min_sources=1`. Whether live-account API
  access differs was left untested; Dow Jones headline-storage rights were a
  separate blocker ([handoff](HANDOFF.md), 10 September section).

### News rule and assessed sources

DS's 20 August rule required **two independent outlets** for a secondary
story before it reached the model. `data/news.py::corroborate` clusters
similar, fresh headlines and counts normalised outlet names, not articles;
an exchange filing marked `primary` bypasses the count **for that story
only**. The implementation cannot prove that two aggregators did not
republish the same wire copy. On **21 August DS** lowered
`news_min_sources` from 2 to 1 after NHF's six Yahoo items came from a
single outlet. The code and handoff explicitly warn that one planted story
can then reach the model. This was already the rule at the freeze, not a
post-freeze loss. `news_source=yfinance` remained selected.

| Source assessed by the freeze | Finding and freeze status |
| --- | --- |
| Yahoo | Working ASX headlines, including a 20 August six-symbol sample of 47 items and two stories clearing the then-two-source rule. Cross-listing and stale-result defects were measured and filtered. **Configured** for Advisor/Workbench news by freeze; single-source stories passed after DS's 21 August change. |
| IBKR: BRFG, BRFUPDN, DJ-N, DJ-RTA, DJ-RTE, DJ-RTG, DJ-RTPRO, DJNL | Eight subscribed channels map to only **Briefing.com and Dow Jones** publishers. 4 September apparent access was not reproducible. 10 September paper API positive control returned zero even for US megacaps; paper-vs-live access remains **uncertain**. `IBKRNewsSource.fetch` is intentionally unwired because of that and unresolved Dow Jones storage terms. |
| asx.com.au / ASX ComNews | Primary exchange filings; crawling permission did not establish data or redistribution rights. Licensed subscription/permission needed. **Assessed, never configured** as QAT news or structured-action feed. |
| marketindex.com.au | Aggregator; pairing its republished wire with Yahoo could falsely satisfy two-outlet corroboration. **Assessed, not configured.** |
| listcorp.com | Bot access refused (HTTP 403 on robots.txt). **Assessed, not configured.** |
| Other paid IBKR providers: Benzinga BZ, Briefing Trader BRF, Fly on the Wall FLY | US-focused, not subscribed or tested for ASX in the 19 August plan. **Assessed as possibilities only.** |
| IBKR WSH | 10 September paper API returned Error 10276/no metadata; entitlement unavailable. **Not configured.** |

Current news reaches the **AI Advisor and Workbench recommendations** through
`advisory_inputs.build_advisory_context`. The deterministic
`symbol_verdict.build_verdict`, Phase 2 engine and OMS do not import the news
source. `data/ibkr_news.py` and the handoff say headline storage in the
decision journal is a licensing blocker, but a trace of the current
`news_for` → Advisor/Workbench path found no journal write of the fetched
headlines. Treat that documentation claim as **unverified**, not as licence to
enable IBKR news; the journal behaviour needs its own targeted check before a
storage-based decision.

## Freeze-to-current differences requiring DS review

1. **New I-6 versus existing Yahoo paths:** the direct Yahoo live feed,
   Yahoo warm-start history, Yahoo news in AI recommendations and Yahoo
   fundamentals/earnings in strategy and sizing were present at the freeze
   and remain selected. The 15–16 October I-6 changes make the direct Yahoo
   feed a deviation and approve earnings dates only under the reduce-only
   constraint described above. No settings-only switch makes Yahoo a
   logged-only cross-check while IBKR supplies the app's primary feed.
2. **IBKR operational history is designed, not wired:** October real-data
   probes and the Phase 3 operational interfaces add evidence and a future
   contract, but the running app still has no IBKR history selector/client.
3. **FRED activation changed at an unknown point:** the rotated application
   log records real FRED observations on 23 August at 23:34 UTC (24 August
   09:34 Sydney), including DGS10 with 16,144 observations. That outside-Git
   log is `C:\Users\mailm\Documents\Codex\phase1-holdings-copy-20261015\data\logs\qat.log.6`,
   SHA-256 `efe2adbfc4fdb8ce2ef11130dffaf190075d4ae528d95369091245b525b2303d`.
   The key was missing from QAT's credential store at an unknown later point;
   Git cannot date its absence. DS restored the original key and reports a
   live DGS10 fetch on 16 October with 16,181 observations, latest 14 October. Presence was
   confirmed without reading the value into this document. The FRED role in
   AI advice remains for DS to decide, and the mock fallback still needs the
   approved fail-closed change in trading modes.
4. **News validation was revised before the freeze:** the two-source rule had
   already been changed by DS on 21 August, the early IBKR zero-coverage claim
   was retracted, and 10 September probes left live API access unresolved.
   No validated ASX news provider was dropped after the freeze: Yahoo remains
   configured; ASX ComNews, MarketIndex and IBKR news were assessed but not
   adopted. That historical authorization does **not** override the new I-6.
5. **Indirect roles awaiting a decision or implementation:** Yahoo earnings
   dates are approved only as a reduce-only input, but the current risk path
   can admit an otherwise rejected buy after applying the scalar. Yahoo
   fundamentals can change deterministic strategy signals, and Yahoo news
   can become displayed AI advice; their roles remain open for DS. Synthetic
   fallbacks must fail closed in trading modes under DS's 16 October decision,
   but the code does not yet enforce it. Nothing has been restored or changed.
