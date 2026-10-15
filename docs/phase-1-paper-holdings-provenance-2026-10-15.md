# Paper holdings provenance and test dependency — 15 October 2026

This is an offline investigation of the five holdings in the operator's 14
October DU snapshot. No Gateway request, order, application, OMS or poller was
started. The local QAT `data` directory was copied to
`C:\Users\mailm\Documents\Codex\phase1-holdings-copy-20261015\data`; only
the copy was read. It contains 51 files / 42,146,973 bytes. The original
pre-freeze decision journal, entry record and logs are the evidence below.
The copy contains no OMS database, broker execution ledger with complete
symbol-tagged fills, or consolidation ledger. The `absorbed_fills.json` rows
have execution IDs, times, sizes and prices, but no symbol or side, so this
report does not assign those rows to a holding by time coincidence.

## Development freeze

**12 September 2026.** Commit `d39debc` at 18:38 AEST is titled “Freeze for
the design recovery audit: plan, Claude error log, handover.” The subsequent
handover states “FROZEN since 12 September” in its status table
(`docs/HANDOFF.md:82`) and repeats this at line 6762. The M175 build and the
12 September 10:52 fill-basis repair precede the freeze. Trading was separately
suspended on 14 September; that is not the development-freeze date. The
operator's 14 October snapshot confirms the quantities today, but the origin
claims below use records dated before the 12 September freeze.

## Holdings

All five entries were produced by the **Phase 1 `swing` signal → OMS →
`autonomous-executor` sign-off** path in paper mode. The journal's `price`
column is the proposal/reference price, not proof of the fill. The entry file
is the fill/basis evidence where stated. Times below are AEST (UTC+10).
These are legacy orders predating the 10 October intent register; none has a
DS-approved Phase 3 exit plan. This report neither adopts them into the new
plan nor authorises QAT to manage or close them.

| Holding | Origin with pre-freeze evidence | Pending tests that require this exact holding | Recommendation |
|---|---|---|---|
| BOQ 13,586 | 25 Aug 10:30. Application order `d7877ec89ea34e75804a2c561f0d99a5`; proposed/reference AUD 6.39, signed by `autonomous-executor` for 13,586. `open_position_entries.json` records AUD 6.38 with `price_source=fill`. Broker order ID and full execution breakdown are absent from the copied journal and logs. | None identified. A non-flat book exercises portfolio checks generally, but no approved test names BOQ. | **Close after DS approves a safe unwind and ledger/working-order reconciliation**; do not retain solely for an unnamed test. |
| ANZ 640 | 25 Aug 13:34 proposal, signed 14:04. Application order `56d67b4e6012439fa3e3c588689a8de3`; reference AUD 37.24, quantity 640. The handover (`docs/HANDOFF.md:4278`, `:4449`) attributes that size to aggregate-risk headroom. Entry file records AUD 37.16 with `price_source=fill`. Broker ID and full executions are absent. | None identified; Phase 4 sector checks can use any accurately classified paper holdings. | **Close after DS-approved reconciliation**; not needed to preserve a Financials concentration for a test. |
| SUN 3,192 | 25 Aug 11:34. Application order `fdb77a966c234545b99da813c9e80257`; reference AUD 18.55, signed for 3,192. Entry file records weighted fill AUD 18.6806484962406 with `price_source=fill`. Broker ID and full executions are absent. | None identified. The planned Policy A consolidation test needs a position held over a relevant ex-date; this position was opened **after** 17 Feb 2025. | **Close after DS-approved reconciliation**; do not preserve it as evidence of the 2025 event. |
| ASX 1,314 | 25 Aug 10:32. Application order `8cd96e49cf07437fb4c9c7fba8198f4e`; reference AUD 55.84, signed for 1,314. Entry file records weighted fill AUD 56.42420091324202 with `price_source=fill`. Broker ID and full executions are absent. | None identified; no planned test names this holding. | **Close after DS-approved reconciliation.** |
| TAH 64,229 | 4 Sep 14:28. Application order `a82b2625c6f548739af2164b3f00b435`, broker **permId** `579188641` (the identity returned by `from_ib_trade`), signed by `autonomous-executor`. The OMS capped 70,693 proposed shares to 64,229; reference AUD 0.89. The pre-freeze handover (`docs/HANDOFF.md:1324`) gives broker-inclusive basis about AUD 0.8908. The 12 Sep entry file says AUD 0.89 with `price_source=null`, so a precise execution fill price cannot be certified from it. | None identified. Its large share count exposed the broker-size-preset misconception, already recorded in the handover; it need not remain open to keep that evidence. | **Close after DS-approved reconciliation**, with particular care for its large GTC protective quantity. |

The decision journal and entry file show each current position was opened
between 25 August and 4 September **2026**. Thus the current SUN 3,192-share
position was **not held across** the 17 February **2025** 0.8511
consolidation. The resemblance to `3,750 × 0.8511` does not establish an
acquisition or adjustment. No cash-in-lieu or consolidation event for these
five appears in the copied pre-freeze QAT stores; the announcement cache is
`{"announcements": []}`. This proves only what QAT recorded. A complete
broker statement and the corporate-action authority would be needed to
exclude all external events or older account holdings.

The planned manual-management switch and exit alerts are keyed to a Phase 3
**card ID** (`operational/exit_alerts.py`); the shadow record also starts with
cards. These five Phase 1 positions have no Phase 3 card or approved exit plan.
The planned QAT-managed exit, entry-transmission and paper-rehearsal tests
therefore require a newly approved card/position, not one of these holdings.
Phase 4 limit tests need a correctly reconciled account state, not particular
symbols. Halt and Policy A tests require a dated authority event and a
position held across it; no such dependency is recorded for these five.
Retaining one as a future test fixture would be a new DS plan, not an existing
dependency.

## If a holding is closed

With QAT running and receiving a confirmed sell execution, OMS updates its
tracked quantity (`oms.py::_account_execution`), the bridge removes a fully
closed entry (`signal_bridge.py::_on_fill`), and the trade ledger records a
closed trade (`trades.py::_on_fill`). Reconciliation then compares the tracked
and broker quantities (`oms.py::check_reconciliation`); protective legs must
also be absent or the resting-order scan can flag an orphan.

With QAT stopped, a TWS closure changes the broker account but **does not
immediately change** `open_position_entries.json`, the decision journal or
the closed-trade ledger. At a later startup, `OMS.adopt_broker_positions`
seeds its reconciliation baseline from the broker, and missed-fill replay
tries to recover the sell using the saved watermark and entry-symbol watch
list. If the broker no longer returns the execution or attribution fails,
flat-versus-flat quantity reconciliation alone cannot prove that the closure
was recorded; a stale entry and missing closed trade can remain. The copied
pre-freeze entry file lacks durable quantity, fill ID and order ID fields now
supported by the code. A manual exit must therefore include explicit
confirmation of the broker fill, cancelled/absent protective legs, the entry
record, closed-trade row and reconciliation result. This report authorizes no
closure.

## Evidence limits

The copied store has no complete broker statement or current broker order
inventory. No historical positions before August 2026, exact fill price for
TAH, full broker execution breakdown for the other four, or cash-in-lieu
receipt can be certified from it. The 14 October snapshot supplies the five
current quantities but is not used to invent acquisition details. Relevant
copy SHA-256 values: `decision_journal.csv`
`fcc60f8163e21d197d3a491200a452999d2c30efd3f0c792b97a2481ae0cd4ba`,
`open_position_entries.json`
`b389974e6286eaebc871e1610ce0ebab97348634abc77875a546de955b87a0e0`,
`absorbed_fills.json`
`3437aabf882abe5f38e2920c2b922bcdef0caf904dc9fd859b9d1dfae0e9b0a5`,
and `corporate_announcements.json`
`aa8aca345812595142e0a37d2084e825377cf1887a6ae95b124688aacbd4341d`.
Log copy hashes are `qat.log`
`ea3452e003ab59760d08a3bc1378c91feb56b53d78011ba80925eb0764432b70`,
`qat.log.1`
`a3d86300fbf77ece446cc4c488aa86569fe2489fd9c40176834623caea4e87b7`,
`qat.log.3`
`cd4d00a5992c7d5259ab39072a66a0ad8988a988e1e3d657ce5a5661e25f1f4a`,
and `qat.log.4`
`1419a301dbeffac5ed540c11e5b9ed9bbf1f0eb72b42a60f708aeae97af2d0b9`.
