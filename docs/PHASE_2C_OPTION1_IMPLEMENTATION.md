# Phase 2C Option 1 correction report

This report records the operator's follow-up to the accepted Phase 2C corrections
at `90f2589`. Work is on `recovery/phase-2-authoritative-strategy`. It does not
open promotion-tier observations or issue a method declaration.

| Item | Result | Test-first evidence |
| --- | --- | --- |
| 1. Exit-session onsets | Terminal-tail and simultaneous-two-issuer simulations now include every official onset session after entry through the scheduled exit. An exit-session onset removes the scheduled proceeds exactly, matching the deterministic structural sweep. | Three parity tests failed before the correction and passed afterward. |
| 2. Exact bootstrap ties | All `2^G` Rademacher vectors are enumerated when they fit within the declared draw count. Equality counts as an exceedance; larger designs use the declared `1e-12` relative tolerance. The three-cluster floor is `1/8`. | Three-cluster, all-positive and reference-oracle regressions failed under the old sampled/tie rule and passed after the change. |
| 3. Production candidates | Entry-month WCR-S, fixed consecutive three-month WCR-S and aligned block-cluster wild bootstrap share the one-sided p-value and Romano–Wolf path. All use the same monthly base weight draws in paired audits. `G >= 6` is required because the exact p-value floor is `1/64`, below both 2.5% and 5%; `G = 5` has floor `1/32`, above the confidence gate. | Candidate and eligibility tests passed; grouped replay inference uses the selected cluster count. |
| 4. Selection | Each declared candidate receives paired size and power evidence. All mandatory size cells must pass the existing 20,000/100,000 sequential caps. The qualifying candidate with the highest minimum projected power at `delta_MME` wins; ties use the larger supported cluster count. Pattern-specific `N_required` and `G_required` are recomputed under the winner. No qualifier returns `METHOD_INADEQUATE`. | Selection, tie, incomplete-pattern, forged-cluster, ineligible-candidate and no-qualifier tests passed. |
| 5. Scenario matrix | Calibrated development/validation block resampling preserves joint pattern months and partition boundaries. Generic 1–4-month persistent shocks are mandatory under the independent market proxy; 6- and 12-month shocks are disclosed sensitivities. Complete and one-/two-null configurations, imbalance, skew and terminal envelope are represented in the frozen matrix builder. | Matrix and paired-input hash tests passed. |
| 6. Market-regime proxy | The [source audit](phase-2-market-regime-proxy.md) uses 200 complete ASX 200 month-end values from January 2010 to August 2026 and 4,205 daily ^AXJO closes. It reports all lag-1–12 autocorrelations and the 1–4-month recommendation. RBA F18 supports the Yahoo value for September 2023; no accessible official third July 2014 close was found, so the ASX July value is retained and a Yahoo-substitution sensitivity gives the same recommendation. | Nine focused source-validator tests passed; the regeneration script reproduced the report and exited 0. All five input snapshots are hashed and stored outside Git. |
| 7. Documentation | The operator's Option 1 amendment is in specification section 16 and the Phase 2C plan. [The unsigned draft](METHOD_AUDIT_DECLARED_UNSIGNED_DRAFT.json) records three candidates, aligned block length `L = 4`, eligibility, selection, scenario matrix, proposed seeds and caps. `delta_MME`, calibration instances and pilot evidence remain unresolved. | Draft parses as JSON; no declaration was signed, submitted or timestamped. |
| 8. Raw outputs | New raw simulation and source outputs are excluded from Git. The two existing diagnostic JSON files remain untouched. [The handling note](PHASE_2C_RAW_OUTPUT_HANDLING.md) gives the external output location, hash manifest and regeneration command. | Ignore rules and tracked-file status were checked. |

The ASX month-end source has two value discrepancies above the 0.1-percentage-point
return gate: July 2014 (`5623.9` ASX versus `5632.8999` Yahoo) and September
2023 (`7084.6` ASX versus `7048.6001` Yahoo). The repository calendar and Yahoo
bars agree on 31 July 2014 and 29 September 2023 as final trading dates; an ASX
cash-market report independently confirms the latter, while July remains a
rules-based inference. The RBA September return differs from Yahoo by
0.010029 percentage point and from ASX by 0.482760 point. The July source
sensitivity changes no persistence recommendation. The source audit records
the full values, dates, URLs and hashes.

Verification: the affected backtester tests and source-validator tests pass;
`ruff check .`, `black --check .` with Black 26.5.1, `mypy src` and
`bandit -q -r src` pass. Full `python -m pytest -q` completed with 4,275 passed
and 26 skipped. GitHub CI is checked on the pushed commit.
