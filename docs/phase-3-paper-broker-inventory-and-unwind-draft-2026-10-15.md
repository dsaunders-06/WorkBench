# DU paper inventory and Friday unwind draft — 15 October 2026

**Status:** read-only evidence and a draft for DS review. No order, cancellation,
QAT application, OMS or poller was started. Friday's sells and cancellations
require DS approval of the individual actions and a fresh broker preflight.

## Merge and evidence boundary

`recovery/phase-3-recommend-mode` fast-forwarded from `d55b51f` to
`b6db82962ad039c150a40d078ac3b787d4e131f7` and was pushed. The latter
is the accepted `recovery/phase-1-exit-readiness` head. The merged branch's
[CI run 38694579594](https://github.com/dsaunders-06/WorkBench/actions/runs/38694579594)
passed. There was no production code change in this inventory.

At 17:49 Sydney, the current QAT local stores were copied outside Git to
`C:\Users\mailm\Documents\Codex\phase3-broker-inventory-20261015\local-stores`.
Only the copy was read. A single paper Gateway connection at localhost:4002
used client ID 99. The script checked exactly one `DUQ200898` account before
each of five read-only requests; `reqAllOpenOrders` did not bind an order. It
did not call `reqOpenOrders`, `reqAutoOpenOrders`, `placeOrder` or `cancelOrder`.
The raw payload's `read_only=true` describes the script's denied-method
guard, not a verified Gateway "Read-Only API" configuration.
IBKR documents that [all-open-order reads do not bind orders](https://interactivebrokers.github.io/tws-api/modifying_orders.html)
and that API orders normally remain cancellable only by the submitting client
ID [here](https://interactivebrokers.github.io/tws-api/open_orders.html).
The guard's three offline tests cover those method denials and the DU check.

The raw JSON, its SHA-256 sidecar and the full copied stores remain outside
Git. `PHASE3_BROKER_INVENTORY_MANIFEST_2026-10-15.json` records their paths,
hashes, request parameters and UTC times. The broker snapshot ran from
06:55:00.746157 to 06:55:01.239760 UTC (17:55 Sydney).

## Broker account

The `DUQ200898` account summary returned AUD 999,701.55 net liquidation,
AUD 681,431.68 cash, AUD 920,465.20 available funds and AUD 681,431.68
buying power. `reqPositionsAsync` delivered six callback rows: five positive
positions below and a zero-share BHP row. The keyed `IB.positions()` cache had
the five positive rows once each. All five are ASX `STK` contracts in AUD.

| Holding | conId | Broker shares | QAT entry record | Entry record versus broker |
| --- | ---: | ---: | --- | --- |
| BOQ.AX | 11470910 | 13,586 | 25 Aug, AUD 6.38 fill, stop 6.07, target 7.05 | Price plan agrees; quantity is absent from legacy entry record. The 25 Aug journal records 13,586. |
| ANZ.AX | 4109645 | 640 | 25 Aug, AUD 37.16 fill, stop 35.25, target 41.24 | Price plan agrees; quantity absent. Journal records 640. |
| SUN.AX | 12101107 | 3,192 | 25 Aug, AUD 18.6806484962406 weighted fill, stop 17.20, target 21.27 | Price plan agrees; quantity absent. Journal records 3,192. |
| ASX.AX | 4354508 | 1,314 | 25 Aug, AUD 56.42420091324202 weighted fill, stop 51.18, target 65.17 | Price plan agrees; quantity absent. Journal records 1,314. |
| TAH.AX | 4506346 | 64,229 | 4 Sep, AUD 0.89 recorded basis, stop 0.80, target 1.075 | Price plan agrees; quantity absent. Journal records 64,229. Exact TAH fill basis remains unverified. |

The earlier pre-freeze origin analysis is in
`phase-1-paper-holdings-provenance-2026-10-15.md`. The current entry file has
no protective broker order IDs, `orderRef`s or share quantities. Matching the
plan's prices and the journal's initial quantities is evidence of consistency,
not a durable identity match. The new code's legacy-quantity migration would
derive the current size from a stable broker position and missed-fill snapshot,
back up the old file, and refuse contradictory evidence
(`signal_bridge.py::_migrate_legacy_entry_quantities`). This has not been run
against the live stores.

## All working broker orders

Every row below is `SELL`, client ID **1**, `GTC`, parent ID **0**, with an
empty `orderRef`. Each pair shares an OCA group. The LMT legs were `Submitted`;
the STP legs were `PreSubmitted`. Quantity is the order's total quantity; a
fresh remaining-quantity and holding check is mandatory before Friday.

| Symbol | Leg | orderId | permId | Shares | Price (AUD) | OCA group | QAT record comparison |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| BOQ | LMT | 152 | 1216552512 | 13,586 | 7.05 | 1216552511 | Target price and original size match; no QAT protective ID record. |
| BOQ | STP | 153 | 1216552513 | 13,586 | 6.07 | 1216552511 | Stop price and original size match; no QAT protective ID record. |
| ANZ | LMT | 433 | 1216558933 | 640 | 41.24 | 1216558932 | Target price and original size match; no QAT protective ID record. |
| ANZ | STP | 434 | 1216558934 | 640 | 35.25 | 1216558932 | Stop price and original size match; no QAT protective ID record. |
| SUN | LMT | 167 | 1216552521 | 3,192 | 21.27 | 1216552520 | Target price and original size match; no QAT protective ID record. |
| SUN | STP | 168 | 1216552522 | 3,192 | 17.20 | 1216552520 | Stop price and original size match; no QAT protective ID record. |
| ASX | LMT | 157 | 1216552515 | 1,314 | 65.17 | 1216552514 | Target price and original size match; no QAT protective ID record. |
| ASX | STP | 158 | 1216552516 | 1,314 | 51.18 | 1216552514 | Stop price and original size match; no QAT protective ID record. |
| TAH | LMT | 500 | 579188642 | 64,229 | 1.075 | 579188641 | Target price and original size match; no QAT protective ID record. |
| TAH | STP | 501 | 579188643 | 64,229 | 0.80 | 579188641 | Stop price and original size match; no QAT protective ID record. |

There was **no other working order** in the account at this read. Each pair
is a protective bracket, not a new order awaiting approval. The GTC legs can
still fill before Friday; this is a point-in-time inventory.

`reqCompletedOrdersAsync(apiOnly=False)` returned zero rows, and the
account-filtered `reqExecutionsAsync` returned zero fills. There are therefore
no delivered times to normalise in this capture. These empty responses are
not proof that older executions or completed orders never existed; the copied
journal and `absorbed_fills.json` contain historical activity.

## Copied QAT records and discrepancies

The current copy contains `open_position_entries.json`, `decision_journal.csv`,
`closed_trades.csv`, `absorbed_fills.json` (with a 12 September watermark),
`kill_switch.json`, `resting_order_anomalies.json` and `.env`. It contains no
SQLite OMS database, `inflight_orders.json`, `ib_pending_legs.json` or
`exit_recovery.json`. The `sqlite:///./qat.db` setting is present, but no
corresponding database file was found in this copied app store; the active
records above are files. No in-memory OMS order book exists while QAT is
stopped. Thus none of the ten live leg `permId`s has a current durable
protective-leg counterpart in the new identity stores. A search of the copied
historical `qat.log*` files found **all ten permIds**, so they were logged by
QAT in the past; log text is not a current structured identity or cancellation
receipt. Their empty legacy `orderRef`s cannot be equated to the new UUID
references. The currently reported OCA group pairs are available to the
merged `resting_orders.py::_group_key` logic, which nets the two legs of each
group; historical orphan warnings in the logs do not establish that the
current book is orphaned. Friday must re-run that check.

Four entry records, **WOW.AX, JHX.AX, TWE.AX and COH.AX**, have no broker
holding or working order in this snapshot. They are stale local entries until
the missed-fill replay and legacy migration can verify and retire them. The
copied kill switch is not tripped and the anomaly list is empty. Those facts
do not clear the stale entries or certify Friday's startup.

## Startup controls and automatic paths

The copied settings resolve to `trading_mode=paper`, `broker=ibkr`,
`market=ASX`, `ibkr_client_id=1`, **`execution_mode=auto`**,
`autonomous_strategies=swing`, `autonomy_enabled=True`,
`delever_sweep_enabled=False`, `resting_order_reconcile_enabled=True`, and
**blank `ibkr_account_id`**. The blank account currently prevents a
non-read-only ASX connection. If that setting alone were supplied, the
unchanged `auto` mode could autonomously sign pending swing orders:
`config.py::autonomy_enabled` is true in paper auto mode and
`AutonomousExecutor.retry_pending` is active. The de-lever sweep
measures risk but returns before creating sells while disabled. The governor
blocks new risk when over its cap; it does not itself transmit an order.

For a proposed Friday QAT startup, set `QAT_EXECUTION_MODE=recommend` in the
launch environment and verify `Settings().autonomy_enabled is False` before
starting `qat.app:main`. Keep `QAT_TRADING_MODE=paper` and
`QAT_DELEVER_SWEEP_ENABLED=false`, and set and verify
`QAT_IBKR_ACCOUNT_ID=DUQ200898`. `IBAdapter.connect` refuses non-read-only
ASX operation while that account setting is blank, so the copied settings
cannot support the proposed OMS unwind as they stand. A process-scoped
settings evaluation against the **copy**, with those four overrides, returned
`execution_mode=recommend`, `autonomy_enabled=False`, `trading_mode=paper`,
`delever_sweep_enabled=False`, `ibkr_account_id=DUQ200898` and client ID 1.
No setting was changed tonight. DS must approve the Friday configuration and
exact orders. The production `IBAdapter` validates the configured paper port
and account identity but does not itself call `managedAccounts()` immediately
before every Gateway request. Tonight's inventory used a separate guarded
read-only client. If a per-request DU recheck is required for Friday's QAT
OMS path too, that production capability must be reviewed separately before
orders are authorised; a settings override alone cannot provide it.

Even in recommend mode, startup runs adoption, the resting-order scan, missed
fill replay, legacy entry migration, lot restoration and the protection sweep
(`ReconciliationMonitor.start`, `SignalToOrderBridge.start`). The bridge may
raise a *pending-signoff* stop if one is missing; it does not itself authorise
its transmission in recommend mode. The autonomous retry loop exits when
`autonomy_enabled` is false. These startup writes and reads need a separate
preflight on the actual stores; the read-only inventory did not exercise them.

## Friday 16 October, 10:30–15:00 Sydney — draft only

The intended path is QAT's own `PositionCloser.close_position` and
`OMS.sign_off` in **recommend** mode, with the existing Phase 1 kill switch
and checks. The dashboard asks for one confirmation per symbol, not a bulk
action. **Attribution blocker:** `dashboard.py::_run_close` passes the
hard-coded string `operator (dashboard)`, not an authenticated DS identity.
`OMS.sign_off` records that string. Directly calling the closer with
`operator="DS"` would record the literal text but would not prove who clicked;
it is not the dashboard flow. No production code may be changed in this
inventory. DS must resolve the sign-off attribution before the unwind can
claim compliance with I-5. The dashboard's preview also reads only the OMS's
in-memory known stop orders, so it may say it believes zero legs even while
the broker has the ten inherited legs shown above. The closer verifies the broker holding,
entry record and protective legs. At sign-off,
`OMS._release_protective_legs` saves recovery intent, cancels each target
first and its stop second through `IBAdapter.cancel_order`, and re-reads the
account-wide order book after each cancellation. It refuses the market sell
until both legs are confirmed absent. `IBAdapter._adopt_from_broker` can look
up an inherited order by `permId`, but the legacy legs have not yet been
tested against this merged implementation. They belong to client ID 1, which
matches the copied `ibkr_client_id`; IBKR says that matching client identity
and the submitting TWS username are required to modify or cancel API orders.
The inventory proves the client ID, not the username or actual cancellation
capability. Do not interpret an optimistic local `cancelled` status as broker
confirmation.

On Friday, first verify exactly one DU paper account, the corrected startup
settings, all five account/conId/quantity pairs, every order ID and OCA pair,
the kill switch, and absence of unrecognised orders. Let QAT adopt, migrate
and restore; inspect the resulting entry quantities, lots, protective stop
map and reconciliation before any approval. If the startup changes an entry,
finds a foreign holding or cannot identify/cancel a leg, stop the entire
unwind and leave the remaining brackets untouched. Do not force adoption,
bind an order, or switch to a probe script.

The proposed *individual* actions, in this order, are:

| Step | DS-approved cancellation requests through OMS, target then stop | One proposed QAT OMS order after both cancellations are confirmed |
| --- | --- | --- |
| 1 BOQ.AX | permIds 1216552512 (LMT), 1216552513 (STP) | SELL MKT 13,586 BOQ.AX |
| 2 ANZ.AX | 1216558933 (LMT), 1216558934 (STP) | SELL MKT 640 ANZ.AX |
| 3 SUN.AX | 1216552521 (LMT), 1216552522 (STP) | SELL MKT 3,192 SUN.AX |
| 4 ASX.AX | 1216552515 (LMT), 1216552516 (STP) | SELL MKT 1,314 ASX.AX |
| 5 TAH.AX | 579188642 (LMT), 579188643 (STP) | SELL MKT 64,229 TAH.AX |

These quantities and identities are **15 October evidence**, not standing
Friday instructions. If an OCA leg or holding changes before its turn, stop
and return revised exact actions to DS. A cancel may cause an OCA sibling to
change state; the OMS must prove both are gone before selling.

After **each** sell, use a fresh DU-checked `reqExecutions` read to pair the
broker `execId` and delivered time with the OMS fill; confirm the full broker
quantity is flat, both protective legs are absent, the entry record is
removed, an attributable closed-trade row was written, and
`OMS.check_reconciliation` and resting-order checks are clean. Only then
consider the next row. `SignalToOrderBridge._on_fill` removes a fully closed
entry; `TradeLedger._on_fill` closes its lot. These outcomes remain to be
proved with the actual migrated legacy data. At the first unexpected broker
state, stop the whole unwind, do not retry a submission, and leave all
remaining holdings and their protection untouched. Any already-cancelled
protection must be handled by the OMS recovery state and a fresh DS decision;
the draft does not authorise an improvisation.

## Decisions and proof still needed

1. DS approval of the exact five sells, ten cancellation identities and the
   Friday startup configuration; no approval is inferred from this draft.
   Resolve the dashboard's generic operator attribution so the actual
   approving person is recorded before treating its confirmation as I-5
   sign-off. This is a production/UI change outside tonight's scope unless
   DS specifies an existing approved operator-authentication path.
2. A non-synthetic preflight of QAT's inherited client-1 leg adoption and
   cancellation confirmation, plus successful migration of the legacy entry
   quantities and four stale entries, before any sell.
3. Fresh Friday account/position/order evidence. Resting stops or targets may
   fill independently before the planned window.
4. Whether Friday's trading path must enforce the same per-request DU recheck
   as tonight's probe. The current production adapter does not implement it.

The BHP OMS diagnostic round trip and entry transmission remain separate,
deferred work. No autonomous trading is authorised here.
