# Phase 2D final Holm method pilot: binding stopping result

The operator-authorized final candidate, `aligned_block_holm-L4`, is
**METHOD_INADEQUATE** under the stopping rule recorded before this pilot. All
28 mandatory confidence-bound cells met the 3.25% cap. Six of the 28 family
cells exceeded the 6.00% cap on their one-sided 95% Monte Carlo upper limits.
Those six were the two-alternative partial nulls under AR(1) mean persistence
of 0.25, alone and combined with volatility persistence of 0.4524. The other
three candidates had already failed the mandatory generic pilot. **No method
qualifies**, and no method is selected or declared. The rule allows no further
candidate, threshold or dependence change in this Phase 2 promotion attempt.

The [28-row size summary](phase-2d-final-holm-size-summary.csv) records the
complete and six partial nulls for each of the four mandatory families, with
rejection counts, point rates, one-sided 95% Wilson limits and pass/fail
decisions for both gates. `0` denotes a true null and `d` an alternative in
EMA pullback, bull flag, double-bottom order. These are the six failing cells;
all ran to the declared 100,000-draw maximum. Percentages shown are one-sided
95% *upper* Monte Carlo limits, compared with the fixed 6.00% family cap.

| Mandatory family | Null | Family upper limit | Decision |
| --- | --- | ---: | --- |
| AR(1) mean 0.25 | `dd0` | 6.1338% | Fail |
| AR(1) mean 0.25 | `d0d` | 6.0359% | Fail |
| AR(1) mean 0.25 | `0dd` | 6.1368% | Fail |
| Volatility 0.4524 + AR(1) mean 0.25 | `dd0` | 6.1914% | Fail |
| Volatility 0.4524 + AR(1) mean 0.25 | `d0d` | 6.0864% | Fail |
| Volatility 0.4524 + AR(1) mean 0.25 | `0dd` | 6.1469% | Fail |

The largest confidence upper limit was 3.1935%, below its 3.25% cap. The
pilot used the unchanged one-sided WCR-S marginal tests, exact enumeration of
512 signs for the nine aligned four-month clusters, Holm step-down over the
three marginal p-values, 9,999 declared inner draws, and the 20,000/100,000
sequential rule. Fourteen cells extended to 100,000 runs; the other fourteen
stopped at 20,000. Eight workers completed the pilot in about 4 hours 30
minutes. This is a generic pre-declaration size check, not the prospective
calibrated audit, which was not run.

An independent checkpoint review verified all 28 summary files against the
raw selected-run checkpoints, all attempt SHA-256 values, the 20,000-run
prefix of each 100,000-run extension, the Wilson limits and decisions, and
the frozen scenario IDs, seeds and source hashes. Every 20,000-run input hash
and every selected-run input hash matched the earlier Romano-Wolf aligned
L=4 checkpoint for that same scenario. The two prior reports also matched the
hashes pinned in the pilot manifest. No raw attempts or power values are
committed.

| Artifact | SHA-256 |
| --- | --- |
| Outside-Git `holm-report.json` | `6b7f310d6e00307d0531ade78632f4f83e9de6ee022d5f5f645d0784dd14d348` |
| Outside-Git `manifest.json` | `76cd8fc00d765853393cb03e6b5652cc630f6100fe5a4e923d1cf53a4f8814a8` |
| Committed 28-row size summary | `fdf94089478b62e674c726ceaaa32c5ccb5c5076bf01586838e140f0d32e9a7c` |
| Prior 77-cell generic report | `f76ac5c56578c9a849c19ce73b7a8bf12d565592361a3284ed0b617d3861ae50` |
| Prior seven-cell combined report | `45a2cb43efd8d9e65cf4910be5954080ab5bd63dbf0f10a0b323dd11fdd55851` |

Raw checkpoints and their verified manifest remain outside Git at
`C:\Users\mailm\Documents\Codex\phase2d-holm-final-pilot-20261007`. The
frozen code input was commit `a7fbac0`, with green CI run `37584729630`.
Regenerate or resume the same recipe from the repository root with:

```powershell
python scripts/research/run_phase2d_holm_pilot.py --prior-report C:\Users\mailm\Documents\Codex\phase2d-amended-method-pilot-observable-v2-20261006\report.json --combined-report C:\Users\mailm\Documents\Codex\phase2d-combined-stress-pilot-20261007\combined-report.json --output-dir C:\Users\mailm\Documents\Codex\phase2d-holm-final-pilot-20261007 --workers 8
```

The [unsigned draft](METHOD_AUDIT_DECLARED_UNSIGNED_DRAFT.json) records the
stopping outcome and is marked **DO NOT DECLARE**. Nothing was signed,
timestamped, submitted or released. Even a size-valid method would establish
that a holdout test is valid, not that the strategy is likely to succeed. With
only nine four-month clusters in 36 months, the duration planner was expected
to require substantially more than 36 months for prospective power. No
duration or power claim is made for a selected method, because none qualified.
