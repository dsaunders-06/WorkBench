# Phase 1 durable-order checkpoint — 24 September 2026

Draft recovery work only. This checkpoint does not approve deployment, launch, broker connection or trading. Master and operational records remain outside the change scope.

## Changes

Orders handed to the broker now have a durable application-to-broker identity record. The record contains the order context and both identifiers so a restart can retain committed exposure, match later execution evidence and preserve the independent duplicate-transmission guard.

Transmission intent is written atomically before the broker call. If that write fails, the broker is not called and order flow halts. If the broker call raises after it may have accepted the order, the outcome remains committed and uncertain in the current process and after restart; it is never restored as an unsigned proposal and is not eligible for retransmission. A corrupt identity store also halts order flow.

Unsigned proposals are deliberately not persisted. Their price, cash and risk evidence belongs to the prior session, so restoring them into the autonomy retry path would authorise stale decisions.

Late broker-ID resolution updates the durable record. Confirmed asynchronous rejection and confirmed cancellation are also persisted so restart cannot resurrect a dead order as working. A completed order identity is retired only after its cumulative fill has been saved in the fill-deduplication state.

Application and broker aliases remain available for lookup, while pending and awaiting-signoff enumeration now de-duplicates aliases. Manual-close reporting checks the durable transmission stage: an acknowledgement-loss sell remains uncertain and is never described to the operator as confirmed working at the broker.

## Test evidence

New regressions failed before their fixes for: accepted identity lost at restart; duplicate pending enumeration after restore; transmission attempted without durable intent; acknowledgement loss becoming retryable in the same process; late broker ID lost at restart; asynchronous rejection and confirmed cancellation resurrected as working; unreadable identity state failing open; completed identity retired before fill state was durable; and manual close describing unacknowledged transmission as working.

The OMS and safety suites passed 782 tests. The final full suite passed 3,752 tests with 26 skipped and 1,097 existing dependency, numerical and coroutine warnings in 324.15 seconds. Ruff, Black, Mypy (186 source files), Bandit and Git whitespace checks passed. An intermittent Qt object-deletion error occurred once after 3,751 tests had passed; both affected tests then passed in isolation, the full presentation suite passed 612 tests, and the final full run passed from a fresh temporary directory with offscreen Qt.

Independent bounded review found three defects in the first implementation: same-session acknowledgement loss became retryable after a halt reset, asynchronous rejection was not durable, and the manual closer could label an unacknowledged sell as working. All were reproduced or exposed with production-shaped settings, fixed and rechecked. The reviewer found no remaining blocker in the bounded diff review and did not independently rerun tests.

## Remaining Phase 1 limits

This checkpoint makes order intent and identity durable; it does not make execution accounting exactly-once. Entry records, cumulative-fill state, ledger event delivery and closed-trade writes still cross separate persistence boundaries. Replay preparation and absorption still use separate broker queries. Legacy entry records without an execution-accounted quantity still require explicit migration. Historical ledger corrections remain proposals and have not been applied.

The durable store records an acknowledgement-loss order as uncertain and halts. It does not guess whether the broker accepted it, cancel it automatically or clear it automatically. Broker evidence and operator review remain required to resolve that state.
