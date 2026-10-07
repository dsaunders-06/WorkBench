# Phase 2D amended generic method pilot and combined stress

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

Candidate ranking was withheld until every original mandatory size cell and
paired power cell completed. The paired power grid has 24 cells: the three amended
dependence generators at `N = 200` and `N = 430` for each effect `0.10`,
`0.15`, `0.20` and `0.30`. Its projected rejection fraction counts a pattern
only when both one-sided WCR-S confidence has `p < 0.025` and Romano–Wolf
adjusted family inference has `p < 0.05`. This is the event relevant to both
frozen inference gates. The review summary gives rankings only, by the
minimum of that joint fraction over generators and all three patterns.
At 20,000 paired outer draws, overlapping two-sided 95% Wilson limits on
adjacent worst-cell fractions trigger 100,000-draw extensions for all three
generators at that projection point. Any overlap remaining at the cap is
reported as ranking uncertainty. Raw power fractions and Monte Carlo limits
stay outside Git at
`C:\Users\mailm\Documents\Codex\phase2d-power-grid-observable-v2-20261006`.
Its prelaunch manifest SHA-256 is
`0855d6e7c27506fa60aac44556cd455b80c35500fe06024818960c5232fee47f`.
The proposed common projection size of 430 trades per pattern required
identical complete candidate rankings at `N = 200` and `N = 430` for effects
`0.10`, `0.15`, `0.20` and `0.30`. Even an identical ranking makes 430 a
comparison point only:
development/validation-calibrated power cells remain unresolved, so this
generic ranking cannot itself freeze the declared comparison point. The
bull-flag mechanical proxy is about 69.96 pre-resistance candidates over
36 months, below the 100-trade floor. Pattern-specific frequency, power and
duration must therefore be reported separately; EMA or double-bottom counts
cannot make bull flag feasible. A method failure remains `METHOD_INADEQUATE`;
pattern-specific data or frequency shortfalls map to
`INSUFFICIENT_EVIDENCE`, while engineering-tier overall status remains
`PORTFOLIO_RISK_DESIGN_PENDING`.

## Completed generic size results

The unchanged observable-v2 pilot completed **77/77 cells**: 21 mandatory
cells and 56 disclosed constant-mean-shock sensitivities. It produced 231
initial 20,000-run candidate checkpoints and 45 extensions to 100,000.
All three candidates passed all seven volatility-regime cells and all seven
observed-return-baseline AR(1) cells. **Every candidate failed all seven
binding AR(1) mean-stress cells at `phi = 0.25`.** Thus each candidate was
`METHOD_INADEQUATE` before the combined family was added. The complete
scenario/candidate decisions and one-sided 95% Wilson Monte Carlo limits are
in [the committed size summary](phase-2d-amended-method-size-summary.csv).

The operator-approved combined family uses volatility persistence `0.4524`
and mean AR(1) persistence `0.25` in the same draw, across the complete null
and all six one-/two-pattern partial nulls. Its seven cells completed with
21 initial checkpoints and 12 extensions, taking 5 hours 56 minutes of wall
time with four workers. The initial launch stopped before a draw because its
entry-point import resolved QAT from an older editable checkout. A failing
subprocess test reproduced that error; commit `a95f2f2` pins the runner to its
own checkout. The resumed run used that commit and the unchanged declared
candidates, seeds, caps and 20,000/100,000 rule. CI run `37546391040` passed.

The table gives the 95% Monte Carlo limits, in percentage points, for the
confidence and family false-positive rates. The caps are **3.25%** and
**6.00%**, respectively. A cell passes only when both one-sided upper limits
are at or below their caps. `0` means a true-null pattern and `d` an
alternative pattern in EMA pullback, bull flag, double-bottom order.

| Null | Candidate | Runs | Confidence 95% limits | Family 95% limits | Size |
| --- | --- | ---: | ---: | ---: | --- |
| `000` | entry month | 20,000 | 6.317–6.895% | 9.942–10.649% | Fail |
| `000` | quarter | 100,000 | 3.425–3.617% | 6.432–6.690% | Fail |
| `000` | aligned block L=4 | 100,000 | 2.883–3.060% | 5.742–5.986% | Pass |
| `00d` | entry month | 20,000 | 5.710–6.262% | 9.366–10.055% | Fail |
| `00d` | quarter | 100,000 | 3.405–3.596% | 6.355–6.611% | Fail |
| `00d` | aligned block L=4 | 100,000 | 2.856–3.032% | 5.759–6.004% | Fail |
| `0d0` | entry month | 20,000 | 5.994–6.558% | 9.883–10.588% | Fail |
| `0d0` | quarter | 100,000 | 3.479–3.672% | 6.481–6.739% | Fail |
| `0d0` | aligned block L=4 | 100,000 | 2.913–3.090% | 5.829–6.075% | Fail |
| `0dd` | entry month | 20,000 | 6.278–6.854% | 9.883–10.588% | Fail |
| `0dd` | quarter | 20,000 | 3.525–3.967% | 6.577–7.165% | Fail |
| `0dd` | aligned block L=4 | 100,000 | 3.013–3.193% | 5.899–6.147% | Fail |
| `d00` | entry month | 20,000 | 6.004–6.568% | 9.637–10.334% | Fail |
| `d00` | quarter | 100,000 | 3.539–3.734% | 6.331–6.587% | Fail |
| `d00` | aligned block L=4 | 100,000 | 2.917–3.095% | 5.830–6.076% | Fail |
| `d0d` | entry month | 20,000 | 6.278–6.854% | 9.932–10.639% | Fail |
| `d0d` | quarter | 20,000 | 3.550–3.993% | 6.547–7.134% | Fail |
| `d0d` | aligned block L=4 | 100,000 | 2.926–3.104% | 5.840–6.086% | Fail |
| `dd0` | entry month | 20,000 | 6.131–6.701% | 9.986–10.694% | Fail |
| `dd0` | quarter | 100,000 | 3.565–3.760% | 6.530–6.790% | Fail |
| `dd0` | aligned block L=4 | 100,000 | 3.010–3.190% | 5.943–6.191% | Fail |

Only the complete-null aligned-block cell passes. **No candidate passes every
mandatory cell; all remain `METHOD_INADEQUATE`.** The combined family changes
no candidate's selection status. No method is selected, no calibrated audit
is represented as complete, and no declaration is signed or submitted.

## Power ranking and evidence custody

The paired power grid completed its eight projection points. Its declared
minimum-power ranking is identical at both sample sizes and all four effect
values; there is no Monte Carlo overlap between adjacent ranks at the cap.
The table deliberately omits power fractions until `EFFECT_DECLARED` is
signed on economic grounds.

| Trades per pattern | 0.10 R | 0.15 R | 0.20 R | 0.30 R |
| ---: | --- | --- | --- | --- |
| 200 | entry month > quarter > aligned block | entry month > quarter > aligned block | entry month > quarter > aligned block | entry month > quarter > aligned block |
| 430 | entry month > quarter > aligned block | entry month > quarter > aligned block | entry month > quarter > aligned block | entry month > quarter > aligned block |

The original ranking condition for a 430-trade comparison point is met in
this generic grid. The later-added combined family is absent from that power
grid, and development/validation-calibrated power remains unresolved; the
unsigned draft therefore retains its conditional projection-size status.
The ranking does not override the size failure.

Raw attempts and power fractions remain outside Git in the two directories
named above and in
`C:\Users\mailm\Documents\Codex\phase2d-combined-stress-pilot-20261007`.
SHA-256 hashes are:

| Artifact | SHA-256 |
| --- | --- |
| 77-cell `report.json` | `f76ac5c56578c9a849c19ce73b7a8bf12d565592361a3284ed0b617d3861ae50` |
| Seven-cell `combined-report.json` | `45a2cb43efd8d9e65cf4910be5954080ab5bd63dbf0f10a0b323dd11fdd55851` |
| Paired `power-report.json` | `709a7f43a2fb35fb44ffb1e8eea8fd6407f17d8d4c365a85bc6174fc15ecc2a6` |
| Committed size summary CSV | `f396bd5ca261f864147445c1b391886a8e78b7d9cc1d08d5cd7616611ac0b81d` |

The combined-report hash above corrects a transcription error in the
preceding report revision; the outside-Git file and its contents were not
changed.

The combined report pins the prior report hash. Independent checks confirmed
all seven null configurations, identical candidate inputs at each common
20,000-run prefix, every 100,000-run prefix, and all 21 selected raw attempt
hashes. Regenerate the completed addendum from the repository root with
`python scripts/research/run_phase2d_combined_stress_pilot.py --prior-report C:\Users\mailm\Documents\Codex\phase2d-amended-method-pilot-observable-v2-20261006\report.json --output-dir C:\Users\mailm\Documents\Codex\phase2d-combined-stress-pilot-20261007 --workers 4`.
The first run is resumable from its verified outside-Git checkpoints. The
pre-existing 77-cell pilot and power-grid commands and source manifests remain
in their respective outside-Git output directories. No output artifact is a
signed declaration.
