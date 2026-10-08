# Phase 2C review corrections: implementation evidence

4 October 2026, Australia/Sydney. Operator-authorized corrections to
`recovery/phase-2-authoritative-strategy` at baseline `6f6f05a`.
The latest operator review supersedes the handover's hold and authorizes
items 1–6, a diagnostic-only investigation of item 7, a correction push, then hold.

## Corrections and reproduced failures

| Review item | Reproduction before correction | Minimum correction and regression evidence |
| --- | --- | --- |
| 1 / F3 CI | Bandit: 14 findings, comprising nine B101 production asserts, four B105 outcome-enum false positives, and one B311 seeded count simulator. AST regression failed with nine assertions; optimized-Python allocation regression produced an unintended TypeError. | Explicit domain/ValueError exceptions preserve runtime invariants under Python -O. Narrow B105/B311 suppressions have one-line nonsecurity reasons. Black explicitly ran on news.py; installed 26.5.1 leaves it unchanged (review used 24.10). Every task in Phase 2A/B/C/D plans requires Bandit and Black; Phase 2D instructions were edited only, no work started. Security regressions: 2 passed; Bandit now passes with no findings. |
| 2 / F2 stress rate | Alternating zero/four monthly counts returned zero from a single-next-month normal prediction. Regression failed at a holdout lower rate >1.5. Seed-5 Poisson(2) counts across 60 development and 24 validation months incorrectly bound on predictive_90_lower. | Predict the average rate of each 36–120-month candidate holdout from the declared joint 3/6/12-month moving-block count paths. Use the smallest empirical lower-10th-percentile rate over block lengths, compared with the development rolling-36 minimum and validation rate. Paths never bridge the development/validation boundary; joint pattern vectors and true zero months remain intact. Poisson-like regression now binds on full_validation at 35/24 entries/month and is feasible; audit/planner tests: 14 passed. |
| 3 / F4 terminal sensitivity | A conservative-terminal failure with all_edge_gates_pass=False returned FAIL before TERMINAL_OUTCOME_SENSITIVE. The runner left all replay edge provenance absent (edge gate None). | Derive conservative and explicit recovery gates from replay signal trades, synchronized WCR-S/Romano–Wolf inference, doubled-cost replays, concentration, and separately supplied frozen protocol contexts. Recovery requires identical trade identities/frozen economics and cannot change nonterminal outcomes. No payout is inferred from a stale mark. Missing recovery evidence remains false. Known unrelated portfolio failure cannot be hidden; when calibrated tail gates apply, supplied recovery-tail parity/mean/drawdown must pass. A 240-trade/120-month synthetic replay fixture has three conservative terminal-zero outcomes fail the gates; explicit recovery valuations alone restore all gates and yield TERMINAL_OUTCOME_SENSITIVE before FAIL. Engineering evidence still returns PORTFOLIO_RISK_DESIGN_PENDING. Promotion/runner checks: 27 passed before the additional portfolio and exit regressions; the final affected suite includes them. |
| 4 / F5 invalidation | pending_entry_from_setup and the independent single-pattern signal path accepted QUALIFIED evidence without structural_invalidation_raw. Both dedicated regressions failed with DID NOT RAISE. | Remove both stop fallbacks; reject missing explicit invalidation. Existing qualified test fixtures now supply their declared structural level. Lifecycle/fills/corporate-action/replay affected scope: 98 passed at this stage. |
| 5 / F6 resistance diagnostic | Both paths used unrestricted historical bars and returned CLEAR for invalid/unavailable history or a zone ValueError. Three regressions failed, returning CLEAR for short history, unverified history and zone construction failure. | Share the engine's exact three-calendar-year history/validity checks, use the signal-session conversion factor, and record post_fill_resistance_abstain plus RuleEvidence when history/zones cannot be established. The short golden fixture now truthfully records abstentions; the positive zone fixture supplies valid three-year history. Replay/resistance/engineering checks: 47 passed. |
| 6 / F7 structural sweep | Reviewed endpoint regressions failed: five placements omitted the exit session instead of six. | Include the baseline exit session while retaining the existing post-entry start. The sparse ledger removes scheduled exit proceeds at this placement. An exit-specific test proves proceeds removal can bind worst drawdown; the independent full-path parity test includes the exit placement. Promotion tests after final regressions: 19 passed. The specification and Phase 2C plan explicitly record the operator's 4 October F7 amendment, superseding the previous exclusive exit endpoint. |

## Final affected-scope verification

The complete affected check ran all `tests/domain/strategies/authoritative_swing`,
all `test_swing*.py` modules in `tests/domain/backtester`, the new
`test_phase2_review_security.py`, and
`tests/integration/test_authoritative_swing_engineering_replay.py` with
`pytest -q -p no:cacheprovider --tb=short`: **360 passed in 27.79 seconds**.
Local execution log: `.superpowers/sdd/phase-2c-review-corrections/affected-tests.log`.

Independent final review also reproduced two remaining bypasses with failing regressions: recovery doubled-cost evidence could change ordinary outcomes, and a QUALIFIED signal could reconstruct missing raw invalidation from an analytical threshold. The corrected helper now binds both ordinary and doubled-cost replay pairs (pattern/trade identities, frozen terms, eligibility, unchanged nonterminal outcomes), and the signal path rejects missing raw invalidation before either branch. The three affected modules passed **54 tests in 6.82 seconds** after these fixes; Ruff and affected mypy pass.

A further real-replay regression reproduced legitimate cost-driven resizing: a high-capacity golden EMA signal changes from 86 to 74 shares, with different trade IDs, under doubled costs. Cross-cost pairing now uses stable signal identity (symbol, patterns, entry session, submitted limit and initial stop) and eligibility; same-cost conservative/recovery pairs retain strict trade-ID/frozen-economic binding. An unrelated cohort is rejected. The final promotion/replay/runner scope passes **55 tests in 7.45 seconds**; final duration is recorded by the coordinating agent.

Every correction task's verification must include:

`.\.venv\Scripts\python.exe -m bandit -r src -q`

`.\.venv\Scripts\python.exe -m black --check .`

Bandit passes without findings. Its 54 legacy nosec-comment parser warnings
pre-existed; the new suppressions add no such warnings. Black 26.5.1 passes
with 721 files unchanged. Ruff across src/tests/the engineering runner passes.
Strict mypy across the 17 directly affected source files and runner passes.
`git diff --check` passes. The coordinating agent records the full repository
suite and remote CI outcome separately before final push/hold.

## Boundaries and diagnostic investigation

Item 7/F1 is diagnostic only and is recorded in the separate dependence report.
No declared inferential method or METHOD_AUDIT_DECLARED document was changed or
signed. Existing binary64 statistical inference stays outside trading decisions;
price, risk and sparse-equity arithmetic remain exact Decimal/rational rules.

No master changes, QAT/IBKR use, broker access, sealed promotion data access,
Phase 2D implementation, or subagent commit/push occurred. The approved stale
last-traded-close halt mark, resumed-open processing, official-session count,
and unresolved T64 zero rule remain in force. After the operator-authorized
correction push, hold for review.
