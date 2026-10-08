# Phase 2D operator-freeze proposals (unapproved)

**Historical proposals, not a pending freeze.** The binding final method
pilot returned `METHOD_INADEQUATE` and Phase 2 promotion was closed on
8 October 2026. See [the closure note](phase-2-closure.md). No declaration
may be frozen from these proposals.

This note gives the operator concrete inputs to consider before a
`METHOD_AUDIT_DECLARED` release. It does **not** freeze a value, issue a
declaration, establish prospective power, or authorize promotion access.
`delta_MME` remains a positive effect and economic rationale to be supplied by
the operator's `EFFECT_DECLARED`; the diagnostic `0.2` used elsewhere is not a
substitute. The unsigned draft at
[`METHOD_AUDIT_DECLARED_UNSIGNED_DRAFT.json`](METHOD_AUDIT_DECLARED_UNSIGNED_DRAFT.json)
records the amended provisional recipe and remains unsigned.

## Mechanical frequency and projection sample size

The sole frequency input here is
[`data/phase2-engineering-mechanical/7074778a0563b1f4db06fa96d0adfbf9/metrics.json`](../data/phase2-engineering-mechanical/7074778a0563b1f4db06fa96d0adfbf9/metrics.json),
SHA-256 `4c25fa933b0e25e677918ad23362aa852671a93d00ba315d8b0ecf7cb19d2042`,
under `metrics.mechanical_diagnostic`. Its human-readable companion is the
same bundle's [`report.md`](../data/phase2-engineering-mechanical/7074778a0563b1f4db06fa96d0adfbf9/report.md).
The recorded exposure is 95 symbols, 13 calendar months (August 2025 through
August 2026), and 1,235 eligible symbol-months. The counts are pattern geometry
**before** the three-year resistance check. The direct 95-symbol observed
frequency is `count / 13` per month. For the requested 200-symbol, 36-month
planning scale, `rate = count / 1,235` per eligible symbol-month,
`proxy_monthly = rate × 200`, and `proxy_36m = rate × 200 × 36`.

| Pattern | Pre-resistance count | Per 1,000 eligible symbol-months | Observed 95-symbol count/month | 200-symbol proxy/month | 200-symbol proxy/36 months |
| --- | ---: | ---: | ---: | ---: | ---: |
| Bull flag | 12 | 9.7166 | 0.9231 | 1.9433 | 69.96 |
| Double bottom | 93 | 75.3036 | 7.1538 | 15.0607 | 542.19 |
| EMA pullback | 116 | 93.9271 | 8.9231 | 18.7854 | 676.28 |

**Conditional proposal for operator review:** use **430 trades per pattern**
as the common power-comparison projection point only if the complete candidate
rankings are identical at `N = 200` and `N = 430` across effects `0.10`,
`0.15`, `0.20`, and `0.30`. Rank by minimum projected joint rejection fraction
across mandatory scenarios and all three patterns; the joint event requires
one-sided WCR-S `p < 0.025` and Romano–Wolf adjusted `p < 0.05`. The generic
grid cannot complete this check alone while calibrated mandatory power
scenarios remain unresolved. The arithmetic pre-resistance total is
`(12 + 93 + 116) / 1,235 × 200 × 36 = 1,288.4` candidates across three
patterns, or **429.5 per pattern**; 430 is that mean rounded to a whole trade.
It is a *comparison point*, not a forecast that each pattern can attain it.
The pattern-specific proxies above are the more relevant feasibility inputs:
the bull-flag point rate yields only **69.96 pre-resistance candidates** in
36 months, below even the protocol's `N_required >= 100` floor. At the fixed
rate, 100 pre-resistance bull-flag candidates would need
`100 / (12 / 1,235 × 200) = 51.46` months; 430 would need about **221.3 months**.
The audit must also show power at feasible pattern-specific counts and must
not treat a high-power result at 430 as evidence that bull flag passes the
frequency or duration gate. Resistance,
point-in-time membership, complete signal eligibility, funding, overlap, and
other filters can reduce the final count. Thus the 36-month holdout may fail the
100-trade floor for bull flags even if the later method-power result is
favourable. Do not back-solve a larger `N` from the abundant EMA or
double-bottom proxy and present it as feasible for all three patterns.

The report's symbol/month-clustered 90% monthly planning ranges, on the same
200-symbol scale, are 0.648–3.725 for bull flag, 10.186–20.405 for double
bottom, and 12.955–25.263 for EMA pullback. Multiplying these endpoints by 36
would be only a constant-rate illustration, **not** a 36-month prediction
interval; it would ignore time variation and the missing history. This static
snapshot is survivorship-biased, vendor-adjusted, only 13 eligible months long,
and has no verified as-traded prices, point-in-time membership, corporate
actions, or sufficient resistance history. Its high rates cannot establish
final trade frequency or power. A low rate is a procurement warning. No fills,
returns, exits, P&L, or promotion shards were used in this proposal.

At the proposed 430-trade comparison point, each method still needs its actual
nonempty cluster count checked (`G >= 6`) and paired projected rejection
fractions across every mandatory pattern/scenario cell. The chosen method must
then recompute each pattern's `N_required`, `G_required`, minimum detectable
effect, and at least 80% prospective power at the operator-declared
`delta_MME`. The genuine frequency and holdout-duration gates use later
authorized signal-eligible months, including zero-entry months; this
mechanical rate must not be fed to the holdout planner.

## Proposed random streams and evidence hashes

The historical 56-cell exploratory generic pilot used base seed `20261005`
and `SHA-256("20261005:" + scenario_id)` to seed one PCG64 stream per cell.
It is provenance, not the amended audit seed. The operator subsequently
approved the unsigned draft's separate base seeds: outer null `845317`, inner
Rademacher signs `845318`, and power `845319`. In the amended size runner,
hash the ASCII text `base_seed:scenario_id`, take the first eight digest bytes
in big-endian order as an unsigned 64-bit PCG64 seed, and advance distinct
outer and inner streams across replicates. In the power grid, hash
`base_seed:scenario_id:replicate_index` to separate 64-bit PCG64 seeds for
each replicate's outer observations and inner signs. All candidates within a
cell receive the same observations and base-month sign matrix. Record exact
library versions and code bytes in an outside-Git run manifest.

When `EFFECT_DECLARED` and the authorized calibration inputs exist, create a
pilot report that lists all candidate methods, mandatory scenario IDs and
fixed parameters, projection cells at the subsequently approved common sample
size, observed nonempty clusters,
paired size/power fractions, Monte Carlo limits, numerical policy, seeds and
versions, and any failed/incomplete cells. Preserve every attempted cell. Save
the immutable report bytes and calculate `SHA-256(report bytes)` into a
separate manifest (the report must not contain its own hash). For the
implementation/code hash, require a clean, identified Git commit; enumerate
the transitive source files actually used by the pilot, including method,
scenario, RNG, numerical and serialization code, plus the exact dependency
lock and runtime versions. Sort repository-relative paths bytewise, calculate
each file's SHA-256 from raw bytes, serialize a versioned manifest as canonical
UTF-8 JSON (sorted keys, compact separators), and hash those manifest bytes.
Record the commit ID, file list, per-file digests, manifest digest, command,
environment, input-hash manifest, and pilot-report digest together. A changed
source file, dependency lock, scenario instance, seed rule, or report requires
new hashes and a new operator review.

For the **exploratory generic pilot only**, the provisional
[code manifest](phase-2d-generic-pilot-code-manifest.json) has SHA-256
`54830e9f4c32d8b9062753599dfa568130459dd1ec53795721866833ee37e433`.
The code manifest hashes the committed bytes of all 217 tracked `src` Python files, the pilot
runner and `pyproject.toml` (219 files total), plus the published source commit
`2213aa9e572d8f411b4d16ab81e83cad262c6a27` and the actual pilot runtime
(Python 3.12.14, NumPy 2.5.3). This all-source set conservatively contains the
transitive inference code. The repository has no exact dependency lock, and
the first four hashed checkpoints preceded worker-count and formatting edits
to the runner, with no statistical-method change. Thus this manifest is a
reviewable proposed code identity, not a frozen `METHOD_AUDIT_DECLARED` code
hash. The completed external `report.json` has SHA-256
`fd999a0a274dce8c6345681f578b78ce900712b2998d7c619c6f4e85ba9d06d4`;
its committed [scenario summary](phase-2d-generic-pilot-summary.csv) has SHA-256
`de0d9f9ea272c7930c0f0b1fb0951b33f2540e87f8ebefb165c8bb03967016d1`.
The declared calibrated audit
needs one frozen source/runtime/lock manifest for every attempt.

The approved-primary [market-regime proxy](phase-2-market-regime-proxy.md)
calibrates mandatory observable volatility persistence to lag-one `0.4524`
and mandatory monthly-average AR(1) mean shocks to lag-one `−0.0874`, with
explicit `+0.25` stress. The old constant one-to-four-month Gaussian mean
shocks are disclosed sensitivities, alongside longer six- and twelve-month
persistence. For lognormal volatility with log scale `0.6`, the latent AR(1)
coefficient is about `0.497263`; AR(1) trade residuals are centered and
variance-corrected within each month before adding the common state. The
operator-approved July 2014 primary is `5632.9`; the original ASX `5623.9`
remains discrepancy evidence and sensitivity.
