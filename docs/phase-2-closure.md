# Phase 2 promotion closure — 8 October 2026

**Operator decision:** Phase 2 promotion work is closed as
`METHOD_INADEQUATE` under the binding rule recorded before the final pilot.
No inference method held every mandatory size cap. This is a method-audit
result, not a verdict on the strategy's returns.

The final `aligned_block_holm-L4` candidate passed all 28 one-sided
confidence-size cells; its worst one-sided 95% Monte Carlo upper limit was
3.19% against the 3.25% cap. It failed six family-size cells with exactly one
true null, all under the 0.25 monthly mean-persistence stress alone or combined
with volatility persistence of 0.4524. Their upper limits were 6.04%–6.19%
against the 6.00% cap. The complete decisions and exact limits are in the
[28-cell summary](phase-2d-final-holm-size-summary.csv) and
[pilot report](phase-2d-final-holm-pilot-report.md).

The diagnostic mechanism is that marginal test size under the binding stress
is about 1.2–1.25 times nominal. That remains within the confidence gate's
1.3-times nominal tolerance (3.25% versus 2.5%), but exceeds the family
gate's 1.2-times nominal tolerance (6% versus 5%) when Holm must test the one
remaining true null. These caps, candidates, dependence values and stopping
rule were fixed before the final pilot results. Under that protocol the result
is final; it cannot be rescued by changing the method or thresholds now.

No promotion-tier development, validation or holdout data was opened, and no
real strategy outcome from those partitions was seen. Only synthetic
engineering fixtures and approved strategy-independent market proxies were
used. Nothing was signed, timestamped, submitted or declared. The strategy is
**unvalidated**: it has neither been shown to work nor shown to fail.

The Phase 1 safety layer, the Phase 2 engineering engine, replay, accounting,
artifacts and tests, and the Phase 2D Stage A security groundwork remain valid
engineering work. Stage A is dormant; Stage B and the parked single-pattern
protocol are not authorized. The unsigned declaration draft remains marked
`DO_NOT_DECLARE`.

The only authorized *future* QAT use of the authoritative strategy is
recommend mode, with explicit human sign-off on every order through the
existing Phase 1 OMS path. Every card must say **“unvalidated strategy, no
demonstrated edge”**. Paper account is the default. There is no autonomous
transmission, no current production adapter, and no real-money authorization.
The document-only [Phase 3 specification](phase-3-recommend-mode-integration-spec.md)
and [implementation plan](phase-3-recommend-mode-integration-plan.md) describe
the proposed integration for operator review.

Reopening promotion work requires a new explicitly versioned protocol while
all promotion outcomes remain sealed, a written rationale, and a blinded
feasibility check before any data release. `EFFECT_DECLARED` must set its
economic effect first; only then may the planner test sample size, cluster
count and duration. Existing generic pilot or future operational shadow
outcomes cannot be used to choose the effect or retrofit a promotion claim.

## Evidence and custody

| Evidence | Location |
| --- | --- |
| Accepted Phase 2C engineering | `ebc75d7`, [green CI](https://github.com/dsaunders-06/WorkBench/actions/runs/37245393346) |
| Final Holm pilot code and unchanged recipe | `a7fbac0`, [green CI](https://github.com/dsaunders-06/WorkBench/actions/runs/37584729630) |
| Final size summary and stopping report | `3ad9d2d`, [green CI](https://github.com/dsaunders-06/WorkBench/actions/runs/37622639620) |
| Earlier amended and combined size evidence | [77-cell and seven-cell report](phase-2d-amended-method-pilot-report.md), [size summary](phase-2d-amended-method-size-summary.csv) |
| Final 28-cell evidence | [pilot report](phase-2d-final-holm-pilot-report.md), [size summary](phase-2d-final-holm-size-summary.csv) |
| Dormant Stage A snapshot | annotated tag `phase-2d-stage-a-dormant` on the closure commit; no merge to `master` |
| Phase 2 engineering merge proposal | [draft PR #4](https://github.com/dsaunders-06/WorkBench/pull/4) from `ebc75d7` into `master`; operator review required, not merged |

The raw generic, amended, combined and final-Holm pilot outputs, including
the power-grid output, are archived **outside Git** at
`C:\Users\mailm\Documents\Codex\phase2-promotion-archive-20261008\phase2-promotion-raw.zip`.
Its SHA-256 is
`442edd9ca5b4aada6f13ddc4716e6168bcf51027f7456ede50a4e7fea92686f3`.
The file-by-file [outside-Git hash manifest] is
`C:\Users\mailm\Documents\Codex\phase2-promotion-archive-20261008\hash-manifest.json`
(SHA-256
`af45b84222096956d8770851119e7c76e970854620125e305b5ffc09b3d424c8`).
All 793 archived file hashes were verified against the ZIP. Original
outside-Git directories are retained; power values were hashed as bytes and
were not inspected or reported. The completed Phase 2 pilot monitors were
removed, and no pilot runner remains active.
