# Phase 2 authoritative swing checkpoint

**Date:** 4 October 2026 (Australia/Sydney)

**Branch:** `recovery/phase-2-authoritative-strategy`

**Authority:** [approved Phase 2 specification](superpowers/specs/2026-10-01-phase-2-authoritative-swing-strategy-design.md) and [Phase 2C plan](superpowers/plans/2026-10-01-phase-2c-swing-validation-reporting.md)

**Disposition:** engineering implementation verified; promotion status `PORTFOLIO_RISK_DESIGN_PENDING`. No strategy edge or deployment claim.

## Implemented scope and lineage

Phase 2A implements the isolated strategy calculations, three patterns, resistance, exact-decimal risk sizing, and decision evidence in specification §§4–9 and 13–14. Phase 2B implements deterministic four-arm replay, fill precedence, cash-funded allocation, official sessions, halts, splits, dividends, terminal handling, and isolation in §§10–12 and 15. Phase 2C implements signed engineering dataset validation, signal windows and tails, WCR-S and Romano–Wolf inference, method and frequency audit primitives, field-limited reference incidence with a zero-weight outside-support micro-cap sensitivity, structural risk sweeps, reproducible artifacts, and the offline engineering runner in the engineering parts of §§15–19. Phase 2 does not implement the Declaration Authority, release custodian, exposure permit, or production integration.

The relevant commits are `25c4221` (dataset validation), `7b607e4` (repository Black baseline), `7311b55` (review corrections for independent pattern arms and halts), `90920cc` (consolidation and bar coverage contracts), `332b59e` (signal windows and tails), `be03cfb` (method and duration audit), `2d3b1c7` (incidence and structural risk), `dac6761` (published WCR-S intercept-only CV1 correction), `d978162` (evidence artifacts), `abbaa00` (offline engineering runner), `a0fb6f8` (final review corrections and verification), and `00552d2` (held-session position exposure). The review corrections make the monthly frequency floor predictive rather than a mean-confidence bound, count funded entry-day aggregate/sector exposure, bind a new signed catalog hash to its parent for forward extensions, publish available incidence support and excluded micro-cap sensitivity, run sensitivities for signed engineering shards, and show key fields in the human report. The final exposure correction records each open position's exact session mark in the equity ledger and measures maximum and average single-position notional exposure over every held session. The approved WCR-S clarification is recorded in the specification and Phase 2C plan.

## Verification evidence

On Windows with Python 3.12.14 and the repository virtual environment:

| Check | Result | Duration |
| --- | --- | ---: |
| Focused Phase 2 and safety suite, including independent reference and prefix tests | 346 passed | 19.97 s |
| `python -m ruff check src tests scripts/research/run_authoritative_swing.py` | Passed | 0.23 s |
| Strict `mypy` on the authoritative strategy and 12 Phase 2 backtester modules | Passed; 24 source files checked | 1.22 s |
| Strict `mypy` on the offline runner with `MYPYPATH=src` | Passed; 1 source file checked | 0.70 s |
| `python -m black --check .` | Passed; 718 files unchanged | 1.50 s |
| Full `python -m pytest -q -p no:cacheprovider` | 4,227 passed, 26 skipped; 1,096 warnings | 591.42 s |

The focused test command used the exact Task 7 Step 2 file list in the linked Phase 2C plan, with `-q -p no:cacheprovider`. All commands ran from the repository root; the cache plugin was disabled because this checkout's `.pytest_cache` directory is not writable. Full-suite warnings arise in existing broker tests and modeling dependencies; there were no test failures.

`tests/reference/authoritative_swing_reference.py` imports no production helper or production decimal policy. Parity tests independently recompute rational raw/analytical conversion, ASX predecessor ticks, EMA, Wilder ATR, resistance grouping, whole-share risk size, WCR-S observed statistic and p-value, Romano–Wolf stepdown, exact binomial incidence bound, and constant-frequency holdout duration. Equivalent Decimal spellings give identical canonical evidence and synthetic source identities. Two independent frozen runs produce the same semantic ID and byte-identical decisions, fills, trades, equity, metrics, and promotion files. For each evaluated synthetic session, truncating the data at that session or changing every later input category (bars, membership, calendar, corporate actions, and benchmark) leaves the decision/fill/equity prefix byte-identical.

Safety tests establish that the runner rejects promotion-tier and service capabilities before loading a shard, the artifact writer rejects even a forged `PASS` verdict, and the offline runner does not connect to the network or start a child process. No promotion-grade development, validation, holdout, or tail observation was opened or released in Phase 2. The blinded development structural extractor and its outcome-excluding schema belong to the later reviewed custodian process; no such extractor or release path exists in the Phase 2 runner. That Phase 2 boundary is tested, while the future extractor schema itself remains a Phase 2D/Phase 4 verification item.

## Engineering replay artifacts

The append-only synthetic engineering bundle is `data/phase2-engineering-final-exposure-synthetic/ef2d53611e43205c05c481fa75ee204b`. All four arms are valid; the combined arm has six trades and five eligible signal trades, with an ambiguous bar, overlap suppression, a split, dividend settlement, a halt spanning the time stop, and unresolved terminal valuation. The combined arm's maximum and average single-position notional exposures across held sessions are 0.005188851656499330146958606238 and 0.005142116789027627476794935165, respectively. Every held position mark appears in `equity.csv` for audit. This fixture is a software test and has no empirical edge interpretation.

The strict static-cache bundle is `data/phase2-engineering-final-exposure-static/357e907123feb605e5b9cf64a37368db`. It covers 95 current symbols and 501 union sessions, but each symbol has only 500 bars. The STW.AX benchmark proxy is missing one session. The cache lacks verified as-traded raw prices, split-only adjustment lineage, an authoritative exchange calendar, corporate-action and terminal histories, and three years of resistance history. Strict mode records provenance and history abstentions before any trade and does not carry or invent prices. This static snapshot is survivorship-biased and cannot support promotion or an edge estimate. Both bundles report `PORTFOLIO_RISK_DESIGN_PENDING`.

## Handoff

Phase 2D must establish the operator-controlled Declaration Authority, signed append-only declarations and timestamps, reviewed blinded structural extractor with an explicit outcome-excluding schema, reference-view receipt, promotion-tier release custodian, dataset lineage and packaging checks, Phase 4 portfolio risk policy, permits, rehearsal, and sealed holdout controls before any promotion observation is opened. A deferred Option 3 production-stack parity replay remains a separate later step under the approved specification; Phase 2 has not modified the production OMS, broker adapter, deployed strategy, master branch, or running application. The engineering bundles are local ignored artifacts and are not transferred by Git. The [Phase 2C handover](PHASE_2C_HANDOVER.md) records the review boundary.
