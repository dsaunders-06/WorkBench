# Phase 2D Stage A review report

**Current disposition (8 October 2026):** Stage A is dormant after the final
`METHOD_INADEQUATE` pilot result. No declaration or data release is authorized.
This report records its earlier implementation review; see
[the closure note](phase-2-closure.md) for the controlling status.

**Status:** Stage A implementation submitted on `recovery/phase-2d-stage-a` for
operator review. No declaration has been signed, submitted, or timestamped;
no promotion shard was opened, and no operator key was generated, stored, or
used. Stage B remains locked.

## Stage A boundary

The declaration authority now verifies an exact three-record chain, operator
signatures and certificate path, immutable payloads, sequence/head/nonce
lineage, and recorded RFC 3161 tokens offline. The fixtures contain public
throwaway test certificates, CRLs, and a recorded token; no private test key
or real operator key is tracked. The
[runbook](phase-2d-declaration-runbook.md) proposes DigiCert for operator
review without selecting or configuring a responder.
The [unsigned METHOD_AUDIT_DECLARED draft](METHOD_AUDIT_DECLARED_UNSIGNED_DRAFT.json)
remains unsubmitted and requires the operator's final candidate, scenario,
and hash freeze.

The structural extractor permits only field-limited, pre-holdout reference
windows and aggregate signal-time development fields. It records the exact
source, schema, official calendar and dependency closure before release. The
development and validation gates verify all three declaration receipts,
catalog/shard/bundle/scope and ledger lineage, log every data open, and require
frozen development evidence before validation. The narrow defect-rerun path
requires operator-reviewed independent proof; a changed bundle cannot restore
a consumed holdout. These are implementation boundaries and synthetic tests,
not a deployed custodian service.

Local verification before the Stage A implementation commit: Ruff, latest
Black, mypy, Bandit and the full suite passed (4,340 passed, 26 skipped).
[GitHub CI run 458](https://github.com/dsaunders-06/WorkBench/actions/runs/37255194415)
also passed on the published branch.
After the pilot report, Ruff, latest Black (`black --check .`), mypy, Bandit,
and the full suite passed again (4,340 passed, 26 skipped). GitHub CI is
checked on the final report commit before operator review.

## Generic method pilot

The pre-declaration pilot compares entry-month WCR-S, quarter WCR-S and aligned
block-cluster wild bootstrap (`L=4`) on paired outer observations and weight
matrices. Its 56 generic Gaussian cells cross persistence lengths 1–4 months,
the complete null and all one-/two-pattern partial nulls, and month-0-aligned
versus random shock phase. Each candidate starts with 20,000 outer runs and
9,999 inner draws; a cell escalates to 100,000 runs under the declared
0.25-percentage-point sequential rule. The calibrated development/validation
block-resampled scenarios and prospective power remain a later declared audit,
not part of this generic pilot.

Completed **56/56 cells** with **168 initial 20,000-run checkpoints** and
**33 100,000-run extensions**. All three candidates received the same initial
outer draws and weight matrix in each cell. The
[full scenario/candidate matrix](phase-2d-generic-pilot-summary.csv) records
each confidence and family point rate, one-sided 95% Wilson limits, cap,
sequential decision, attempt hash and compute runtime.

| Candidate | Aligned cells passing / 28 | Random-phase cells passing / 28 | 100,000-run extensions | CPU-hours |
| --- | ---: | ---: | ---: | ---: |
| `entry_month-L1` | 7 | 7 | 1 | 23.964 |
| `quarter-L3` | 15 | 11 | 15 | 38.037 |
| `aligned_block-L4` | 21 | 14 | 17 | 40.283 |

Each cell passes only when the one-sided 95% upper Monte Carlo limits are at
most 3.25% for confidence and 6% for family size after the 20,000/100,000
sequential rule. Pass counts by persistence length, out of seven null
configurations in each phase, are:

| Candidate | 1 aligned/random | 2 aligned/random | 3 aligned/random | 4 aligned/random |
| --- | ---: | ---: | ---: | ---: |
| `entry_month-L1` | 7/7 | 0/0 | 0/0 | 0/0 |
| `quarter-L3` | 7/7 | 1/4 | 7/0 | 0/0 |
| `aligned_block-L4` | 7/7 | 7/7 | 0/0 | 7/0 |

The operator has not yet chosen which shock-phase variant is mandatory, and
no inference method is selected or declared by this generic pilot.

The raw `report.json` SHA-256 is
`fd999a0a274dce8c6345681f578b78ce900712b2998d7c619c6f4e85ba9d06d4`;
the summary CSV SHA-256 is
`de0d9f9ea272c7930c0f0b1fb0951b33f2540e87f8ebefb165c8bb03967016d1`.
Measured candidate compute totals **102.284 CPU-hours** across all completed
attempts. The final uninterrupted 12-worker session took **8.096 wall-hours**;
earlier checkpoint runs and an interrupted interval are excluded from that
wall figure but included in the CPU total.

No candidate passes every aligned-phase or every random-phase generic cell.
Pre-declaration options for operator review are a different declared block
length or candidate set; neither has been changed here.

Raw checkpoints and the generated `report.json` are outside Git at
`C:\Users\mailm\Documents\Codex\phase2d-generic-method-pilot-20261005`.
Regenerate from the repository root with
`python scripts/research/run_phase2c_generic_method_pilot.py --output-dir C:\Users\mailm\Documents\Codex\phase2d-generic-method-pilot-20261005 --workers 12`.
The saved checkpoint attempt hashes, report hash and
[provisional code manifest](phase-2d-generic-pilot-code-manifest.json) make the
evidence reviewable; the operator has not frozen them. The first four
checkpoints preceded worker-count and formatting edits to the runner, with no
statistical-method change, so the present code manifest alone does not certify
those four original executions. The initial estimate before launch
was roughly 40 CPU-hours / 10 hours at four workers, with up to 201 CPU-hours
of escalation; the run resumed safely from four hashed checkpoints with 12
workers when measured candidate times were longer.

## Operator freeze and source decisions

The [frequency proposal](phase-2d-operator-freeze-proposals.md) derives a
430-trade-per-pattern **comparison point** from pre-resistance static-cache
mechanical counts scaled to 200 symbols over 36 months. The bull-flag proxy is
only 69.96 pre-resistance candidates in 36 months, so 430 cannot be assumed
feasible for every pattern. Exploratory seed `20261005` is distinct from the
unapproved calibrated-audit seed proposal (`845317`, `845318`, `845319`). The
operator retains `delta_MME` in `EFFECT_DECLARED`; no value is frozen here.

The [market-proxy source audit](phase-2-market-regime-proxy.md) records apparent
digit transpositions in the ASX month-end table: July 2014 `5623.9` versus
Yahoo approximately `5632.9`, and September 2023 `7084.6` versus Yahoo
approximately `7048.6`. RBA F18 supports Yahoo for September; no eligible
third July close was found. We propose the one-decimal Yahoo value `5632.9`
for July 2014 for operator review. The approved primary series still keeps
the ASX July value, and the precomputed Yahoo-substitution sensitivity leaves
the recommended mandatory generic persistence set at 1–4 months. No source
decision is changed by this report.
