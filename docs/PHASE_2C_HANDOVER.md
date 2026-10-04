# QAT recovery handover after Phase 2C

**Prepared:** 4 October 2026, Australia/Sydney

**Repository:** `dsaunders-06/WorkBench`

**Worktree:** `C:\Users\mailm\Documents\Codex\2026-09-21\continue-the-qat-recovery-project-from\work\WorkBench-phase2`

**Branch:** `recovery/phase-2-authoritative-strategy`

**Review state:** Phase 2C is submitted for operator review. Stop here until the operator supplies review findings or explicitly authorizes the next stage.

This handover supersedes `docs/PHASE_2_HANDOVER.md`, which was written before Phase 2B Task 5 and now records historical context only. Verify mutable facts from Git and the worktree before relying on this document. The Phase 2C implementation checkpoint is `1374c2c`; this handover has its own later commit.

## Authority and completed work

Follow the operator's latest instructions, then the [Phase 2 design specification](superpowers/specs/2026-10-01-phase-2-authoritative-swing-strategy-design.md), the approved [Phase 2C plan](superpowers/plans/2026-10-01-phase-2c-swing-validation-reporting.md), and the [Phase 2C verification checkpoint](phase-2-authoritative-swing-checkpoint.md). The [engineering runbook](phase-2-authoritative-swing-runbook.md) gives exact offline commands and evidence interpretation. The [Phase 2D plan](superpowers/plans/2026-10-02-phase-2d-promotion-control-plane.md) describes later control-plane work; Phase 2D has not started.

Phase 2A, Phase 2B, and all seven Phase 2C tasks are implemented on this recovery branch. Phase 2C includes signed engineering dataset checks, signal/tail boundaries, published intercept-only WCR-S and Romano–Wolf inference, method and duration audits, blinded reference-incidence inputs, structural risk sweeps, deterministic four-arm replay artifacts, an offline runner, independent reference tests, prefix invariance, and safety checks. `00552d2` corrected the final reporting gap by recording every held position's exact session mark and calculating maximum and average single-position notional exposure over all held sessions. `1374c2c` committed the detailed checkpoint. The original review corrections to independent pattern arms, halt handling, invalidation, Black formatting, and data packaging are included in earlier commits.

The approved halt rule is a stale last-traded-close mark during a halt, no forced exit, official-session time counting, normal gap and due-exit handling at the first resumed open, and terminal zero at `T64` if unresolved without documented consideration. Zero at halt onset belongs only in the structural stress sweep. Missing bars under held positions remain `INVALID`; promotion packaging checks bar coverage before replay. Fractional consolidations may invalidate engineering runs, while a promotion dataset must document rounding or cash-in-lieu. Phase 2 uses exact Decimal and rational price rules and keeps the strategy separate from the production stack.

## Verified state and local evidence

At the Phase 2C checkpoint, the focused Phase 2 and safety suite passed 346 tests. The full repository suite passed 4,227 tests with 26 skipped; Ruff, strict mypy, and Black passed. The checkpoint records the exact commands, durations, and warnings. Re-run relevant checks after any change. The engineering synthetic and strict static-cache bundles are under `data/phase2-engineering-final-exposure-synthetic/ef2d53611e43205c05c481fa75ee204b` and `data/phase2-engineering-final-exposure-static/357e907123feb605e5b9cf64a37368db`. They are ignored local files and are not transferred by Git. The static cache is survivorship-biased and lacks promotion-grade provenance. Both bundles report `PORTFOLIO_RISK_DESIGN_PENDING`; neither establishes strategy edge.

A fresh full-suite run for this handover used `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` from the worktree root and passed 4,227 tests with 26 skipped and 1,096 warnings in 643.25 seconds. The handover changes only documentation.

No promotion-tier development, validation, holdout, or tail observation was opened. Phase 2 cannot issue a `PASS` verdict or a permit. The blinded development structural extractor, Declaration Authority, release custodian, Phase 4 portfolio policy, and sealed-data controls remain later work. Phase 2D Stage A precedes any Phase 4 promotion-tier outcome; Stage B depends on the Phase 4 policy and development/validation freeze. Permit issuance and actual holdout execution require separate operator approval. The deferred production-stack parity replay is also a separate later decision.

## Review and safety boundary

The operator asked to push Phase 2C and then hold for review. On resumption, first check the actual branch, HEAD, clean worktree, upstream, remote tip, and any newer operator instruction or review. Do not treat unchecked plan boxes or the older handover as current status. If no review verdict has arrived, report the verified state and stop before substantive changes. If review requests fixes, reproduce each finding against the code and governing spec, write a failing regression test first, make the minimum correction, and rerun the relevant checks. Do not begin Phase 2D from this handover alone.

Do not modify `master`, start or use QAT or IBKR, place paper or live orders, touch the production OMS/adapter/deployed strategy, or open sealed promotion data. Preserve the Phase 1 broker-confirmed lifecycle and the exact-decimal and isolation constraints. Do not push another change without a new operator instruction.

## Prompt for a new context window

```text
Continue the QAT recovery from docs/PHASE_2C_HANDOVER.md in the worktree
C:\Users\mailm\Documents\Codex\2026-09-21\continue-the-qat-recovery-project-from\work\WorkBench-phase2.
Phase 2C has been submitted on recovery/phase-2-authoritative-strategy for my review.
First verify the branch, HEAD, worktree, upstream remote, latest commits, and
whether any newer instruction or review supersedes the handover. Read the
governing Phase 2 specification, Phase 2C checkpoint, and relevant plan.
Treat docs/PHASE_2_HANDOVER.md as historical. Do not modify master, use IBKR
or the running application, or open promotion-tier sealed data. Preserve exact
decimal arithmetic, strategy isolation, and the approved halt/data rules.
My Phase 2C review decision and findings are: [PASTE REVIEW HERE].
If I have not supplied a review decision, present the verified state and hold.
If I approve corrections, implement them test-first and verify the full affected
scope. Do not start Phase 2D or push further changes without my instruction.
```
