# Fill basis and the commission check — design

**Date:** 11 September 2026. **Milestone:** M175. **Outstanding item:** 3 ("A & B").
**Decisions by the operator, 11 September:** option A (slippage is measured, never
charged), approach 2 (the model stays in the ledger; IBKR's figure checks it),
and REWRITE the existing closed-trade rows.

---

## Why — what was measured, not assumed

Item 3 read "the ledger's costs are modelled while the broker's actuals are
discarded". Measured on 11 September, the commission was never the problem.

### 1. The commission model is exact

IBKR's `commissionReport` lines survive in the 24–25 August logs (938 of them).
Joined to `execDetails` by `execId` and totalled per `permId`, **17 of 17 orders
charged exactly `max(6.60, 8.8 bp × notional)`** — to the cent, single- and
multi-execution alike (LOV 81 executions, ASX 101).

### 2. Entry commission is charged twice — on every trade, open and closed

`SignalToOrderBridge.reconcile_entry_prices` (M65) overwrites the recorded entry
with the broker's `Position.avg_price`. On IBKR that is `avgCost`, which is
**commission-inclusive** (Alpaca's `avg_entry_price` was not — the same
broker-change shape as the `cumQty`/`avgPrice` defect). `_ENTRY_PRICE_TOLERANCE`
is 1 bp against an 8.8 bp commission, so it fires on every position at every
restart, and it undoes M70's correct in-session price:

    31 Aug 10:35  ENTRY PRICE CORRECTED: JHX.AX filled at 41.9185   (M70, the fill)
    31 Aug 13:38  Corrected ... JHX.AX -> 41.9554                   (M65, avgCost)
    10 Sep 10:34  ENTRY PRICE CORRECTED: COH.AX filled at 135.7360
    10 Sep 16:28  Corrected ... COH.AX -> 135.855

The inflated entry lowers `gross_pnl` by the commission, and `entry_cost`
charges it again. It also skews `risk_per_share`, every R-multiple, and
`entry_slippage`. Proven on the ledger — the gap equals the logged commission:

| | ledger entry | IBKR fill | gap × shares | commission |
|---|---|---|---|---|
| RHC | 44.45230503 | 44.4132 | 46.67 | 46.67 |
| PNI | 17.92576186 | 17.9100 | 46.86 | 46.86 |
| A2M | 6.98614259 | 6.9800 | 59.19 | 59.19 |
| IAG | 7.9269697 | 7.9200 | 46.69 | 46.69 |

**BHP.AX, stopped out at the 11 September open, is the first row ever closed with
`reference_price` set — and its slippage has the WRONG SIGN:** recorded +0.0464,
true −0.01 (fill 64.07 = 64.1263816 ÷ 1.00088, an exact tick, against a 64.08
reference).

### 3. Slippage is charged twice, both sides

`TradeLedger._fill_cost` uses `CostModel.apply()`, which is commission **plus
5 bp slippage**. A live fill price already contains its slippage. So does a
replay fill: `SimulatedBroker._slipped` moves the price against the order, and
the ledger then subtracts modelled slippage on top. The ledger is the only
consumer of modelled slippage for REALISED figures; the risk engine's
`round_trip` is a pre-trade estimate and correctly keeps it.

### 4. The $6.60 floor is charged per absorbed piece, not per order

`_close_against_lots` charges `_fill_cost(event.quantity, …)` per
`OrderFilledEvent`. LOV's single exit order was absorbed in pieces and paid
the floor four times (6.74, 6.81, 6.97, 12.68).

### 5. Commissions cannot be recovered from a second client

Read-only probe, clientId 99, 11 September 10:04: `reqExecutions` returned
BHP's 10:00 stop execution with `commission=0.0`, and `commissionReportEvent`
did not fire in 3 s. Whether the APP (clientId 1, which placed the order) is
sent commissions for fills recovered after a restart is **not measured**. So
actuals would only ever cover fills the app is connected for — which is why the
model stays authoritative (approach 2).

---

## Design

### Section 1 — a ledger cost is the broker's charge only

* New `CostModel.charge(notional)` = `commission(notional) + third_party(notional)`.
  `apply()` is unchanged — it remains the pre-trade and backtest figure.
* `TradeLedger._fill_cost` uses `charge()`. `entry_cost` and `exit_cost` now mean
  "what the broker billed", never slippage.
* **One floor per order.** The ledger keeps, per `order_id`, the notional and
  charge already booked; an increment's cost is
  `charge(cumulative notional) − already charged`. In memory only: a piece
  absorbed after a restart may pay a second floor, which can only matter below
  ~AUD 7,500 of notional — a size this system has not traded. Documented at the
  code, not fixed.
* The M70 and M71 correction paths already recompute costs through
  `_fill_cost`, so they inherit the change — covered by tests, not assumed.
* **Slippage is measured, never charged.** `entry_slippage` stays fill minus
  `reference_price`. On stop exits `exit_price − stop_price` is the gap, and both
  are already stored. No new exit-slippage column.

### Section 2 — M65 stops inflating the entry price

* `_Entry` gains `price_source: "fill" | "reference" | None`, persisted in
  `open_position_entries.json` (read with `.get()`; `None` = pre-M175 record).
* Stamped `"fill"` wherever the price written is a real fill:
  `_on_entry_price_corrected` (M70), and entry creation when the announced
  price was `order.filled_price` rather than `order.reference_price`
  (`OMS._announce_fill`, `oms.py:1169` — `OrderFilledEvent` gains
  `price_is_fill: bool` so the bridge can tell).
* **M65 never overwrites a `"fill"` price.**
* For any other record, M65 still corrects from the broker, but first converts
  the broker's average cost to a fill price when the adapter says it includes
  commission: above the floor `avg ÷ (1 + bps)`, below it `avg − floor ÷ qty`
  (whichever is self-consistent with `charge()`). A new adapter attribute
  `avg_price_includes_commission` — `True` for `IBAdapter`, `False` elsewhere
  (read with `getattr(…, False)`, the established optional-capability pattern).
* Other `avg_price` readers (governor fallbacks, delever, book-risk weights,
  corporate-action basis) are risk estimates where 8.8 bp is immaterial —
  deliberately unchanged, and said so in the commit.

### Section 3 — IBKR's commission checks the model

* `IBAdapter` subscribes to `ib.commissionReportEvent` and totals, per `permId`,
  commission and executed notional. When an order's reports are complete
  (cumulative quantity reaches the order's total and every execution has a
  report), it hands a plain `BrokerCommission` record (order_id, symbol, side,
  quantity, notional, commission, currency) to a registered listener. The data
  layer does not import `CostModel`.
* New domain component `CommissionAuditor` (`qat.domain.performance`) compares
  it with `CostModel.charge(notional)` and appends one row to
  **`commission_checks.csv`** in the data dir: `checked_at, order_id, symbol,
  side, quantity, notional, actual, modelled, currency, agrees`.
  * agree (≤ 0.01): INFO `COMMISSION VERIFIED`.
  * disagree, or currency ≠ the market's: WARNING `COMMISSION DISAGREES`.
* **No column on the ledger.** The report arrives after the fill is recorded;
  marking the row would mean amending written rows, which is what approach 2
  exists to avoid. `order_id` joins the two files.
* Adapters without the capability do nothing (`getattr` check at wiring).
* **This measures Section 5's open question.** The app's own entries are the
  positive control (reports observed live on 24–25 August). If broker-side
  exits never produce a row while entries do, that absence is then evidence.

### Section 4 — the rewrite

`scripts/repair_fill_basis.py`, modelled on `repair_entry_price_precision.py`:
PowerShell only, dry run by default, `--apply` to write.

* **Refuses while the app runs** (process check plus `session_running.json`).
* **Backs up** `closed_trades.csv` and `open_position_entries.json` before any write.
* **Per-row evidence, never blanket.** A row is inflated only if a logged M65
  line (`Corrected the recorded entry price for <SYM> -> <price>`) set that
  entry price. True fill = the logged `execDetails` average where the 24–25
  August logs hold it (LOV, RHC, PNI, A2M, IAG, TNE), else `avg ÷ 1.00088`.
  **Self-check first:** the formula must reproduce every logged fill, or the
  script writes nothing. Rows without evidence are listed and left untouched.
* Costs recomputed with `charge()`, one floor per order (rows grouped by the
  exit `order_id` — every row carries one, and LOV's five share `1216552509`;
  entry cost apportioned by quantity across rows from one lot), including the
  LOV repair row with empty costs.
* **Where the ledger holds only part of an order** (TNE.AX: 60 shares of a 3,051
  entry, whose remainder left by another route), the floor is NOT applied to the
  fragment — proportional rate only — and the row is flagged in the dry run.
  Charging a whole-order floor to a fragment would invent a cost.
* Derived columns rebuilt through `ClosedTrade` (`from_row` → corrected fields
  → `as_row`), never computed by hand. `audit_closed_trades` must pass after.
* Dry run prints a before/after table for every row: entry price, gross, costs,
  net, R, slippage, and the evidence used.
* The 9 open records: price → fill, `price_source: "fill"`.

### Sequence — after the close, never mid-session

1. Build M175 (carries `000f07e`); confirm the dist hash moved.
2. Close the app. **Leave IB Gateway up.**
3. Repair dry run → operator reads the table → `--apply`.
4. `deploy.ps1` dry run → **operator's OK** → `-Apply`.
5. Operator launches. Read back: the build stamp, NO M65 "Corrected the
   recorded entry price" line, and a clean ledger audit.

⚠️ **The old build must never launch on repaired records** — M65 would
re-inflate them at startup. Steps 3–5 happen together, with the app closed.

---

## Testing — tests first

* `charge()` excludes slippage; `apply()` unchanged.
* Ledger: live buy and sell costs equal `charge()`; an order absorbed in N pieces
  pays one floor; M70/M71 corrections recompute with `charge()`.
* **Replay (the "where else" case):** a simulated round trip's net P&L equals
  gross minus commission only — slippage appears once, in the fill prices.
* M65: skips a `"fill"` record; de-commissions IBKR `avgCost` above and below the
  floor; leaves Alpaca/simulated `avg_price` as-is; still heals a `"reference"`
  record.
* `price_source` round-trips through `open_position_entries.json`; a pre-M175
  record loads as `None`.
* `OrderFilledEvent.price_is_fill` is set from `filled_price`, not reference.
* Adapter: per-`permId` totalling across executions; completes only when
  quantity and reports are both complete; a report before its execution is held.
* `CommissionAuditor`: agree, disagree, currency mismatch, CSV header and append.
* Repair script: dry run writes nothing; refuses with the app running; refuses
  when the self-check fails; untouched rows stay byte-identical; post-repair
  audit passes — against a fixture ledger, never the live one.

## Out of scope

* Actual commissions INTO the ledger (approach 1). Revisit only if
  `commission_checks.csv` ever records a disagreement.
* Exit-slippage column; floor persistence across restarts; `avg_price` readers
  outside M65.
