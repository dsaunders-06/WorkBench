# Phase 3 paper unwind — 19 October 2026

**Halted on the first BOQ target cancellation. No market sell or fill. Conditional BOQ stop recovery verified. Hold unmerged for DS review.**

## Authority and gates

Reviewed head: `3905bb6854a9140eb2caa7f776dbcb57210304a7`, clean `unwind/close-script`. CI [38856023111](https://github.com/dsaunders-06/WorkBench/actions/runs/38856023111) was independently verified completed/success for that exact head before the Gateway inventory. Canonical approved action-list SHA-256: `e421d507b728fcd0a919f2577d702c1cdd1f6d161a243628e5cc9224f7101ae2`.

The client-99 read-only independent inventory at 10:10:31 Sydney found exactly DUQ200898, five holdings and ten orders. The entire pinned account book matched. Positions, all-client open orders, completed orders and executions were requested through the existing account-checking read-only guard; orders were not bound.

Launch-only settings verified before connection: broker IBKR, ASX, execution recommend, paper, autonomy false, de-lever sweep false, DUQ200898, client 1, 127.0.0.1:4002. Stored settings were unchanged. Raw settings evidence and all broker responses remain outside Git.

## Halt and conditional protection recovery

The close script was launched once after 10:30 Sydney. The BOQ exit was proposed and rejected at 10:30:20 after target cancellation failed to settle. The script finished halted at 10:30:20.360502. Only target permId 1216552512 was recorded as cancellation issued; no original stop cancellation or market sell was issued by the close sequence. Later holdings were never armed.

Independent post-halt inventory at 10:30:29 found both original BOQ legs Cancelled in completed orders, absent from working orders, with all 13,586 BOQ shares still held. The broker returned orderId 0 for these completed rows and supplied empty status logs. Exact cancellation timestamps are unavailable. Why both legs disappeared after one requested cancellation is not established; an OCA side effect is a hypothesis only.

No close retry occurred. The persisted OMS recovery plan was invoked once through the existing `recover_exit_protection` path, without restarting the close sequence or signal components. An additional local boundary denied further cancels and allowed only one BOQ SELL STP GTC, exactly 13,586 shares at the pinned 6.07, with DU/account/contract checks. The existing ApprovedBroker guard was rearmed solely for recovery, recording the previously issued cancellation count of one; it did not issue another cancellation. No repository code was changed.

Recovery began at 10:32:25.115023 Sydney and protection was verified by 10:32:27.890100. Replacement orderId **727**, permId **255153930**, PreSubmitted. A separate final client-99 read-only inventory at 10:32:38 confirmed it. The BOQ target was not recreated.

## Per-holding outcome

| Symbol / conId | Before → final shares | Target orderId / permId | Stop orderId / permId | Outcome |
| --- | --- | --- | --- | --- |
| BOQ.AX / 11470910 | 13,586 → 13,586 | 152 / 1216552512 | 153 / 1216552513 | Original target and stop Cancelled; replacement stop 727 / 255153930 at 6.07, PreSubmitted. |
| ANZ.AX / 4109645 | 640 → 640 | 433 / 1216558933 | 434 / 1216558934 | Not armed; original target Submitted and stop PreSubmitted unchanged. |
| SUN.AX / 12101107 | 3,192 → 3,192 | 167 / 1216552521 | 168 / 1216552522 | Not armed; original target Submitted and stop PreSubmitted unchanged. |
| ASX.AX / 4354508 | 1,314 → 1,314 | 157 / 1216552515 | 158 / 1216552516 | Not armed; original target Submitted and stop PreSubmitted unchanged. |
| TAH.AX / 4506346 | 64,229 → 64,229 | 500 / 579188642 | 501 / 579188643 | Not armed; original target Submitted and stop PreSubmitted unchanged. |

## Final working orders

| Symbol | orderId / permId | SELL type / quantity | Limit / aux price | TIF | Status | Delivered status timestamp (UTC) |
| --- | --- | --- | --- | --- | --- | --- |
| ANZ | 433 / 1216558933 | LMT / 640.0 | 41.24 / 0.0 | GTC | Submitted | 2026-10-18T23:32:38.485875+00:00 |
| ANZ | 434 / 1216558934 | STP / 640.0 | 0.0 / 35.25 | GTC | PreSubmitted | 2026-10-18T23:32:38.484692+00:00 |
| ASX | 157 / 1216552515 | LMT / 1314.0 | 65.17 / 0.0 | GTC | Submitted | 2026-10-18T23:32:38.484692+00:00 |
| ASX | 158 / 1216552516 | STP / 1314.0 | 0.0 / 51.18 | GTC | PreSubmitted | 2026-10-18T23:32:38.485875+00:00 |
| BOQ | 727 / 255153930 | STP / 13586.0 | 0.0 / 6.07 | GTC | PreSubmitted | 2026-10-18T23:32:38.486878+00:00 |
| SUN | 167 / 1216552521 | LMT / 3192.0 | 21.27 / 0.0 | GTC | Submitted | 2026-10-18T23:32:38.486878+00:00 |
| SUN | 168 / 1216552522 | STP / 3192.0 | 0.0 / 17.2 | GTC | PreSubmitted | 2026-10-18T23:32:38.486878+00:00 |
| TAH | 500 / 579188642 | LMT / 64229.0 | 1.075 / 0.0 | GTC | Submitted | 2026-10-18T23:32:38.485875+00:00 |
| TAH | 501 / 579188643 | STP / 64229.0 | 0.0 / 0.8 | GTC | PreSubmitted | 2026-10-18T23:32:38.485875+00:00 |

All nine final orders are client 1 / DUQ200898. The four later holdings and their eight bracket orders match every pinned inventory field. All five holdings remain at their original quantities. Delivered status timestamps are snapshot observation times, not proof of original exchange event times.

## Fills, stores and reconciliation

Preflight, post-halt and final `reqExecutions` returned no executions. There are no unwind execIds, fill times, fill prices or commissions to report. No fill or flat position is inferred. `closed_trades.csv` remains at 12 rows and no close row was added. Startup migrated five legacy entry quantities, retired four flat stale entries COH/JHX/TWE/WOW and backed up the entries. It migrated/backed up the closed-trade CSV schema. Five held entries remain.

Decision journal: 477 → 481 rows; risk decisions: 4,958 → 4,959. BOQ exit application ID `97e58e69a11a4c1d8f21b26d896b8b8d` has proposed/rejected records at 10:30:20 Sydney, with the required sign-off label `DS-approved instruction 2026-10-19, order list e421d507b728fcd0a919f2577d702c1cdd1f6d161a243628e5cc9224f7101ae2, executed by agent`. Recovery application ID `24b3e1b783ef4066b6a8329e4d3700c4` has proposed/signed-off records at 10:32:26 Sydney; existing OMS operator label is `exit-protection-recovery`.

The recovery path tripped the existing kill switch when loading its persisted pending recovery: `pending exit protection recovery restored after restart`. It remains tripped. BOQ remains in `exit_recovery.json` at stage `working`, quantity 13,586 and stop 6.07. Broker protection was independently verified; the record was not cleared and no safety reset was performed. The close loop did not reach its post-close clean reconciliation checks: clean QAT reconciliation is not claimed. Startup adoption matched the five broker holdings. The run log preserves the 886-hour broker-fill watermark warning.

Additional local-state findings: `absorbed_fills.json` changed from 23 historical absorbed records to 0, with the old watermark retained and a recovery application-ID alias added. No execution was returned during this run; this store change must not be mistaken for new fills, and its effect requires review before restart. `ib_pending_legs.json` records recovery orderId 727 but permId 0 / unresolved, while the independent broker inventory resolves it to permId 255153930. `inflight_orders.json` retains the recovery as accepted/transmitted. No store repair was attempted.

Store differences before → final:

- added: `closed_trades.csv.bak-pre-schema-1792366220146368200`, `exit_recovery.json`, `ib_pending_legs.json`, `inflight_orders.json`, `open_position_entries.json.bak-pre-quantity-migration`
- changed: `absorbed_fills.json`, `closed_trades.csv`, `decision_journal.csv`, `kill_switch.json`, `open_position_entries.json`, `risk_decisions.csv`
- removed: none

## Evidence hashes and checks

Raw evidence root: `C:\Users\mailm\Documents\Codex\phase3-close-unwind-20261019`. Before, after-halt and final store copies include available application logs inside each store copy. No separate app-root log folder exists. `after-stores` predates recovery; `final-stores` is authoritative for the final state. Check logs and runner output are outside Git. The companion manifest hashes all preserved evidence files (excluding disposable pytest temporary files), including every copied store/log file. Only this report and its path/hash manifest are committed.

- Preflight inventory: `C:\Users\mailm\Documents\Codex\phase3-broker-inventory-20261019-pre\phase3-phase3-broker-inventory-20261018T231031568955Z.json`; SHA-256 `b4dd5757f569e4de9abda4cff060c184488c79a1a5049d490ca5c8551cc1f48a`.
- Post-halt inventory: `C:\Users\mailm\Documents\Codex\phase3-broker-inventory-20261019-post\phase3-phase3-broker-inventory-20261018T233029879170Z.json`; SHA-256 `6a5ba881077d50dac03ebfc418e14d64303fc59155538b9b0ee6bbf200a0c022`.
- Final inventory: `C:\Users\mailm\Documents\Codex\phase3-broker-inventory-20261019-final\phase3-phase3-broker-inventory-20261018T233238490890Z.json`; SHA-256 `53dd49b7140d1f8ce888b3f1c123724451083a8f8bdf7a64e9b9bb8d935b8082`.
- Run report: `C:\Users\mailm\Documents\Codex\phase3-close-unwind-20261019\run\run.json`; SHA-256 `5f850501992f2ed6b6302d9f17361369576922c7d2b0c2358e13fc0954894d8d`.
- Recovery report: `C:\Users\mailm\Documents\Codex\phase3-close-unwind-20261019\conditional-recovery.json`; SHA-256 `ecc388711492706a585e3533c131eb75668b7328bc69d008123482c5ceee8578`.

Full offline pytest: **4,559 passed, 26 skipped**, 1,096 warnings, 537.32 seconds. Ruff, Black, mypy and Bandit all exit 0. These checks ran on unchanged reviewed code while waiting for 10:30. No source or test files changed. CI for the evidence commit is verified after push and identified with the final branch head in the review handoff.

## Review and scope

Branch `evidence/phase3-close-unwind-20261019` starts at the reviewed head. Unwind incomplete; do not retry or merge. DS must review the unconfirmed target cancellation, both original BOQ legs disappearing, the separately invoked pinned conditional recovery, and the retained kill-switch/recovery state. Final account inventory differs from the approved starting book: further close actions need revised DS approval. No fix, card path, entries, ASX-only cleanup or other Phase 3 work was performed.
