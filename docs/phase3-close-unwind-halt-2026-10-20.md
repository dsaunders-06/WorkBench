# Phase 3 paper close: 20 October preflight halt

The Tuesday run halted at independent reconciliation, before verify-only, recovery-plan clearance, kill-switch reset, cancellation, or order placement. The later close was not started. Hold this branch unmerged for DS review.

The run used `unwind/close-script` commit `4632d655d8ae28c9557623a8e20526bc6167d6a2`, confirmed by the auditor and green CI [39337739969](https://github.com/dsaunders-06/WorkBench/actions/runs/39337739969). The approved action-list hash was `acc578fa5df3bf65a6f9372a796d860a8dc500b686a4ceced50423db6a963978`.

At 10:09 AEDT, a separate account-checking, read-only paper Gateway client captured positions, balances, all open and completed orders, and executions. Position and working-order identity, quantity, price, status, and OCA fields matched the 19 October final book. The completed-order response differed: it omitted two previously returned cancelled rows. Marked account values also differed. Under the runbook's rule to halt when any fact differs or cannot be established, no later step was attempted.

The raw current inventory, including detailed account information, remains outside Git at `C:\Users\mailm\Documents\Codex\phase3-broker-inventory-20261020-pre\phase3-phase3-broker-inventory-20261019T230935609326Z.json`, SHA-256 `b10a276716327314bc26106b0d0819106070d511a405c0e2e8b75d92339ce4c0`. The comparison baseline is the final 19 October inventory, SHA-256 `53dd49b7140d1f8ce888b3f1c123724451083a8f8bdf7a64e9b9bb8d935b8082`. A separate detailed review note and proposed exact action list are outside Git.

No close fills occurred in this attempt. The read-only execution request returned none, so there are no new execIds, execution times, or commissions to report. Verify-only was not invoked; this attempt did not resolve the pending identity, clear the exit-recovery plan, or alter the kill switch. Store contents and post-halt broker state were not reverified after the step-1 halt. The account was not flattened.

Production files changed: none. Scripts changed: none. Tests changed: none. This evidence branch adds only this redacted document. DS must review the changed completed-order response and account values, and approve an exact list and procedure before any reset or close. The detailed live book must remain outside the public repository.
