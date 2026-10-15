# I-6 source paths, fresh paper inventory and narrow-close feasibility — 16 October 2026

**Status:** read-only broker evidence and offline design for DS. No QAT application,
OMS, poller, market-data feed or order path was started; no order was sent or
cancelled. The five closes remain deferred until DS chooses a method and date.
The raw response remains outside Git; its filename, request times and SHA-256
are in [the manifest](PHASE3_BROKER_INVENTORY_MANIFEST_2026-10-16.json).

## Fresh DU inventory versus 15 October

At 09:27:31–09:27:32 Sydney (22:27:31–22:27:32 UTC on 15 October),
`scripts/phase3_broker_inventory.py` connected to the paper Gateway at
127.0.0.1:4002 as client 99. Its guarded client checked exactly one
`DUQ200898` managed account immediately before each of five read-only
requests: positions, account summary, all open orders, completed orders and
account-filtered executions. It neither bound nor modified an order. Five
position callbacks and five keyed positions were returned, with no duplicate
row. Completed orders and executions returned zero rows in this request;
that does not erase older history. AUD net liquidation was 999,701.55, cash
681,431.68 and available funds 920,465.20, matching the 15 October response.

| Holding (ASX stock, AUD, DUQ200898) | conId | Shares on 15 and 16 October | Working target, status | Working stop, status | Difference |
| --- | ---: | ---: | --- | --- | --- |
| BOQ.AX | 11470910 | 13,586 | 152 / permId 1216552512, LMT 7.05, Submitted | 153 / 1216552513, STP 6.07, PreSubmitted | None |
| ANZ.AX | 4109645 | 640 | 433 / 1216558933, LMT 41.24, Submitted | 434 / 1216558934, STP 35.25, PreSubmitted | None |
| SUN.AX | 12101107 | 3,192 | 167 / 1216552521, LMT 21.27, Submitted | 168 / 1216552522, STP 17.20, PreSubmitted | None |
| ASX.AX | 4354508 | 1,314 | 157 / 1216552515, LMT 65.17, Submitted | 158 / 1216552516, STP 51.18, PreSubmitted | None |
| TAH.AX | 4506346 | 64,229 | 500 / 579188642, LMT 1.075, Submitted | 501 / 579188643, STP 0.80, PreSubmitted | None |

All ten legs were `SELL GTC`, client ID 1, parent ID 0, empty `orderRef`, with
each symbol's target and stop in the same OCA group. No other working order
appeared. Their IDs, quantities, prices, OCA groups and statuses are unchanged
from the [15 October inventory](phase-3-paper-broker-inventory-and-unwind-draft-2026-10-15.md).
This snapshot is not a standing permission to cancel or sell: any leg may fill
before a future run, so the account needs a new guarded inventory at that time.

## Which signal path uses Yahoo fundamentals?

The legacy Phase 1 path and the Phase 3 card path are separate.
`presentation/runtime.py::Runtime.build_demo` constructs a
`MarketDataFeed`, Yahoo history `WarmStart`, `StrategyEngine` and
`SignalToOrderBridge`; the bridge can propose an OMS order in recommend mode,
though sign-off remains required. `StrategyEngine._on_market_data` fetches
fundamentals for each ticked symbol whenever strategies are deployed, inserts
them into `SymbolContext`, and evaluates the strategies. The fundamentals
fields are used in `can_slim.py`, `dividend_growth.py`, `garp.py`, `growth.py`,
`multi_factor.py`, `quality.py`, `sector_rotation.py` and `value.py`. Relative
strength for the Yahoo fundamentals source also uses the selected history
source. The deployed `swing` strategy may not inspect those fields, but the
legacy engine still fetches them; other deployed strategies can make them
decisive. `runtime.py::_build_earnings_calendar` separately obtains Yahoo
earnings dates; `signal_bridge.py::_submit_sized` passes them to
`risk_engine/engine.py::evaluate_order` for sizing. Fundamentals also reach
the AI Advisor, Workbench and Screener through their own presentation paths.

The [Phase 3 specification](phase-3-recommend-mode-integration-spec.md)
instead calls for operational IBKR bars → the pure Phase 2 engine → QUALIFIED
card candidates. `operational/adapter.py` and `operational/cards.py` have no
Yahoo fundamentals dependency; their optional `YahooCrossCheck` is log-only.
This is the intended recommend-mode recommendation path. It is not yet the
running app's sole path: `Runtime.recommendation_service` defaults to `None`,
`Runtime.build_demo` never constructs `CardService`, and the main window
receives that optional service. Meanwhile the legacy feed and strategy engine
are still constructed. Thus leaving full QAT running in recommend mode does
not implement I-6 merely by disabling autonomy. DS's decision on Yahoo
fundamentals in signals remains open after this analysis; no role was silently
approved or removed.

## Narrow close using existing production components

The close can be **composed in a separate script in principle**, without
building the full `Runtime` or any market-data, history, fundamentals, news,
macro or AI source. This is a design conclusion, not a successful rehearsal
or permission to run. It must use the production classes and a copied store,
then prove its behavior offline before DS chooses a real-run method.

| Component | Required role and behavior without other sources |
| --- | --- |
| `data/broker/ib_adapter.py::IBAdapter` | Paper Gateway account/position/order/fill authority. `connect` uses configured account and port; direct sell orders and cancels do not need a quote stream. The adapter itself does not recheck `managedAccounts` before every call, so a narrow script needs an independently tested guarded wrapper for that stronger probe rule. |
| `domain/risk_engine/kill_switch.py::KillSwitch`, `risk_engine/engine.py::RiskEngine`, `oms/oms.py::OMS`, `domain/decision_journal.py::DecisionJournal` | Use the real persisted switch, exit risk audit, sign-off, durable order identity and journal. `RiskEngine.evaluate_exit` uses the given quantity and recorded entry price, checks the kill switch, and skips entry sizing/portfolio appetite limits by design. For a sell, `OMS.sign_off` does not fetch a quote. No source outside the broker is constructed. |
| `oms/reconciliation.py::ReconciliationMonitor` | `start` adopts current broker positions and resting stops, scans resting orders, then polls. Adoption failure is logged and suppressed by this component, so the script must explicitly require the expected adopted account/conId/quantities, stops and a clean scan before any close. |
| `oms/signal_bridge.py::SignalToOrderBridge` | With an empty `warm_symbols` tuple and its built-in `NullEarningsCalendar`, `start` needs no Yahoo source. It subscribes to fills, replays missed broker fills, migrates legacy entries, reconciles entry prices/strategies, restores ledger lots, proposes missing protection and starts the sweep. No live tick or signal need be published. Its `_on_fill` removes an entry when the recorded quantity is fully sold. The script must expose a live read-through mapping of its entries to `PositionCloser`, as `Runtime` does. |
| `performance/trades.py::TradeLedger` | `start` subscribes to fill events and persists closed-trade rows. It requires no market data to close restored lots, but without history the restored lots' MAE/MFE start at entry price; this is incomplete research evidence, not a fabricated bar. |
| `oms/position_closer.py::PositionCloser`, pending-leg and recovery stores | The closer checks the held quantity, entry record and existing legs, then calls `OMS.submit_exit_order` and `OMS.sign_off`. `OMS._release_protective_legs` saves recovery intent, cancels target then stop, verifies each absent and only then places one market sell. The adapter's pending-leg store and OMS's exit-recovery journal retain order identity and uncertain handoffs. No non-IBKR source is consulted. |

**Identity and proof limits.** The closer and OMS protective-release code still
select working legs by *symbol*, not account/conId. The fresh snapshot has one
ASX/AUD stock per symbol and no foreign holding, but a new preflight must
prove those facts and refuse any same-symbol contract or unknown working leg.
The script's per-request DU guard and its direct construction and shutdown
order need offline tests. Whether inherited client-1 legs can be cancelled
and verified by the merged adapter remains a real paper-Gateway question;
do not infer it from the read-only inventory. A script can add these guards
without changing Phase 1 code, but that composition has not yet been built
or tested. If a mock rehearsal cannot retain all Phase 1 controls, stop and
seek a reviewed production change instead of bypassing them.

`PositionCloser.close_position(symbol, operator=...)` passes that label to
`OMS.sign_off`, which writes it into the decision journal. A proposed label
would name DS, the 15 October written approval, the chosen run date and the
specific holding's contemporaneous confirmation. A literal label records an
assertion; it does **not** authenticate who confirmed. The existing dashboard
hardcodes `operator (dashboard)` and does not prove DS's identity. DS must
choose an approval method that can be recorded truthfully before any real
close. The previously approved conditional stop recovery uses the separate
`exit-protection-recovery` operator label and places only a stop for the
verified residual holding at the captured original stop price.

On startup, adoption should seed the five broker quantities and their stops.
The current copied legacy entries have no quantity; if no missed fills
intervene, `SignalToOrderBridge._migrate_legacy_entry_quantities` backs up the
file and fills in the five current quantities, while retiring WOW, JHX, TWE
and COH only after a stable snapshot shows them flat. Entry prices may be
corrected against broker fill evidence; lots are restored before exits.
These are **predictions**, not a completed migration. A future script must
compare every store with its backup, halt on contradictory fills or identity,
and decide with DS whether the expected migration writes are accepted before
closing. TAH's exact historical basis remains unverified in the prior
inventory; no new basis is inferred here.

### Offline rehearsal before any real run

Copy the current stores and hash them. Use `MockBroker` or a simulated broker
with the five exact account/conId/position rows and ten inherited legs;
instrument it to reject every market-data/vendor call, unlisted order and
unlisted cancellation. Start the production kill switch, risk engine, OMS,
reconciliation monitor, trade ledger and bridge in their application order,
then verify the adopted baseline, all ten legs, the legacy migration, four
stale-entry outcomes, restored lots and every changed store. Exercise one
DS-labelled `PositionCloser` close at a time. Assert target-before-stop
cancellation, confirmed absence, exactly one `SELL MKT`, execId-based fill
attribution, zero broker holding, removed entry, one closed-trade row and
clean reconciliation before the next symbol. Fault cases must cover an
unknown account/conId, changed or missing leg, cancellation timeout, partial
fill, uncertain transmission and conditional stop recovery; each halts the
remaining sequence without retry. This synthetic rehearsal checks control
flow only. A later DS-approved paper run is needed to establish actual IBKR
cancellation, fill and recovery behavior.

The expected copied-store diff is concrete: startup creates the legacy
entry backup, writes quantities for the five held entries and retires the
four flat legacy entries from `open_position_entries.json` if the replay
snapshot supports that result; each completed close removes one more entry.
`risk_decisions.csv` and `decision_journal.csv` gain one risk decision and
the proposal/sign-off/outcome for each close. `closed_trades.csv` gains one
row per fully restored and closed lot, with broker execId attribution, while
`absorbed_fills.json` advances its watermark and records absorbed fill IDs.
`exit_recovery.json`, `inflight_orders.json` and `ib_pending_legs.json` may
be created or updated during each protection handoff, then must show no
unresolved exposure or pending leg at the end. The rehearsal should present
the actual byte-level diff and explain any deviation from these expectations;
it must not write to the live stores.

### Action list and stop conditions (design only)

| Order | Proposed target cancel, then stop cancel | One proposed order after both are confirmed absent | Pre-approved conditional recovery stop if a failed close leaves unprotected shares |
| --- | --- | --- | --- |
| BOQ.AX | orderId 152 / permId 1216552512, then 153 / 1216552513 | SELL MKT 13,586 | SELL STP GTC 6.07, no more than residual 13,586 |
| ANZ.AX | 433 / 1216558933, then 434 / 1216558934 | SELL MKT 640 | SELL STP GTC 35.25, no more than residual 640 |
| SUN.AX | 167 / 1216552521, then 168 / 1216552522 | SELL MKT 3,192 | SELL STP GTC 17.20, no more than residual 3,192 |
| ASX.AX | 157 / 1216552515, then 158 / 1216552516 | SELL MKT 1,314 | SELL STP GTC 51.18, no more than residual 1,314 |
| TAH.AX | 500 / 579188642, then 501 / 579188643 | SELL MKT 64,229 | SELL STP GTC 0.80, no more than residual 64,229 |

`IBAdapter.open_orders` exposes the permId as the OMS cancellation key when
present; both broker identifiers are shown to avoid ambiguity. These are
unchanged 16 October inventory quantities, **not executable
instructions for a new date**. Before each symbol, recheck the DU account,
exact contract identity, holding, legs and DS approval. Stop the entire run
on any changed or unexpected broker/QAT state, kill-switch trip, failed
attribution or confirmation, unresolved recovery journal, extra order, or
uncertain fill. Do not retry a sell. Leave later holdings and their brackets
untouched. If an already-started close leaves shares without protection, the
previously approved conditional recovery may place only the captured-price
stop at no more than the residual broker quantity; then halt. Confirm each
completed exit by broker execId, zero position and no working conId order,
removed entry, closed-trade row and clean reconciliation/resting-order scan
before considering the next. No such sequence was run in this investigation.
