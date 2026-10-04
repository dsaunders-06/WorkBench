# Phase 2C review correction report

4 October 2026, Australia/Sydney. Submitted for operator review on `recovery/phase-2-authoritative-strategy`; baseline `6f6f05a`. Corrections and diagnostic investigation are authorized by the operator review, with a push followed by a hold.

| Item | Result |
| --- | --- |
| 1 / F3 | Nine production asserts replaced with explicit exceptions; four enum and seeded simulation suppressions have reasons. Black ran on news.py (26.5.1 leaves it unchanged). All 28 Phase 2 task verification sections now require Bandit and whole-tree Black. |
| 2 / F2 | The stress floor now predicts each holdout horizon's average entry rate from the joint 3/6/12-month moving-block model, preserving partition boundaries. The Poisson-like regression binds on validation, rather than single-month observation variance. |
| 3 / F4 | Conservative and explicit recovery replay results supply edge and terminal gate provenance. Terminal-only failure is classified before edge FAIL; unrelated portfolio/tail failures cannot be hidden. Same-cost recovery pairs preserve identities/economics; cross-cost pairs use stable signal identity so legitimate resizing remains valid. Missing recovery evidence cannot pass. |
| 4 / F5 | Every QUALIFIED entry requires explicit raw structural invalidation, including the analytical single-pattern branch; both stop fallbacks are removed. |
| 5 / F6 | Both post-fill diagnostics share the engine's three-year window and validity checks. Failed history or zone construction records an abstention and evidence. |
| 6 / F7 | Exit-session onsets are included, with exact removal of scheduled proceeds and independent sparse/full-ledger parity. The operator amendment is recorded in the specification and plan. |
| 7 / F1 | Diagnostic matrices reproduce persistent-shock size inflation. Complete-null month-clustered family false-positive rates are 15.83%, 23.17%, 28.00% for 3/6/12-month shocks; quarter rates are 5.67%, 14.00%, 23.33%. Aligned block rates are 5.67%, 5.50%, 0%, with low power at six months and no usable three-block power at twelve. The independent-month control is 5.17% for month clustering. These are short diagnostics, not an accepted method audit. |

The 24-cell conservative matrix took 55.81 seconds wall time (216.19 summed cell seconds); the retained raw-kernel matrix took 45.61 seconds. Each uses 600 outer runs and 999 inner draws, 36 months and eight trades per pattern/month; both complete and `d00` partial nulls retain size, power, uncertainty intervals and attempt hashes. Raw three-block numerical ties are reported separately; conservative handling applies only to the diagnostic block variant.

## Verification

Full stable-tree run: **4,243 passed, 26 skipped, 1,096 warnings in 379.67 seconds**, process exit 0. Run with `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring`, `QT_QPA_PLATFORM=offscreen`, and `pytest -q -p no:cacheprovider`. Warnings match the existing broker/modeling dependency warning count.

Repository Ruff passes; `mypy src` passes all 212 source files; Bandit passes without findings; Black 26.5.1 passes with 721 files unchanged. The affected Phase 2 run passed 360 tests; final review repairs passed 55 affected tests, with independent narrow verification. All three independent review findings were reproduced and repaired test-first. GitHub CI is checked after the operator-authorized push; its final result is reported in chat.

## Evidence and disposition

- [Implementation regressions and checks](PHASE_2C_CORRECTIONS_IMPLEMENTATION.md)
- [Dependence diagnostic definitions, size, power, intervals and runtimes](PHASE_2C_DEPENDENCE_DIAGNOSTIC.md)
- [Conservative diagnostic attempts](PHASE_2C_DEPENDENCE_DIAGNOSTIC_RESULTS.json) and [raw-kernel attempts](PHASE_2C_DEPENDENCE_DIAGNOSTIC_RAW_KERNEL_RESULTS.json)

Hold for operator review after this push. Phase 2D has not started. No master changes, QAT/IBKR use, promotion-data access, or method declaration occurred. Exact decimal/rational arithmetic, isolated strategy execution, stale halt marks, official-session counting and resumed-open/T64 rules are preserved.
