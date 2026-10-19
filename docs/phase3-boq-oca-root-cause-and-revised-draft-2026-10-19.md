# BOQ unwind halt: offline root cause and revised draft — 19 October 2026

**Review hold.** This addendum analyses the preserved 19 October evidence. It does not authorise an order, a Gateway connection, a store repair, a kill-switch reset or a recovery-record change. The revised list is a draft for DS to approve by its exact SHA-256. The original dated [run report](phase3-close-unwind-2026-10-19.md) and raw evidence have not been changed.

## What the evidence records

The table distinguishes the client-1 close script from independent client-99 inventories. Times are Australia/Sydney. For BOQ, both legacy legs share OCA group `1216552511`; their raw preflight `repr` values each state `ocaType=3`.

| Observation | Target orderId / permId `152 / 1216552512` | Stop orderId / permId `153 / 1216552513` |
| --- | --- | --- |
| 10:10:31.397505, independent preflight status-log callback | `Submitted` | `PreSubmitted` |
| Client-1 `before_start` and `before_BOQ.AX` snapshots, before the 10:30:20.360502 halt | `Submitted`, orderId 152 | `PreSubmitted`, orderId 153 |
| Between `before_BOQ.AX` and 10:30:20.360502, client-1 close attempt | One cancellation request issued for **permId 1216552512**. The script's immediate `open_orders()` read still contained that identity; it logged “has not settled”. The response status and exact callback time were **not persisted**. | No explicit cancellation request was issued by the close script. No intervening client-1 status callback was persisted. |
| 10:30:29 independent post-halt inventory | Absent from open orders; completed row `Cancelled`, **orderId 0**, permId 1216552512; empty status log, so no exact cancellation time. | Absent from open orders; completed row `Cancelled`, **orderId 0**, permId 1216552513; empty status log, so no exact cancellation time. |
| 10:32:38 independent final inventory | Still completed `Cancelled`, orderId 0, empty status log. | Still completed `Cancelled`, orderId 0, empty status log. Replacement stop 727 / 255153930 was `PreSubmitted` at 10:32:38.486878. |

There is no complete client-1 event stream in the saved run report or log. In particular, no observed `PendingCancel` callback, transition time to `Cancelled`, or exact time of the stop's cancellation can be supplied. The unit test replays the plausible intermediate state; it is a regression scenario, **not** a claim that the missing callback was observed.

The untouched outside-Git sources are the preflight inventory (SHA-256 `b4dd5757f569e4de9abda4cff060c184488c79a1a5049d490ca5c8551cc1f48a`), client-1 `run/run.json` (`5f850501992f2ed6b6302d9f17361369576922c7d2b0c2358e13fc0954894d8d`) and `close-run.log` (`c7626282ef9984a172418743f018b9c6b0002c02cdfbd5aeae837f29efa02c37`), post-halt inventory (`6a5ba881077d50dac03ebfc418e14d64303fc59155538b9b0ee6bbf200a0c022`) and final inventory (`53dd49b7140d1f8ce888b3f1c123724451083a8f8bdf7a64e9b9bb8d935b8082`). Absolute paths and the rest of the evidence hashes are in the original [manifest](phase3-close-unwind-2026-10-19-manifest.json).

The unsettled judgment came from `OMS._release_protective_legs`: it sent the target cancel, made **one immediate** working-order read, and returned failure when the same application-facing order identity was still present. There was no wait or timeout. `IBAdapter.open_orders()` represents an IBKR leg by `permId` when available, so the `orderId 0` completed rows did **not** cause the original decision. The stop disappeared after the halt; it was not judged unexpected by the running close script. Its later absence triggered the separately approved, one-off protective recovery.

The stop's cancellation is **consistent with the OCA group and is the strongest explanation**, but the missing client-1 callbacks prevent proving the broker's causal path. IBKR says that a **client cancellation before execution automatically cancels other OCA members**, while a system rejection or cancellation does not ([IBKR OCA glossary](https://www.interactivebrokers.com/campus/glossary-terms/one-cancels-all-oca-order/)). Its [OCA type table](https://www.interactivebrokers.com/campus/?p=195739&post_type=ibkr-api-page) identifies type 3 as proportional reduction of the other orders **after an execution**, with no block; that type does not negate the separate client-cancellation rule. There was one client target-cancel request, both legs had the same OCA group and `ocaType=3`, both later appeared `Cancelled`, and no BOQ execution was returned. A distinct broker-side event cannot be ruled out from the saved status data.

## Recovery source and identity

Commit `593bce0b61b48ffec65afeaacfd79fc1e8d78fca` preserves the [exact one-off recovery Python body](../scripts/phase3_boq_recovery_20261019.py.txt) unchanged, with its [invocation note](phase3-boq-recovery-code-2026-10-19.md). The script was executed once through standard input to `.venv/Scripts/python.exe -B -` with the pinned QAT/IBKR paper settings and an outside-Git one-shot marker; it must not be rerun. The final independent inventory confirms BOQ SELL STP GTC orderId **727**, permId **255153930**, quantity **13,586**, stop **6.07**, and no target.

The copied `ib_pending_legs.json` still has orderId 727 but permId 0, `resolved=false`. Restart by itself does **not** resolve it. `IBAdapter.pending_identity_reason()` reads the broker's open orders (then executions if needed), calls `PendingLegStore.resolve_match()`, and persists the permId only if orderRef, account, conId and clientId match. The proposed future close script explicitly invokes that method after connection and refuses to continue unless the durable record resolves to **255153930** with orderId 727. This is a conditional code-path claim, not a claim that the live store was changed in this offline task.

## Proposed fix and current gates

Commit `f7eb5f21b65ce7299b06c1975ccfc79ba60bf7d7` on `unwind/close-script` preserves both `orderId` and `permId` in translated resting orders and matches either nonzero identity. During a protective release the OMS now waits briefly for the requested cancel to settle. If the paired leg from the same OCA group is already gone, it does not send a redundant second cancel; it proceeds toward the market sell as soon as the symbol's working book is clear. A still-working requested leg times out closed after two seconds, and an unexplained disappearance still fails closed. BOQ's revised book requires only the single 727 stop; the guard accepts a cancel of permId 255153930 followed by one exact 13,586-share market sell. The script refuses the old approved list and requires the revised inventory. Commit `c3ec673e7fa9cb5b1bdf573bfd9092bdb320ea77` adjusts one pre-existing failure-injection fixture so its stop remains visible until its intentionally failing second cancel; its assertions are unchanged.

Commit `9a24d1319d42ed053c4225f00b81592bf43aa3c0` adds an actual IBKR completed-order read to the confirmation path. It matches terminal rows by permId even when IBKR reports `orderId 0`. With that response available, the OMS requires `Cancelled`/`ApiCancelled` for each disappeared leg before a sell; a `Filled` or `Inactive` leg blocks the sell. The offline replay uses separate open-order and completed-order responses, including a filled OCA partner that must refuse the exit. If the requested leg lacks completed-order confirmation when the two-second bound expires, or an absent OCA partner lacks it when checked, the release fails closed and the existing protection-recovery path applies. No claim is made that the missing 19 October client-1 callbacks can be recovered from these tests.

Commit `0b0853b0354d45e53c92b2bc41512e0730291f4f` covers the intervening OCA state: if the target is settled but its partner still appears `PendingCancel`, the OMS waits for that partner to settle rather than sending a duplicate cancellation. A two-second bound retains the fail-closed recovery path if it does not settle. The replay confirms no second cancel is sent while the partner is pending.

The persisted kill switch is tripped. `PositionCloser.close_position()` rejects a manual close before cancelling anything; `RiskEngine.evaluate_exit()` also rejects exposure-reducing sells while tripped. An operator-attributed `KillSwitch.reset()` is therefore required before a future OMS close, but a reset alone is not sufficient: BOQ's recorded recovery plan must first be assessed against fresh broker positions, all open/completed orders, executions, the 727 identity, and QAT's stores, then cleared through the verified recovery path. DS must approve the revised order list and the exact operational reset/recovery sequence first. **No reset or recovery-record change occurred here.**

## Revised draft for DS

The canonical [19-action JSON list](phase3-revised-order-list-2026-10-19.json) has SHA-256 **`acc578fa5df3bf65a6f9372a796d860a8dc500b686a4ceced50423db6a963978`**. Canonical bytes are `json.dumps(actions, sort_keys=True, separators=(",", ":")) + "\n"`, UTF-8. `.gitattributes` prevents line-ending conversion of this approval artifact. `CANCEL` rows for an OCA pair are planned identities: the second cancellation request is skipped when that partner is already confirmed gone after the first. `RECOVERY_ONLY` rows are conditional protection limits, not routine close steps.

| Symbol | Normal sequence | Conditional recovery ceiling |
| --- | --- | --- |
| BOQ.AX | Cancel stop **727 / 255153930**, confirm; SELL MKT **13,586** | SELL STP GTC up to 13,586 at 6.07 |
| ANZ.AX | Cancel target **433 / 1216558933**; confirm partner stop **434 / 1216558934** gone or cancel it; SELL MKT **640** | Up to 640 at 35.25 |
| SUN.AX | Cancel target **167 / 1216552521**; confirm partner stop **168 / 1216552522** gone or cancel it; SELL MKT **3,192** | Up to 3,192 at 17.20 |
| ASX.AX | Cancel target **157 / 1216552515**; confirm partner stop **158 / 1216552516** gone or cancel it; SELL MKT **1,314** | Up to 1,314 at 51.18 |
| TAH.AX | Cancel target **500 / 579188642**; confirm partner stop **501 / 579188643** gone or cancel it; SELL MKT **64,229** | Up to 64,229 at 0.80 |

The old 19 October approval hash `e421d507b728fcd0a919f2577d702c1cdd1f6d161a243628e5cc9224f7101ae2` cannot authorise this list. All five positions remained held in the final saved inventory; this draft requires a fresh independent read-only book and new DS approval before any further close. No Gateway request or order was made during this offline investigation.

As an offline consistency check, the revised script's exact position/order inventory gate accepted the untouched final client-99 inventory (`positions_cache` plus `all_open_orders`) with all five holdings and nine working orders. That verifies the draft's starting identities against the saved state; it is not a current broker check.

## Verification and review state

The final `unwind/close-script` head is `0b0853b0354d45e53c92b2bc41512e0730291f4f`. Its full local suite passed with **4,569 passed and 26 skipped**; Ruff, Black, mypy and Bandit passed. The affected focused tests passed (**116 passed**). [CI run 39183849455](https://github.com/dsaunders-06/WorkBench/actions/runs/39183849455) completed successfully for that exact head. The evidence branch is held for review; this addendum and revised draft are local commits and have not been pushed to the public repository.
