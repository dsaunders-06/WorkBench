# Phase 2 authoritative swing engineering runbook

Phase 2C is an offline engineering replay. It does not authorize a strategy, open a promotion-tier observation, change deployed settings, contact a broker, or access the running application. The governing design is [the Phase 2 authoritative swing specification](superpowers/specs/2026-10-01-phase-2-authoritative-swing-strategy-design.md), with the approved [Phase 2C implementation plan](superpowers/plans/2026-10-01-phase-2c-swing-validation-reporting.md).

## Run the frozen engineering inputs

From the repository root, using the repository virtual environment:

```powershell
.\.venv\Scripts\python.exe scripts/research/run_authoritative_swing.py --catalog synthetic-golden --partition development --out data/phase2-engineering-synthetic
.\.venv\Scripts\python.exe scripts/research/run_authoritative_swing.py --catalog static-asx --engineering-mode strict_authoritative --partition development --out data/phase2-engineering-static
```

The command prints the absolute append-only bundle directory and exits `0` when the engineering input and all four replay arms are valid. It exits `2` for invalid data, configuration, an existing semantic run directory, or a promotion-tier capability. Repeating the same run requires a new output root; existing evidence is never overwritten. The optional `--ambiguity-policy optimistic` and `--volume-multiplier` arguments create separate non-promotional engineering sensitivity runs.

For a signed *engineering synthetic* shard, provide `--catalog <catalog.json> --shard-root <authorized-signal-directory> --shard-id <exact-id> --verification-key-file <public-key-file>`. The shard must match `--partition`. The loader verifies the signature, hashes, schema, exact split-only bar representation, calendar, membership, corporate actions, and physical shard scope before replay. The same non-promotional sensitivity matrix used for the built-in fixture is run on signed engineering shards. Promotion-tier catalogs and service profiles are rejected. A production packager must run `validate_packaging_bar_coverage` for every member and preflight-held symbol on every tradable official session, with documented suspensions or delistings for untradeable intervals. The replay retains an independent held-symbol gap guard.

The synthetic fixture uses verified split-only bars and a fixed decision schedule to exercise the offline fill and portfolio path. It is a software test, not an estimate of strategy edge. The static ASX cache is a survivorship-biased 95-symbol snapshot. Each file has 500 sessions, but the union has 501 dates: STW.AX begins on 23 August 2024 and has no 24 October 2025 bar, while the other 94 begin on 26 August 2024. No missing bar or benchmark price is carried or fabricated. The static bars are vendor-adjusted and lack authoritative as-traded prices, corporate-action lineage, finalized calendar provenance, and enough multi-year resistance history. Strict mode records `STATIC_PROVENANCE_UNVERIFIED` and `INSUFFICIENT_RESISTANCE_HISTORY` abstentions before any trade. Mechanical diagnostic mode counts pre-resistance geometry for planning only; it cannot produce fills, edge claims, or promotion evidence.

## Partition and terminal boundaries

A promotion dataset needs signed, physically separate signal and 63-official-session outcome-tail shards for development, validation, and holdout. Allocate complete signal months 50/20/30, with at least 36 complete holdout months. Do not join a calendar month split by a partition or tail. The named sessions are `T0` first input, `T1` final entry fill, `T10` last normal exit session, `T11` first subsequent tail session, `T64` terminal valuation, and `T65` first excluded session. An entry belongs to the partition of its *fill*, not its signal. A forward-only holdout extension uses a new signed catalog content hash with `parent_dataset_id` linking to the prior catalog; development, validation, and the original holdout start remain frozen. No new instruction is emitted after the final entry boundary. The 63-session tail resolves entries, halts, dividends, and delistings without borrowing the next partition. A halted position is held at its last traded close as a stale mark until resumption; a due exit executes at the first resumed open under normal gap/stop ordering. If still unresolved at `T64`, it receives the terminal zero rule unless consideration is documented. It is not zeroed at halt onset in baseline replay.

Each calendar row contains `calendar_date`, `session_kind`, `open_time`, `close_time`, `source`, `source_version`, `source_notice`, `reason`, `retrieved_at`, `source_hash`, and `finalized`. Full and shortened sessions must have verified trading hours; ad hoc closures, scheduled closures, and weekends have a documented reason. The signed ledger covers every civil day without gaps, and only full or shortened rows are tradable. Market events and the benchmark must align with this ledger.

## Method, incidence, and risk gates

The primary edge measure is net `R_order` for eligible signal-level trades; `R_fill` is diagnostic. Each pattern is an independent hypothesis, with common entry-month weights for WCR-S and one-sided Romano–Wolf adjustment. The published WCR-S intercept-only specialization uses CV1 standard errors and raw restricted month scores because the null fixes the only coefficient. The method-size audit must be declared before outcomes are opened and pass every mandatory scenario, including terminal contamination and partial nulls. The power and duration planner then determines required trades, nonempty month clusters, and forward holdout months. No sensitivity run enters the baseline family.

The support-matched reference extract permits only exposure, issuer, date, market cap, and event incidence fields. It is blinded to the post-signal trade outcomes. Incidence buckets require exposure support, planned merges, cluster and exact bounds, and terminal weights. The structural risk sweep places the calibrated terminal loss at every eligible funded trade/session pair, compares each with an independently computed exact-decimal replay, and checks the Phase 4 single-position and drawdown policy. Zero at *halt onset* belongs only to this stress sweep. A real Phase 4 policy, declared bundle, permit, rehearsal, first-exposure receipt, and sealed holdout controls remain Phase 2D work. Phase 2 opens no promotion-tier observation.

`FeasibilityStatus` maps to operator handling as follows:

| Feasibility result | Phase 2/Phase 2D handling | Operator action |
| --- | --- | --- |
| `FEASIBLE` | Still `PORTFOLIO_RISK_DESIGN_PENDING` in Phase 2; never an automatic pass | Complete incidence, structural, Phase 4, declaration, and permit gates |
| `DATASET_INSUFFICIENT` | `INSUFFICIENT_EVIDENCE` when promotion controls are otherwise reached | Acquire untouched forward holdout months and rerun the declared plan |
| `FREQUENCY_INADEQUATE_WITHIN_MAX_HORIZON` | `INSUFFICIENT_EVIDENCE` | Do not extend within the declared 120-month horizon; redesign through a new lineage |

Invalid integrity or terminal parity gives `INVALID`; support failure gives `INCIDENCE_DATA_INSUFFICIENT`; failed structural sweep gives `PORTFOLIO_RISK_STRUCTURALLY_INFEASIBLE`; a failed method audit gives `METHOD_INADEQUATE`. Conservative terminal sensitivity can give `TERMINAL_OUTCOME_SENSITIVE`, and a passing edge with unsafe cash portfolio gives `EDGE_PASS_PORTFOLIO_RISK_BLOCKED`. Phase 2 cannot emit `PASS`.

## Evidence bundle

`manifest.json` identifies the tier, catalog/shard, numeric and cost policies, boundaries, method, incidence, feasibility, and sensitivities. `decisions.jsonl`, `fills.csv`, `trades.csv`, and `equity.csv` retain ordered replay evidence and exact decimal strings. `metrics.json`, `promotion.json`, `method_audit.json`, `feasibility.json`, and `reference_incidence.json` retain separate analyses. `report.md` leads with the survivorship warning for engineering inputs and presents each pattern separately from the combined cash portfolio. `SHA256SUMS` covers every artifact file. The semantic run ID excludes packaging time and output path. The report's uncapped portfolio is a concentration and gap-risk stress case, not a deployable forecast.
