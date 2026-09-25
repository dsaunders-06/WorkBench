# Phase 1 historical correction checkpoint

Date: 25 September 2026

Status: tool implemented, dry run verified, and authorized operational correction applied.

## Safety boundary

The correction command is bound to the approved proposal SHA-256. That proposal in turn binds the exact broker statement and source-ledger hashes. A changed proposal, statement or ledger is refused before a candidate row is produced.

The original ledger row must match every proposed source field exactly, and its symbol, order id and opening timestamp must select exactly one row. Missing, repeated or ambiguous matches are refused. The broker quantity, weighted prices, commissions and realised net P&L must also reconcile internally using decimal arithmetic.

Dry run is the default. It writes the candidate only to temporary scratch space, audits the complete candidate ledger and removes the scratch file. Applying requires both `--apply` and the correction id printed by the reviewed dry run. It also requires the application process to be provably stopped.

## Corrected interpretation

The uniquely matched later TNE.AX round trip changes from 60 to 3,051 shares. Entry and exit prices and commissions come from the broker statement. Gross P&L, net P&L, return percentage, risk per share and gross/net R multiples are recalculated with decimal rounding from the stored inputs.

The source ledger's `swing` strategy is retained with explicit provenance that the statement does not verify it. The existing `target` exit reason is cleared because the statement cannot establish why the position closed. Other rows and the recorded timestamps are unchanged.

The corrected net loss is AUD 7,076.61, compared with AUD 139.17 in the source row. This removes the documented AUD 6,937.44 understatement for that round trip. Other absent broker round trips remain outside this bounded correction.

## Apply and recovery behavior

Before replacement, the command creates and verifies a byte-for-byte backup beside the ledger. It stages and audits the corrected CSV and a JSON audit journal containing the evidence hashes, before/after rows, provenance and resulting ledger hash. A repeat attempt, conflicting backup, conflicting journal, changed ledger or leftover staging path is refused.

The ledger is replaced atomically. A failed post-write verification or journal publication restores the original ledger from the verified backup. If automatic restoration itself fails, the backup is retained and the command reports the exact manual restore file.

## Preserved-evidence dry run

The dry run validated these immutable inputs:

- proposal SHA-256: `58aaae8c02c81efe61f9a0e3c0b949504be73a49d5f34bda0fe54dada1f54ccc`
- statement SHA-256: `8e578080943089d79d3ac6f2c90d802fbea533af250372259d0edb4df5d40e69`
- ledger SHA-256: `688b709185cb1f8fef552b6af57fb00fe195c2488003ea95a0c05d70c70c7669`
- correction id: `tne-20260903-58aaae8c02c8`

The candidate ledger audit was clean. A second hash check confirmed the preserved source ledger remained unchanged. At this dry-run checkpoint, the operational AppData ledger had not yet been read or written.

## Authorized operational application

The operational ledger was subsequently read with elevated local access while the QAT application was stopped. Its SHA-256 exactly matched the approved source hash before application. The same dry run passed directly against that file, after which correction `tne-20260903-58aaae8c02c8` was applied with the reviewed confirmation id.

- before and backup SHA-256: `688b709185cb1f8fef552b6af57fb00fe195c2488003ea95a0c05d70c70c7669`
- corrected ledger SHA-256: `cd801a345153545d7076a1bc4e4eef538fc78720fe0eb69a19f3c9a84b97863f`
- post-write ledger audit findings: zero
- leftover staging or rollback files: zero

The journal independently records the same before/after hashes, unique target and corrected values. Windows still reported no running QAT application after verification. The recovery build was not launched and no broker order was placed, modified or cancelled.

## Verification

- Ten correction tests cover decimal recalculation, all three evidence hashes, ambiguous selection, byte-identical backup, audit journal, repeated-run refusal, changed-ledger refusal, automatic rollback, read-only default and explicit apply confirmation.
- The performance suite passed 240 tests.
- Ruff, Black, Mypy and Bandit passed for the correction implementation.
- A date-sensitive pre-existing cumulative-fill test was found when its fixed August fixture crossed the 30-day receipt-retention boundary. The test now uses the OMS's existing injected clock and passes without changing production behavior.
- Complete repository suite: 3,777 passed, 26 skipped and 1,097 existing warnings in 346.88 seconds.
- Ruff passed; Black left all 659 tracked Python files unchanged; Mypy passed over 187 source files; Bandit passed with its existing comment-parser warnings; Git whitespace checks passed.

## Remaining boundary

The bounded historical correction has now been applied to the hash-matched operational ledger and independently verified. This checkpoint does not deploy or launch the recovery build, resume trading, merge the draft pull request or approve `master`.
