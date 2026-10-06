# Phase 2D amended generic method pilot (in progress)

This is pre-declaration evidence. The unsigned `METHOD_AUDIT_DECLARED` draft has
not been released, signed or timestamped. The development/validation-calibrated
block and terminal-loss scenarios remain unresolved until authorized
pre-holdout calibration inputs exist. This generic pilot cannot qualify a
method for promotion on its own.

The operator-approved July 2014 market-proxy primary is `5632.9`, Yahoo's
`5632.8999` rounded to the ASX table's one-decimal precision. The original ASX
`5623.9` is preserved as source-discrepancy evidence and sensitivity. Both
versions give the same broad persistence conclusion. The approved-primary
return lag-one autocorrelation is about `-0.0874`, maximum absolute
monthly-return autocorrelation through lag 12 is about `0.1426`, and
realised-volatility lag-one autocorrelation is `0.4524`.

## Pilot matrix and compute plan

The pre-declaration generic dependence pilot has 21 cells from mandatory
scenario families: seven complete and partial null configurations for each of
a zero-mean volatility-regime generator
(`phi = 0.4524`), a return-bounded AR(1) mean generator (`phi = -0.0874`), and
the explicitly stressed AR(1) mean generator (`phi = +0.25`). The prior 56
constant one-through-four-month Gaussian mean-shock cells, with aligned and
random phase, are now sensitivities. EMA pullback, bull flag and double bottom
are present in every Romano–Wolf family. The same three frozen candidates use
paired outer draws and base-month weight matrices.

The full calibrated audit additionally requires development/validation block
resampling, stressed cluster imbalance, empirical skew and the terminal-loss
envelope. Those cells cannot be constructed from this strategy-independent
pilot and remain unresolved before any method qualification.

The observable-v2 generator calibrates the lognormal volatility scale's
lag-one correlation to `0.4524` through a latent Gaussian AR(1) coefficient
of about `0.4972628264`. For mean shocks, within-month Gaussian residuals
are centered and variance-corrected before adding the common AR(1) state, so
the monthly average outcome targets the declared correlation even when month
counts vary. The first launched recipe understated both observable
correlations. Its outside-Git checkpoints are superseded and excluded.

Exploratory seed `20261005` is retained as lineage. The approved simulation
domains are `845317` for outer null draws, `845318` for inner signs and `845319`
for prospective power. The generic size runner hashes each base seed and
scenario ID to a 64-bit seed, then advances a PCG64 stream across replicates.
The power runner hashes its base seed, scenario ID and replicate index for each
outer draw and inner matrix. All three candidates in a cell use identical
draws and signs. The run starts at 20,000 outer simulations per candidate with
9,999 inner signs, extending a
cell to 100,000 only under the declared 0.25-percentage-point sequential rule.
Its one-sided 95% Wilson upper limits must be at most 3.25% for confidence
size and 6% for family size; at 20,000, a margin of 0.25 percentage points
from either cap is needed for early acceptance or rejection. Monte Carlo
uncertainty remains material near either cap until the 100,000 extension is
complete. Individual cell intervals and attempts are retained outside Git.

The previous 56-cell pilot measured 102.284 candidate CPU-hours, with
20,000-run checkpoints around 1,550–1,780 seconds each and 33 of 168
candidate cells extending to 100,000. At the same rate, 77 × 3 candidate
cells imply roughly 100–115 CPU-hours for their initial checkpoints and
80–130 additional CPU-hours if a similar fraction extends. At 12 workers,
the planning range is about 15–21 wall-hours, subject to contention and
scenario-specific runtime. The corrected run was launched on 6 October 2026
with raw checkpoints and `report.json` at
`C:\Users\mailm\Documents\Codex\phase2d-amended-method-pilot-observable-v2-20261006`.
Its prelaunch manifest SHA-256 is
`54c417c5692efe4a1ece2c533011948b8ea0bfabca0fc72173e1cae730ddc758`.
The manifest pins source hashes, Python and NumPy versions, candidate set,
scenario parameters, seeds and regeneration command. An interrupted session
was resumed from verified checkpoints with identical source hashes and
parameters. No declaration hash is frozen.

## Method ranking and projection freeze

No candidate ranking is reported until every mandatory size cell and paired
power cell is complete. The paired power grid has 24 cells: the three amended
dependence generators at `N = 200` and `N = 430` for each effect `0.10`,
`0.15`, `0.20` and `0.30`. Its projected rejection fraction counts a pattern
only when both one-sided WCR-S confidence has `p < 0.025` and Romano–Wolf
adjusted family inference has `p < 0.05`. This is the event relevant to both
frozen inference gates. The review summary will give rankings only, by the
minimum of that joint fraction over generators and all three patterns.
At 20,000 paired outer draws, overlapping two-sided 95% Wilson limits on
adjacent worst-cell fractions trigger 100,000-draw extensions for all three
generators at that projection point. Any overlap remaining at the cap is
reported as ranking uncertainty. Raw power fractions and Monte Carlo limits
stay outside Git at
`C:\Users\mailm\Documents\Codex\phase2d-power-grid-observable-v2-20261006`.
Its prelaunch manifest SHA-256 is
`0855d6e7c27506fa60aac44556cd455b80c35500fe06024818960c5232fee47f`.
The proposed common projection size of 430 trades per pattern remains unfrozen
until complete candidate rankings are
identical at `N = 200` and `N = 430` for effects `0.10`, `0.15`, `0.20` and
`0.30`. Even an identical ranking would make 430 a comparison point only:
development/validation-calibrated power cells remain unresolved, so this
generic ranking cannot itself freeze the declared comparison point. The
bull-flag mechanical proxy is about 69.96 pre-resistance candidates over
36 months, below the 100-trade floor. Pattern-specific frequency, power and
duration must therefore be reported separately; EMA or double-bottom counts
cannot make bull flag feasible. A method failure remains `METHOD_INADEQUATE`;
pattern-specific data or frequency shortfalls map to
`INSUFFICIENT_EVIDENCE`, while engineering-tier overall status remains
`PORTFOLIO_RISK_DESIGN_PENDING`.

The raw pilot and power evidence are incomplete at this report revision. No
winner, 430-trade freeze, prospective-power claim or promotion claim follows
from the in-progress run.
