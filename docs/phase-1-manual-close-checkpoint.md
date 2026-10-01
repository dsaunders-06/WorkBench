# Phase 1 manual-close checkpoint — 23 September 2026

Draft recovery work; not deployment approval. This extends the published lifecycle checkpoint and preserves master and the operational snapshot.

## Changes

Manual close now uses OMS sign-off for protective cancellation, exit transmission and recovery. Its independent cancellation and re-protection implementation has been removed. The manual managed-position checks remain: no partial-close request, no halt override, no short sell, and an entry record and visible managed protection are required.

The former `legs_already_released` argument has been removed from `submit_exit_order`. No caller can assert that protection was handled elsewhere and bypass the shared release transaction.

The shared sequence records recovery intent before cancellation, waits for target cancellation before touching the stop, and refuses an unverifiable order book. A collapse of the entire account order book when other symbols' orders were present is retained as uncertainty, including during recovery. The shared recovery restores only the captured stop and waits for verification rather than claiming an accepted request is confirmed protection.

The operator result distinguishes cancellation requests from confirmed removals. Evidence survives a broker order-ID change. A partially filled working sell reports confirmed shares and remaining shares. A transmission exception does not authorise another sell or replacement stop.

Restoring a partially filled entry now seeds the per-order commission accumulator. The reproduced $6 + $6 minimum-commission duplication for one order is fixed.

## Test migration decisions

The manual-close tests retain their broker failure scenarios but now exercise the real OMS. Former fake-only expectations were updated where they encoded the unsafe independent path:

- Risk refusal leaves the original legs untouched; it must not cancel and then restore them.
- An unsettled target cancellation prevents the stop cancellation.
- A changed holding refuses the stale full-close quantity rather than silently resizing the approved order.
- Recovery submits only the captured stop, not another target bracket; acceptance remains pending verification.
- A broker transmission exception is uncertain, not proof that replacement protection can be submitted.
- The result identifies only the cancellations actually issued before refusal.

New regressions were observed failing before their fixes: risk failure after protection removal, stop cancellation before target settlement, missing recovery intent, lost cancellation facts after broker rekey, partial-fill wording, and repeated commission floor after restart.

## Validation and limits

Focused manual, dashboard and accounting checks passed. The final full suite passed 3,741 tests with 26 skipped and 1,097 warnings in 382.29 seconds. Ruff, Black, Mypy (185 source files), Bandit and Git whitespace checks passed. The warnings are the existing dependency, numerical and coroutine warnings recorded in the test output.

Independent bounded review found the commission and two operator-result defects above. They were fixed and the reviewer reported no remaining blocker from that bounded review; the reviewer did not independently rerun tests.

Phase 1 still requires crash-atomic ledger/fill/entry persistence, coherent replay across changing broker snapshots, durable pending-order identity and explicit migration of legacy records. The historical comparison exists as a separate proposal; no historical records have been rewritten. Passing these tests does not establish those remaining guarantees.
