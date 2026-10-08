# Phase 2C cross-month dependence diagnostic (F1)

Diagnostic investigation only, run 4 October 2026. The declared entry-month WCR-S method and promotion rules are unchanged. No declaration was drafted or signed. No promotion data, application, or broker was used.

## Design and reproducibility

Each cell calls `run_synthetic_pilot(..., diagnostic=True)`: Gaussian observations, 36 months, eight trades per pattern per month, 600 outer simulations, 999 inner Rademacher draws, PCG64 seed 20261004. The three patterns have one shared standard-normal shock per persistent block with coefficient 0.35 and independent standard-normal trade noise. Persistence lengths are 3, 6, and 12 months; the independent-month control uses the same generator with a fresh common shock each month. Complete null `000` means all three means are zero. Partial null `d00` gives EMA pullback mean +0.2 and leaves bull flag and double bottom at zero. This effect is a diagnostic choice, not an approved minimum meaningful effect or power declaration.

The comparison uses identical samples and the same full month-weight matrix for each method at a given persistence/null cell; aggregation retains the first sign in each contiguous block. The month and quarter methods call the production kernels directly. All methods impose the same zero restricted null, use CV1 studentization, and apply the same common-sign Romano-Wolf stepdown across the three patterns:

- **Month WCR-S:** 36 entry-month clusters and independent month signs.
- **Quarter WCR-S:** observations concatenated into 12 fixed consecutive three-month clusters, with one sign per quarter and quarter CV1.
- **Block wild:** fixed nonoverlapping blocks matching the simulated shock duration, observations concatenated within each block, one sign per block, and block CV1. This is a block-cluster wild bootstrap, not a moving-block resampling of trades or a month-CV1 statistic with correlated signs. It has 36, 12, 6, or 3 clusters for persistence 1, 3, 6, or 12 months. The block boundaries are aligned with the synthetic shocks, giving this comparison an oracle choice of block length and alignment.

The existing pilot retains confidence rejection flags for true nulls only. Process-local callbacks retain every pattern's confidence and adjusted family p-value, including the alternative's power; callbacks are restored in a finally block. Production files and inference definitions are untouched. Retained JSON includes all 600 attempts per cell, the pilot Boolean-attempt SHA-256, retained-p-value SHA-256, source hash, and cell runtimes. All draws are retained; none are dropped or conditioned on signs.

### Conservative tie treatment in the diagnostic block variant

With only three blocks, there are eight distinct Rademacher sign vectors. The all-positive bootstrap draw is mathematically equal to the observed statistic. The raw production comparison can miss this tie due to binary64 evaluation order, giving artificial small p-values and spurious rejections. The raw-kernel full matrix is retained separately. The diagnostic block variant counts a statistic as an exceedance when it is greater than or equal to the observed value **or** `numpy.isclose(bootstrap, observed, rtol=1e-12, atol=1e-12)`. The same conservative tie rule is used in the block family maximum stepdown. The denominator remains `999 + 1`, with the usual plus-one numerator. Month and quarter kernels remain unchanged. This adjustment is diagnostic only and is not a proposed change to the declared method.

Run from the worktree:

```text
.venv/Scripts/python.exe scripts/research/diagnose_swing_dependence.py --output docs/PHASE_2C_DEPENDENCE_DIAGNOSTIC_RESULTS.json
.venv/Scripts/python.exe scripts/research/diagnose_swing_dependence.py --raw-kernel --output docs/PHASE_2C_DEPENDENCE_DIAGNOSTIC_RAW_KERNEL_RESULTS.json
```

## Results

Rates are percentages; brackets are two-sided 95% Wilson Monte Carlo intervals. Confidence size is the largest individual true-null rejection rate at the 2.5% gate (its interval is marginal, not simultaneous across patterns). Family size is the probability of rejecting any true null at the 5% adjusted gate. Partial-null power is EMA pullback rejection probability, shown for both gates. Complete-null power is not defined. Full pattern-specific counts and intervals are in the JSON.

### Complete null (000)

| Shock months | Method | Confidence size % [95% MC] | Family size % [95% MC] | Seconds |
| - | - | - | - | - |
| 1 | month_wcr_s | 2.83 [1.78, 4.49] | 5.17 [3.66, 7.24] | 9.00 |
| 1 | quarter_wcr_s | 2.50 [1.52, 4.08] | 3.83 [2.57, 5.69] | 4.94 |
| 1 | block_wild | 2.83 [1.78, 4.49] | 5.17 [3.66, 7.24] | 18.90 |
| 3 | month_wcr_s | 10.67 [8.44, 13.39] | 15.83 [13.13, 18.97] | 10.23 |
| 3 | quarter_wcr_s | 3.33 [2.17, 5.09] | 5.67 [4.08, 7.81] | 6.15 |
| 3 | block_wild | 3.33 [2.17, 5.09] | 5.67 [4.08, 7.81] | 10.59 |
| 6 | month_wcr_s | 17.00 [14.21, 20.21] | 23.17 [19.97, 26.71] | 9.59 |
| 6 | quarter_wcr_s | 8.83 [6.82, 11.37] | 14.00 [11.45, 17.01] | 6.14 |
| 6 | block_wild | 2.17 [1.27, 3.67] | 5.50 [3.94, 7.62] | 8.54 |
| 12 | month_wcr_s | 23.50 [20.28, 27.05] | 28.00 [24.56, 31.72] | 9.67 |
| 12 | quarter_wcr_s | 17.00 [14.21, 20.21] | 23.33 [20.13, 26.88] | 5.96 |
| 12 | block_wild | 0.00 [0.00, 0.64] | 0.00 [0.00, 0.64] | 6.94 |

### Partial null (d00)

| Shock months | Method | Confidence size % [95% MC] | Family size % [95% MC] | Confidence power % [95% MC] | Family power % [95% MC] | Seconds |
| - | - | - | - | - | - | - |
| 1 | month_wcr_s | 2.33 [1.39, 3.88] | 4.67 [3.25, 6.66] | 65.50 [61.61, 69.19] | 62.50 [58.56, 66.28] | 9.08 |
| 1 | quarter_wcr_s | 2.00 [1.15, 3.46] | 3.83 [2.57, 5.69] | 61.00 [57.04, 64.82] | 56.00 [52.00, 59.92] | 6.15 |
| 1 | block_wild | 2.33 [1.39, 3.88] | 4.67 [3.25, 6.66] | 65.50 [61.61, 69.19] | 62.50 [58.56, 66.28] | 21.73 |
| 3 | month_wcr_s | 9.67 [7.55, 12.29] | 15.83 [13.13, 18.97] | 63.17 [59.23, 66.93] | 59.67 [55.69, 63.52] | 9.68 |
| 3 | quarter_wcr_s | 3.33 [2.17, 5.09] | 5.33 [3.80, 7.43] | 33.50 [29.84, 37.37] | 31.83 [28.23, 35.67] | 6.09 |
| 3 | block_wild | 3.33 [2.17, 5.09] | 5.33 [3.80, 7.43] | 33.50 [29.84, 37.37] | 31.83 [28.23, 35.67] | 10.90 |
| 6 | month_wcr_s | 17.00 [14.21, 20.21] | 22.50 [19.34, 26.01] | 58.00 [54.01, 61.89] | 56.00 [52.00, 59.92] | 9.76 |
| 6 | quarter_wcr_s | 8.83 [6.82, 11.37] | 13.33 [10.85, 16.29] | 39.67 [35.83, 43.63] | 37.83 [34.04, 41.78] | 6.26 |
| 6 | block_wild | 2.00 [1.15, 3.46] | 4.00 [2.70, 5.88] | 11.33 [9.04, 14.12] | 14.17 [11.60, 17.19] | 8.43 |
| 12 | month_wcr_s | 23.50 [20.28, 27.05] | 27.17 [23.76, 30.86] | 57.67 [53.68, 61.56] | 56.17 [52.17, 60.09] | 9.28 |
| 12 | quarter_wcr_s | 16.83 [14.05, 20.04] | 21.83 [18.71, 25.31] | 44.00 [40.08, 48.00] | 42.83 [38.93, 46.83] | 5.69 |
| 12 | block_wild | 0.00 [0.00, 0.64] | 0.00 [0.00, 0.64] | 0.00 [0.00, 0.64] | 0.00 [0.00, 0.64] | 6.51 |

Four worker processes completed the conservative matrix in 55.81 seconds wall time, with 216.19 seconds summed cell elapsed time. The raw-kernel matrix took 45.61 seconds wall time. Cell runtimes include callback retention and diagnostics; they are hardware/load dependent and are not extrapolated to promotion counts. Both source hashes match f458dcf5eca0d222c567ea6e2c650b92970e2831405a6c74ffea852be5f01209.

## Findings and limits

F1 is reproduced: complete-null month-clustered family size rises from 5.17% for independent monthly shocks to 15.83%, 23.17%, and 28.00% under 3-, 6-, and 12-month persistence. Quarter-clustered family size is 5.67%, 14.00%, and 23.33% for those persistent cases. The 600-run uncertainty is too small to explain the large persistent-shock inflation. The apparently higher month-clustered power accompanies invalid size and is not a fair power advantage.

The aligned block alternative reduces persistent-shock size but does not establish an adequate method. At six-month persistence there are only six blocks; alternative confidence power falls to 11.33%. At twelve-month persistence there are only three blocks and eight distinct signs: the exact sign distribution has minimum attainable tail probability 1/8, so 2.5% and 5% rejection gates cannot provide useful power. The conservative Monte Carlo realization makes no rejections and no power in these cells. A zero observed rejection rate has Wilson upper bound about 0.64%, not proof of zero underlying rejection probability for the finite random-draw procedure.

The raw twelve-month block kernel produces complete-null family size 3.33 [2.17, 5.09]% and partial-null confidence power 7.33 [5.51, 9.70]%, despite the discrete sign floor. These are numerical-tie artifacts, not validated inference or evidence of useful three-block power. Review this separately before any future method declaration; no production change is authorised or made by this diagnostic.

This is one Gaussian generator, one shared-shock strength, one 36-month sample, one partial null, one effect, and one deterministic shock alignment. It omits empirical skew, terminal mixtures, imbalance, shifted boundaries, alternative block lengths, other partial-null configurations, and longer histories. It does not run the mandatory 20,000/100,000 outer or 9,999 inner promotion audit or adjudicate its size caps. The intervals are marginal Monte Carlo intervals, not multiplicity-adjusted declarations; around nominal 5% size their half-width is roughly 1.8 percentage points, while power intervals can be about 4 points. No method recommendation is adopted: the current method remains pending the user's review and authorised next steps.

## Verification

- The two retained full matrices contain 24 cells × 600 attempts each and 999 inner draws per attempt. The diagnostic-only pilot eligibility guard passes.
- Sixteen diagnostic-harness and existing method-audit tests passed, including paired-equivalent cluster definitions and conservative three-block sign-floor behavior.
- Ruff and Bandit pass for the diagnostic script; Black passes for the diagnostic script and its test. Full-worktree Black is delegated to the integration check after concurrent authorised corrections finish. Every task includes Bandit and `black --check .` in verification.

Artifacts: `scripts/research/diagnose_swing_dependence.py`, `docs/PHASE_2C_DEPENDENCE_DIAGNOSTIC_RESULTS.json`, `docs/PHASE_2C_DEPENDENCE_DIAGNOSTIC_RAW_KERNEL_RESULTS.json`, and `tests/domain/backtester/test_swing_dependence_diagnostic.py`.
