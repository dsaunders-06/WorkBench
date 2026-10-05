# Phase 2D Promotion Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish independently timestamped research declarations and, only
after Phase 4 risk rules and refreshed development/validation evidence are
final, build the operator-controlled services that can expose one frozen
holdout without giving the automated agent access to shards, keys, or arbitrary
output channels.

**Architecture:** Phase 2D has two activation stages. Stage A runs before the
first Phase 4 promotion-tier outcome and contains only the Declaration Authority,
blinded structural extractor, and development/validation release gates. Stage B
runs after Phase 4 and the statistical/structural planners pass. It packages a
hermetic promotion bundle, operates scoped append-only ledger and sealed-data
services under separate accounts, validates all output through a trusted
artifact writer, rehearses the exact deployment against a holdout-scale
synthetic shard, and issues one signed permit.

**Prerequisites:** Phase 2A/2B/2C engineering complete; Phase 2 checkpoint status
`PORTFOLIO_RISK_DESIGN_PENDING`; no promotion-tier observation previously
released. Stage B additionally requires frozen Phase 4 rules and refreshed
development/validation results under their final fingerprint.

**Spec:** `docs/superpowers/specs/2026-10-01-phase-2-authoritative-swing-strategy-design.md`

## Global Constraints

- The operator or appointed data custodian owns signing and decryption keys;
  they are unavailable to the repository, runner, and automated agent.
- Promotion development, validation, holdout, and tail shards use physically
  separate encryption capabilities and release receipts.
- Every declaration carries an RFC 3161 timestamp token. Internal service time
  alone cannot authorize promotion-tier development.
- `DATA_OPENED` is committed before any holdout plaintext byte or handle leaves
  the service. Every post-open failure consumes the holdout.
- Phase 2D v1 has no checkpoint/resume path. A restarted exact bundle is
  reproduction-only.
- The promotion runner has no network, DNS, clipboard, child-process, broker,
  interactive credential, arbitrary IPC, or arbitrary filesystem access.
- A trusted writer accepts typed records only and enforces schema and output
  budgets. The runner cannot create final artifacts directly.
- Administrators and anyone able to replace service binaries are explicitly
  outside the protection boundary.
- The operator, custodian, and permit signer may be the same human, but the
  custodian, signing, service, and automated-agent identities use distinct
  least-privilege accounts and separately controlled keys. The runbooks state
  the actual role assignment and never claim independent human review or dual
  control when one person fills multiple roles.

## Stage A — Before Phase 4 promotion-tier outcomes

### Task 1: Declaration Authority and independently timestamped receipts

Required verification for this task (Stage A released by operator):

Run: `.\.venv\Scripts\python.exe -m bandit -r src -q`
Run: `.\.venv\Scripts\python.exe -m black --check .`


**Files:**
- Create: `src/qat/promotion/declarations.py`
- Create: `src/qat/promotion/rfc3161.py`
- Create: `tests/promotion/test_declarations.py`
- Create: `docs/phase-2d-declaration-runbook.md`

**Interfaces:**
- Produces: `DeclarationRecord`, `DeclarationReceipt`,
  `append_declaration()`, `verify_declaration_chain()`, and
  `verify_timestamp_token()`.

- [x] **Step 1: Write failing lineage, signature, and time tests**

```python
def test_all_required_declarations_precede_development_release() -> None:
    chain = declaration_chain()
    assert chain.names == (
        "EFFECT_DECLARED",
        "PROMOTION_PROTOCOL_DECLARED",
        "METHOD_AUDIT_DECLARED",
    )
    assert all(r.rfc3161_token.valid for r in chain.records)

def test_backdated_or_reordered_record_fails() -> None:
    with pytest.raises(DeclarationLineageError):
        verify_declaration_chain(reordered_or_backdated_chain())

def test_agent_cannot_sign_or_initialize_ledger() -> None:
    with pytest.raises(SigningAuthorityError):
        append_declaration(agent_context(), effect_declaration())
```

Also test previous-head, sequence, nonce, operator identity, strategy-spec hash,
catalog identity, immutable payload, timestamp certificate chain, revoked/expired
certificate handling, and offline receipt verification.

- [x] **Step 2: Implement the minimal authority**

Run it under an operator-controlled non-interactive account. Store a scoped,
append-only hash chain and return signed receipts. `EFFECT_DECLARED` binds
positive `delta_MME` and rationale. `PROMOTION_PROTOCOL_DECLARED` binds every
data, Phase 4 risk, tail, statistical, feasibility, and promotion threshold.
`METHOD_AUDIT_DECLARED` binds the generic pilot report, WCR-S implementation,
complete scenario matrix, generators, seeds, caps, and code hashes. Anchor each
signed digest with RFC 3161 and bind every later record to the preceding head.

- [x] **Step 3: Verify and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/promotion/test_declarations.py -q`

```powershell
git add src/qat/promotion/declarations.py src/qat/promotion/rfc3161.py tests/promotion/test_declarations.py docs/phase-2d-declaration-runbook.md
git commit -m "feat: record promotion research declarations"
```

### Task 2: Blinded structural extractor and development release gate

Required verification for this task (Stage A released by operator):

Run: `.\.venv\Scripts\python.exe -m bandit -r src -q`
Run: `.\.venv\Scripts\python.exe -m black --check .`


**Files:**
- Create: `src/qat/promotion/structural_extract.py`
- Create: `src/qat/promotion/development_release.py`
- Create: `tests/promotion/test_structural_extract.py`
- Create: `tests/promotion/test_development_release.py`

**Interfaces:**
- Produces: `ReferenceViewReleaseReceipt`, `StructuralExtractReceipt`,
  `DevelopmentReleaseReceipt`, `authorize_reference_view()`,
  `derive_structural_view()`, `authorize_development()`, and
  `authorize_validation()`.

- [x] **Step 1: Write failing information-flow tests**

```python
def test_structural_extract_contains_no_forward_outcome() -> None:
    view = derive_structural_view(custodian_development_handle())
    assert set(view.schema) == allowed_structural_fields()
    assert no_identifiers_join_to_later_rows(view)

def test_reference_view_release_excludes_holdout() -> None:
    access = authorize_reference_view(custodian_reference_handle())
    assert access.latest_receipt.state == "REFERENCE_VIEW_RELEASED"
    assert access.maximum_session < catalog().holdout_start
    assert all(w.end < catalog().holdout_start for w in access.exposure_windows)

def test_raw_development_requires_three_timestamped_declarations() -> None:
    with pytest.raises(DevelopmentLockedError):
        authorize_development(chain_missing_method_declaration())

def test_release_receipt_precedes_handle_return() -> None:
    access = authorize_development(valid_chain())
    handle = access.open()
    assert access.latest_receipt.state == "DEV_DATA_RELEASED"
    assert handle.shard_id == declared_development_shard_id()

def test_semantics_preserving_bugfix_requires_logged_rerun_authority() -> None:
    with pytest.raises(DevelopmentLockedError):
        open_development(replacement_bundle(), previous_release())
    access = authorize_development_rerun(reviewed_bugfix_receipt())
    assert access.latest_receipt.state == "DEV_RERUN_AUTHORIZED"

def test_rerun_receipt_binds_discovery_and_differential_proof() -> None:
    receipt = reviewed_bugfix_receipt()
    assert receipt.discovery_channel in {"failing_test", "reference_oracle", "outcome_anomaly"}
    assert receipt.first_observed_at < receipt.patch_authored_at
    assert receipt.visible_outcome_artifacts == disclosed_examined_artifacts()
    assert receipt.pre_patch_failure_hash == failing_conformance_test_hash()
    assert receipt.permitted_changed_artifacts == predeclared_defect_scope()
    assert receipt.unchanged_artifact_digest == byte_identical_control_digest()
    assert receipt.changed_artifact_digest == independent_oracle_digest()

def test_outcome_triggered_change_without_independent_oracle_starts_new_lineage() -> None:
    with pytest.raises(NewDeclarationLineageRequired):
        authorize_development_rerun(outcome_triggered_patch_without_oracle())

def test_parameter_or_policy_change_cannot_be_called_semantics_preserving() -> None:
    for patch in (changed_threshold(), changed_calendar(), changed_numeric_policy()):
        with pytest.raises(NewDeclarationLineageRequired):
            authorize_development_rerun(reviewed_patch(patch))

def test_changed_bundle_cannot_regain_holdout_freshness_after_data_opened() -> None:
    with pytest.raises(FreshHoldoutRequired):
        authorize_holdout_rerun(
            ledger=ledger_with_data_opened(),
            replacement_bundle=semantics_preserving_bugfix_bundle(),
        )

def test_engine_dependency_change_expires_structural_extract() -> None:
    assert not structural_receipt().valid_for(bundle_with_changed_detector())
```

Before returning the field-limited reference view, append
`REFERENCE_VIEW_RELEASED` with schema, row and issuer counts, maximum session,
source-record hashes, output hash, catalog, and release identity. Reject exact
market-cap/traded-value paths, OHLC, strategy signals, forward outcomes, any
row at or after holdout start, and any ten-session exposure window crossing it.

The structural-extract allowlist is signal-time stop distance, pattern/candidate count,
contemporaneous rejection reason, price/liquidity bucket, cost-to-planned-risk,
quantity, notional, and frequency by pattern and complete calendar month. Deny
post-signal prices, entry fills, exits, P&L, R, MFE, MAE, win rate, profit
factor, drawdown, and joinable signal identifiers. Record
`DEV_STRUCTURE_DERIVED` with extractor/input/output hashes before returning the
aggregate.

The development gate verifies all declarations and tokens, catalog/shard,
runner bundle, scope, and prior head; it appends `DEV_DATA_RELEASED` before
returning the scoped handle and `DEV_DATA_OPENED` for every actual open.
Development observations may be replayed, but the service never issues an
unlogged reusable bearer capability. A semantics-preserving bug repair needs an
operator-reviewed `DEV_RERUN_AUTHORIZED` receipt binding the signed defect
dossier, failed run, exact diff, replacement bundle, unchanged specification,
permitted changed artifacts, and differential comparison results. The dossier
records discovery time and actor, discovery channel, data tier and every outcome
already visible, original symptom and hypothesis, a pre-patch failing
conformance test or independent reference oracle, the predeclared affected
scope, bundle hashes, and expected differential digest. Outputs outside that
scope must be byte-identical; outputs inside it must match the oracle. The
replacement must pass determinism, complete prefix invariance, reference parity,
isolation, and full regression gates.

An outcome-triggered defect remains permanently disclosed. It may retain the
lineage only when the unchanged frozen contract and an independent oracle prove
the correction without selecting a favorable result. Otherwise require a new
declaration lineage. Any new parameter, threshold, exception, data-dependent
branch, or strategy, eligibility, calendar, numeric, cost, sizing, or inference
change is not semantics-preserving and replays development from the beginning.
No changed bundle can regain holdout freshness after `DATA_OPENED`.

`DEV_STRUCTURE_DERIVED` binds an explicit dependency-closure hash covering the
extractor, pattern engine, eligibility, normalization, official calendar,
numeric, cost, and sizing code plus schema and source shard. It is reusable
across a report-writer-only change, but any dependency change requires a fresh
extract and receipt. Validation remains locked until development
artifacts and fingerprint are frozen, then follows the same flow with
`VALIDATION_DATA_RELEASED`.

- [x] **Step 2: Verify and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests/promotion/test_structural_extract.py tests/promotion/test_development_release.py -q`

```powershell
git add src/qat/promotion/structural_extract.py src/qat/promotion/development_release.py tests/promotion/test_structural_extract.py tests/promotion/test_development_release.py
git commit -m "feat: gate blinded structural and development access"
```

## Stage B — After Phase 4 and development/validation freeze

### Task 3: Reproducible reviewed promotion bundle

Required verification for this task (Stage B not released):

Run: `.\.venv\Scripts\python.exe -m bandit -r src -q`
Run: `.\.venv\Scripts\python.exe -m black --check .`


**Files:**
- Create: `scripts/promotion/build_bundle.ps1`
- Create: `src/qat/promotion/bundle.py`
- Create: `tests/promotion/test_bundle.py`
- Create: `docs/phase-2d-review-checklist.md`

Build a content-addressed read-only bundle containing reviewed source/commit,
QAT wheel, pinned CPython runtime, hash-locked wheels/native DLLs, configuration,
schemas, entrypoint, SBOM, and reproduction metadata. Two clean builds must
produce the same semantic digest. The operator reviews the exact diff and signs
the bundle digest; another model may assist but cannot authorize.

The checklist covers dependency/native changes, all I/O and egress, absence of
network/process/broker/credential access, permit states, raw-data leakage,
artifact budgets, determinism, prefix invariance, reference parity, and failure
behavior.

### Task 4: Scoped ledger, sealed-data service, and trusted artifact writer

Required verification for this task (Stage B not released):

Run: `.\.venv\Scripts\python.exe -m bandit -r src -q`
Run: `.\.venv\Scripts\python.exe -m black --check .`


**Files:**
- Create: `src/qat/promotion/ledger_service.py`
- Create: `src/qat/promotion/sealed_data_service.py`
- Create: `src/qat/promotion/artifact_gateway.py`
- Create: `src/qat/promotion/holdout_runner.py`
- Create: `tests/promotion/test_ledger_service.py`
- Create: `tests/promotion/test_sealed_data_service.py`
- Create: `tests/promotion/test_artifact_gateway.py`
- Create: `tests/promotion/test_holdout_runner.py`

Use a scoped chain keyed by strategy, catalog, and holdout window. Signed head
attestations include scoped sequence/head and a global service checkpoint.
`SCOPE_RESERVED` normally expires in 24 hours and never later than 72 before
data open. Only the operator may cancel or expire it. Other scopes cannot stale
the permit; another append in the same scope does.

The sealed-data service verifies the signed permit and atomically records
`DATA_OPENED` before returning any plaintext byte or handle. Prefer ACL-protected
authenticated named-pipe streaming on one Windows host or mutually authenticated
streaming across hosts. The automated agent has no file or key access.

The writer accepts only canonical typed decisions, fills, trades, equity,
metrics, verdicts, and receipts. Enforce field length, row count, file count,
total bytes, allowed decimal precision, and forbidden raw-bar fields. Reject
arbitrary logs or undeclared output.

Keep every permit, service-client, streaming, ledger, and trusted-writer import
under `qat.promotion`. Pure strategy and `qat.domain.backtester` modules expose
only data and replay interfaces and cannot import `qat.promotion`; the promotion
runner depends inward on them. Transitive-import and runtime isolation tests
must prove the engineering research path cannot reach these I/O clients.

### Task 5: Holdout-scale rehearsal and failure injection

Required verification for this task (Stage B not released):

Run: `.\.venv\Scripts\python.exe -m bandit -r src -q`
Run: `.\.venv\Scripts\python.exe -m black --check .`


**Files:**
- Create: `tests/integration/test_phase2d_rehearsal.py`
- Create: `scripts/promotion/run_rehearsal.ps1`
- Create: `docs/phase-2d-rehearsal-runbook.md`

Run the exact bundle and deployed service binaries against a holdout-scale
synthetic sealed shard in a separate rehearsal ledger/key namespace. Measure
p50/p95/p99 runtime, peak memory, disk, stream volume, and artifact size. The
p99 runtime must be less than half the execution lease.

Inject refusal before reservation, failure after reservation and before data,
failure to append `DATA_OPENED`, stream interruption, runner termination,
insufficient disk, writer rejection, and final-ledger failure. Confirm pre-open
failure is replaceable and every post-open failure is consumed. Phase 2D v1 has
no resume. Bind runner, services, packager, schemas, configuration, environment,
fixture, measurements, and rehearsal ledger into a signed receipt. Any change
expires it.

### Task 6: Permit, promotion run, and permanent failure semantics

Required verification for this task (Stage B not released):

Run: `.\.venv\Scripts\python.exe -m bandit -r src -q`
Run: `.\.venv\Scripts\python.exe -m black --check .`


**Files:**
- Create: `src/qat/promotion/permit.py`
- Create: `scripts/promotion/run_holdout.py`
- Create: `tests/promotion/test_permit.py`
- Create: `tests/integration/test_phase2d_holdout_protocol.py`
- Create: `docs/phase-2d-promotion-runbook.md`

The permit binds all declarations and timestamp tokens, promotion bundle,
review receipt, rehearsal receipt, exact signal/tail shards, `T0/T1/T10/T11/T64/T65`,
complete official-calendar ledger hash and tradable-session projection,
numeric/cost/fill/Phase 4 policies, incidence/method/power/frequency results,
scoped ledger head, nonce, and approval time.

Refuse a permit for `INCIDENCE_DATA_INSUFFICIENT`,
`PORTFOLIO_RISK_STRUCTURALLY_INFEASIBLE`, `METHOD_INADEQUATE`, or infeasible
duration. Treat both `DATASET_INSUFFICIENT` and
`FREQUENCY_INADEQUATE_WITHIN_MAX_HORIZON` as
`INSUFFICIENT_EVIDENCE`; retain the exact planner reason in the refusal receipt.
`FEASIBLE` only permits evaluation of the remaining gates and never authorizes a
permit or `PASS` by itself. Add permit tests for every feasibility value and a
runbook table mapping planner status, promotion status, exit code, operator
action, and whether forward acquisition could help.

If development/validation structural evidence causes a Phase 4 policy
revision, close the current lineage and issue a new
`PROMOTION_PROTOCOL_DECLARED` lineage; re-sign carried-forward effect/method
declarations, refresh every affected structural receipt, and replay development
and validation. The original sealed holdout remains eligible only if no
`DATA_OPENED` exists for its scope, its bytes and window are unchanged, and all
feasibility inputs are recomputed before a new permit.

Progress through `EXPOSURE_RESERVED`, `DATA_OPENED`, and `COMPLETED`,
`FAILED_PRE_EXPOSURE`, `FAILED_AFTER_EXPOSURE`, or descriptive
`FAILED_INFRASTRUCTURE_AFTER_EXPOSURE`. A crash, sleep, restart, lease expiry,
or infrastructure failure after `DATA_OPENED` consumes the holdout even when no
artifact was released. Exact-bundle reruns are reproduction-only. Configure the
host to disable sleep, hibernation, automatic restart, and updates during the
run. The runbook states the expected runtime and permanent consequence before
the operator requests a permit.

### Task 7: Independent security and end-to-end verification

Required verification for this task (Stage B not released):

Run: `.\.venv\Scripts\python.exe -m bandit -r src -q`
Run: `.\.venv\Scripts\python.exe -m black --check .`


- [ ] Verify declaration lineage and RFC 3161 certificates offline.
- [ ] Prove agent/development accounts cannot read promotion shards or keys.
- [ ] Prove network, DNS, child process, clipboard, broker, arbitrary IPC, and
      arbitrary filesystem calls fail inside the runner sandbox.
- [ ] Prove another ledger scope does not stale the permit and a same-scope
      append does.
- [ ] Prove `DATA_OPENED` precedes every plaintext byte and no post-open failure
      restores freshness.
- [ ] Prove the writer rejects raw rows and every undeclared output channel.
- [ ] Reproduce the bundle and rehearsal receipt from clean inputs.
- [ ] Record operator review, host/account/ACL topology, service identities,
      key custody, whether one human fills multiple roles, test outputs, and
      remaining administrator boundary.

Stage B is ready for permit request only after every check passes. Permit
issuance and actual holdout execution require separate operator approval.
