# Close-only paper unwind: offline rehearsal and 19 October draft

**Status:** for DS review. No Gateway connection, cancellation or transmitted
order was made in this work. The Monday list is a draft; this branch remains
unmerged. The script defaults to refusal and requires an explicit execution
flag, an exact list hash, a DS instruction date, a Sydney session/window, and
the fixed paper settings before it can connect.

## Evidence boundary

The rehearsal read a fresh, read-only copy of QAT's local data store, taken on
16 October outside Git. Its 51-file manifest has SHA-256
`7bd0a9ba212264a1ee774dd6bf89ef2c2d87af5c8249bdf3376986ebc20c52c7`.
The fake broker was seeded from the 16 October read-only DU response, SHA-256
`2ce56c1075c42e0d708eb0ddb7057a5df091f9afff78cfbd181eabd5eb6e5ba1`.
The completed rehearsal report is outside Git at
`C:\Users\mailm\Documents\Codex\phase3-close-rehearsal-20261016\run4-asx\rehearsal.json`,
SHA-256 `84e5f006b56f53a9105d6b457987af1ff9a07b9dc861d392e6f0675ea67555b9`.
The five `fault-asx-*` runs each have their own store copy, report and hash
in that directory. No
copied store, raw broker response or simulated execution is committed.

`phase3_close_unwind.py` composes the production kill switch, risk engine,
decision journal, OMS, reconciliation monitor, signal bridge fill handler,
trade ledger and position closer. Its broker guard permits only the pinned
target cancellation, stop cancellation, then full SELL MKT for the active
symbol. A conditional recovery SELL STP GTC may cover no more than the
remaining shares at the pinned original stop. Startup cannot send an order.
The script imports or constructs no market-data, history, fundamentals, news,
macro or AI source. Its null earnings-calendar interface makes no vendor
request. The offline rehearsal substitutes an IB-like fake for `IBAdapter`;
the real adapter and inherited-leg cancellation still require the separately
approved paper run to prove broker behavior.

## Copied-store rehearsal

Startup adopted all five DU holdings and found five resting stops. Legacy
migration wrote quantities for BOQ 13,586, ANZ 640, SUN 3,192, ASX 1,314 and
TAH 64,229, preserved a backup of the original entry file, and retired the
flat WOW, JHX, TWE and COH entries. It also backed up and amended the
closed-trade CSV schema. With `market=ASX` fixed in the script, no existing
entry price, stop or target changed at startup. An earlier, discarded
rehearsal inherited QAT's `market=US` default: it mislabeled ASX closed trades
US/USD and spuriously corrected TAH's entry price. The ASX-only setting and
refusal test now prevent that error. The live runner refuses any changed
existing entry field before a close.

| Simulated close | Confirmed target then stop cancellation (permId) | Fake execId | Store changes after this close |
| --- | --- | --- | --- |
| BOQ.AX 13,586 | 1216552512, 1216552513 | SIM-1 | `exit_recovery.json`, `inflight_orders.json` added; entries, ledger, journal, risk audit, fill state changed |
| ANZ.AX 640 | 1216558933, 1216558934 | SIM-2 | Entries, ledger, journal, risk audit, fill state changed |
| SUN.AX 3,192 | 1216552521, 1216552522 | SIM-3 | Same five stores changed |
| ASX.AX 1,314 | 1216552515, 1216552516 | SIM-4 | Same five stores changed |
| TAH.AX 64,229 | 579188642, 579188643 | SIM-5 | Same five stores changed |

The copied `closed_trades.csv` increased from 12 to 17 rows,
`decision_journal.csv` from 477 to 487 rows, and `risk_decisions.csv` from
4,958 to 4,963 rows. The five new closed rows say ASX/AUD. Each full close removed its entry. Final copied entries
and `exit_recovery.json` were both empty; the fake had no working orders or
holdings. The pending-leg store did not change because the fake does not
implement the IBKR adapter's pending-leg persistence. All five fill prices
were simulated at the recorded broker cost basis, solely to exercise ledger
bookkeeping; they are not market-price or commission evidence. The sign-off
label in the fake run explicitly says `OFFLINE REHEARSAL — no DS order approval`.

Five separate runs against the copied store exercised the halt paths:

| Fault | Result and remaining protection |
| --- | --- |
| Cancel refused | BOQ target remained Submitted; no stop cancellation or sell; later four brackets untouched. |
| Target already Filled | Full-account inventory refused before constructing the close components; no store changed. |
| BOQ quantity mismatch | Inventory refused before construction; no store changed. |
| Partial BOQ fill | 6,793 shares remained; OMS submitted one recovery stop for exactly 6,793 at 6.07, then the run halted with recovery pending. Later four brackets remained. |
| Unknown working BHP order | Full-account inventory refused before construction; no store changed. |

These runs prove the scripted control flow against a fake and real copied
stores. A paper Gateway run is the necessary non-synthetic check of inherited
client-1 cancellations, actual fills and timestamps, permId resolution,
commissions, conditional recovery, and final reconciliation.

## Monday 19 October 2026 order list

DS approved this exact list and its hash on 16 October 2026, conditional on
the fresh read-only inventory matching the 16 October account evidence. If
any quantity, leg, price or status differs, no close is authorised and revised
actions return to DS.

The exact approved input is
[`phase3-close-unwind-order-list-2026-10-19.json`](phase3-close-unwind-order-list-2026-10-19.json),
canonical action-list SHA-256
`e421d507b728fcd0a919f2577d702c1cdd1f6d161a243628e5cc9224f7101ae2`.
The conditional recovery stop is permitted only after a failed close leaves
shares unprotected, and never for more than the remaining broker quantity.

| Sequence | Target cancel (orderId) | Stop cancel (orderId) | Then one SELL MKT | Conditional SELL STP GTC |
| --- | ---: | ---: | ---: | ---: |
| BOQ.AX | 152 | 153 | 13,586 | 6.07 |
| ANZ.AX | 433 | 434 | 640 | 35.25 |
| SUN.AX | 167 | 168 | 3,192 | 17.20 |
| ASX.AX | 157 | 158 | 1,314 | 51.18 |
| TAH.AX | 500 | 501 | 64,229 | 0.80 |

The independent, read-only DU inventory is scheduled for 10:10–10:25 Sydney.
The script's connection and close window is 10:30–15:00 Sydney; it
rechecks the exact account before post-connection Gateway requests and
rechecks the full position and working-order book before each holding. It
halts on any divergence and never retries a close. The final independent DU
inventory and copied-store snapshot follow before shutdown.

The window is checked when each holding is armed. A new holding cannot be
armed after 14:30 Sydney. Once armed, its protective-leg cancellations,
market sell and approved recovery stop can finish after 15:00 rather than
being interrupted by the clock. Offline tests cover a 14:29 start finishing
after 15:00, a refused 14:31 start with untouched brackets, and a recovery
stop submitted after 15:00 for an armed holding.

The launch must set `QAT_MARKET=ASX` alongside the approved
recommend, paper, autonomy-off, de-lever-off, DUQ200898, client-1 and paper
port settings. The script refuses any different market.

The run uses the 19 October session and approval date in each OMS sign-off
label. The live gate refuses a change to any existing entry field before a
real cancellation.

The earlier clock-gate risk has been addressed in the script: the clock cannot
block an armed holding's approved completion or recovery. The offline
rehearsal still cannot establish the real broker's cancellation, fill or
recovery behavior; the approved Monday paper run will test those only if the
fresh account inventory matches.
