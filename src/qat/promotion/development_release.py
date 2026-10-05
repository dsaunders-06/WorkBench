"""Fail-closed Stage A development and validation release boundaries.

The shard opener and receipt authority are injected operator/custodian ports.
This module contains no key material or promotion-data path.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime

from qat.promotion.declarations import DeclarationReceipt, verify_declaration_chain
from qat.promotion.rfc3161 import TrustStore
from qat.promotion.structural_extract import ReceiptAuthority, _record


class DevelopmentLockedError(PermissionError):
    """The requested promotion-tier development/validation release is locked."""


class FreshHoldoutRequired(DevelopmentLockedError):
    """A consumed holdout cannot become fresh through a changed bundle."""


class NewDeclarationLineageRequired(DevelopmentLockedError):
    """A change cannot be proved to preserve the declared semantics."""


@dataclass(frozen=True, slots=True)
class ReleaseRequest:
    catalog_id: str
    shard_id: str
    bundle_hash: str
    strategy_spec_sha256: str
    ledger_id: str
    scope: str
    expected_ledger_head: str


@dataclass(frozen=True, slots=True)
class DevelopmentReleaseReceipt:
    state: str
    catalog_id: str
    shard_id: str
    bundle_hash: str
    scope: str
    declaration_head: str
    previous_head: str
    head: str


class DevelopmentAccess[HandleT]:
    """Scoped opener that commits a fresh receipt on every actual open."""

    def __init__(
        self,
        request: ReleaseRequest,
        receipt: DevelopmentReleaseReceipt,
        authority: ReceiptAuthority,
        shard_opener: Callable[[str], HandleT],
        opened_state: str,
    ) -> None:
        self._request = request
        self.latest_receipt = receipt
        self._authority = authority
        self._shard_opener = shard_opener
        self._opened_state = opened_state

    def open(self) -> HandleT:
        """Log access before the custodian yields a scoped data handle."""
        if self._authority.head != self.latest_receipt.head:
            raise DevelopmentLockedError("release head is stale; a new review is required")
        previous = self._authority.head
        payload: dict[str, object] = {
            "catalog_id": self._request.catalog_id,
            "shard_id": self._request.shard_id,
            "bundle_hash": self._request.bundle_hash,
            "scope": self._request.scope,
            "release_head": self.latest_receipt.head,
        }
        try:
            head = _record(self._authority, self._opened_state, payload)
        except Exception as exc:
            raise DevelopmentLockedError("cannot open shard without an appended receipt") from exc
        self.latest_receipt = DevelopmentReleaseReceipt(
            self._opened_state,
            self._request.catalog_id,
            self._request.shard_id,
            self._request.bundle_hash,
            self._request.scope,
            self.latest_receipt.declaration_head,
            previous,
            head,
        )
        handle = self._shard_opener(self._request.shard_id)
        if getattr(handle, "shard_id", None) != self._request.shard_id:
            raise DevelopmentLockedError("custodian returned a different shard")
        return handle


def _release[HandleT](
    *,
    receipts: Sequence[DeclarationReceipt],
    request: ReleaseRequest,
    declared_catalog_id: str,
    declared_shard_id: str,
    declared_bundle_hash: str,
    declared_scope: str,
    operator_trust: TrustStore,
    tsa_trust: TrustStore,
    allowed_tsa_policies: frozenset[str],
    now: datetime,
    authority: ReceiptAuthority,
    shard_opener: Callable[[str], HandleT],
    release_state: str,
    opened_state: str,
    development_fingerprint: str | None = None,
    frozen_artifacts_hash: str | None = None,
    rerun_authorization: RerunAuthorization | None = None,
) -> DevelopmentAccess[HandleT]:
    if (
        len(receipts) != 3
        or request.catalog_id != declared_catalog_id
        or request.shard_id != declared_shard_id
        or request.scope != declared_scope
        or not request.scope
        or not request.catalog_id
        or not request.shard_id
        or not request.ledger_id
        or re.fullmatch(r"[0-9a-f]{64}", request.expected_ledger_head) is None
        or re.fullmatch(r"[0-9a-f]{64}", request.bundle_hash) is None
        or re.fullmatch(r"[0-9a-f]{64}", request.strategy_spec_sha256) is None
        or authority is None
        or shard_opener is None
    ):
        raise DevelopmentLockedError("release request differs from declared identity or scope")
    if release_state == "VALIDATION_DATA_RELEASED" and (
        development_fingerprint is None
        or frozen_artifacts_hash is None
        or re.fullmatch(r"[0-9a-f]{64}", development_fingerprint) is None
        or re.fullmatch(r"[0-9a-f]{64}", frozen_artifacts_hash) is None
    ):
        raise DevelopmentLockedError("validation requires frozen development evidence")
    try:
        chain = verify_declaration_chain(
            receipts,
            operator_trust=operator_trust,
            tsa_trust=tsa_trust,
            allowed_tsa_policies=allowed_tsa_policies,
            now=now,
        )
    except Exception as exc:
        raise DevelopmentLockedError(
            "three independently timestamped declarations required"
        ) from exc
    if (
        chain.names != ("EFFECT_DECLARED", "PROMOTION_PROTOCOL_DECLARED", "METHOD_AUDIT_DECLARED")
        or chain.ledger_id != request.ledger_id
        or not re.fullmatch(r"[0-9a-f]{64}", chain.head)
        or len(chain.records) != 3
    ):
        raise DevelopmentLockedError("declaration lineage does not match requested release")
    for declaration_receipt in chain.records:
        if (
            declaration_receipt.record.catalog_id != request.catalog_id
            or declaration_receipt.record.strategy_spec_sha256 != request.strategy_spec_sha256
        ):
            raise DevelopmentLockedError("catalog or strategy hash differs from declaration")
    if authority.head != request.expected_ledger_head:
        raise DevelopmentLockedError("release authority head changed after review")
    if request.bundle_hash != declared_bundle_hash:
        if (
            rerun_authorization is None
            or rerun_authorization.prior_bundle_hash != declared_bundle_hash
            or rerun_authorization.replacement_bundle_hash != request.bundle_hash
            or rerun_authorization.head != authority.head
            or not authority.verify(
                rerun_authorization.receipt,
                state="DEV_RERUN_AUTHORIZED",
                payload=rerun_authorization.payload,
                expected_head=rerun_authorization.prior_head,
            )
        ):
            raise DevelopmentLockedError("replacement bundle lacks a verified rerun receipt")
    previous = authority.head
    payload: dict[str, object] = {
        "catalog_id": request.catalog_id,
        "shard_id": request.shard_id,
        "bundle_hash": request.bundle_hash,
        "strategy_spec_sha256": request.strategy_spec_sha256,
        "ledger_id": request.ledger_id,
        "scope": request.scope,
        "declaration_head": chain.head,
        "expected_ledger_head": request.expected_ledger_head,
    }
    if release_state == "VALIDATION_DATA_RELEASED":
        payload["development_fingerprint"] = development_fingerprint
        payload["frozen_artifacts_hash"] = frozen_artifacts_hash
    try:
        head = _record(authority, release_state, payload)
    except Exception as exc:
        raise DevelopmentLockedError("release receipt was not appended") from exc
    receipt = DevelopmentReleaseReceipt(
        release_state,
        request.catalog_id,
        request.shard_id,
        request.bundle_hash,
        request.scope,
        chain.head,
        previous,
        head,
    )
    return DevelopmentAccess(request, receipt, authority, shard_opener, opened_state)


def authorize_development[HandleT](
    *,
    receipts: Sequence[DeclarationReceipt],
    request: ReleaseRequest,
    declared_catalog_id: str,
    declared_shard_id: str,
    declared_bundle_hash: str,
    declared_scope: str,
    operator_trust: TrustStore,
    tsa_trust: TrustStore,
    allowed_tsa_policies: frozenset[str],
    now: datetime,
    authority: ReceiptAuthority,
    shard_opener: Callable[[str], HandleT],
    rerun_authorization: RerunAuthorization | None = None,
) -> DevelopmentAccess[HandleT]:
    """Verify declarations and commit DEV_DATA_RELEASED before returning access."""
    return _release(
        receipts=receipts,
        request=request,
        declared_catalog_id=declared_catalog_id,
        declared_shard_id=declared_shard_id,
        declared_bundle_hash=declared_bundle_hash,
        declared_scope=declared_scope,
        operator_trust=operator_trust,
        tsa_trust=tsa_trust,
        allowed_tsa_policies=allowed_tsa_policies,
        now=now,
        authority=authority,
        shard_opener=shard_opener,
        release_state="DEV_DATA_RELEASED",
        opened_state="DEV_DATA_OPENED",
        rerun_authorization=rerun_authorization,
    )


def authorize_validation[HandleT](
    *,
    receipts: Sequence[DeclarationReceipt],
    request: ReleaseRequest,
    declared_catalog_id: str,
    declared_shard_id: str,
    declared_bundle_hash: str,
    declared_scope: str,
    operator_trust: TrustStore,
    tsa_trust: TrustStore,
    allowed_tsa_policies: frozenset[str],
    now: datetime,
    authority: ReceiptAuthority,
    shard_opener: Callable[[str], HandleT],
    development_fingerprint: str | None,
    frozen_artifacts_hash: str | None,
    rerun_authorization: RerunAuthorization | None = None,
) -> DevelopmentAccess[HandleT]:
    """Release validation only with frozen development artifacts/fingerprint."""
    return _release(
        receipts=receipts,
        request=request,
        declared_catalog_id=declared_catalog_id,
        declared_shard_id=declared_shard_id,
        declared_bundle_hash=declared_bundle_hash,
        declared_scope=declared_scope,
        operator_trust=operator_trust,
        tsa_trust=tsa_trust,
        allowed_tsa_policies=allowed_tsa_policies,
        now=now,
        authority=authority,
        shard_opener=shard_opener,
        release_state="VALIDATION_DATA_RELEASED",
        opened_state="VALIDATION_DATA_OPENED",
        development_fingerprint=development_fingerprint,
        frozen_artifacts_hash=frozen_artifacts_hash,
        rerun_authorization=rerun_authorization,
    )


def check_holdout_freshness(
    *, prior_states: Sequence[str], prior_bundle_hash: str, requested_bundle_hash: str
) -> None:
    """A post-DATA_OPENED bundle change cannot restore promotion eligibility."""
    if "DATA_OPENED" in prior_states:
        raise FreshHoldoutRequired("holdout was already opened; exact replay is reproduction only")
    if prior_bundle_hash != requested_bundle_hash:
        raise DevelopmentLockedError("changed bundle requires a new reviewed lineage")


@dataclass(frozen=True, slots=True)
class DefectDossier:
    """Operator-reviewed proof for the narrow semantics-preserving repair path."""

    discovery_channel: str
    discovery_actor: str
    data_tier: str
    first_observed_at: datetime
    patch_authored_at: datetime
    visible_outcome_artifacts: tuple[str, ...]
    symptom: str
    hypothesis: str
    pre_patch_failure_hash: str
    independent_oracle_hash: str
    failed_run_hash: str
    exact_diff_hash: str
    prior_bundle_hash: str
    replacement_bundle_hash: str
    unchanged_spec_hash: str
    permitted_changed_artifacts: tuple[str, ...]
    unchanged_artifact_digest: str
    changed_artifact_digest: str
    oracle_artifact_digest: str
    regression_gate_hashes: tuple[str, ...]
    changed_surfaces: tuple[str, ...]
    outcome_triggered: bool

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":"), default=lambda x: x.isoformat()
        ).encode("ascii")


@dataclass(frozen=True, slots=True)
class RerunAuthorization:
    state: str
    prior_head: str
    head: str
    dossier_sha256: str
    prior_bundle_hash: str
    replacement_bundle_hash: str
    payload: dict[str, object]
    receipt: object


def authorize_development_rerun(
    *,
    dossier: DefectDossier,
    prior_release: DevelopmentReleaseReceipt,
    frozen_spec_sha256: str,
    authority: ReceiptAuthority,
    review_signature: bytes,
    review_verifier: Callable[[bytes, bytes], bool],
) -> RerunAuthorization:
    """Log a reviewed repair only when independent evidence proves contract parity."""
    hashes = (
        dossier.pre_patch_failure_hash,
        dossier.independent_oracle_hash,
        dossier.failed_run_hash,
        dossier.exact_diff_hash,
        dossier.prior_bundle_hash,
        dossier.replacement_bundle_hash,
        dossier.unchanged_spec_hash,
        dossier.unchanged_artifact_digest,
        dossier.changed_artifact_digest,
        dossier.oracle_artifact_digest,
        *dossier.regression_gate_hashes,
    )
    if (
        dossier.discovery_channel not in {"failing_test", "reference_oracle", "outcome_anomaly"}
        or dossier.data_tier not in {"development", "validation"}
        or not dossier.discovery_actor
        or not dossier.symptom
        or not dossier.hypothesis
        or dossier.first_observed_at.tzinfo is None
        or dossier.patch_authored_at.tzinfo is None
        or dossier.first_observed_at >= dossier.patch_authored_at
        or not dossier.visible_outcome_artifacts
        or not dossier.permitted_changed_artifacts
        or dossier.changed_surfaces != ("implementation_defect",)
        or len(dossier.regression_gate_hashes) != 5
        or any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in hashes)
        or dossier.changed_artifact_digest != dossier.oracle_artifact_digest
        or dossier.prior_bundle_hash != prior_release.bundle_hash
        or dossier.replacement_bundle_hash == dossier.prior_bundle_hash
        or dossier.unchanged_spec_hash != frozen_spec_sha256
        or (dossier.outcome_triggered and not dossier.independent_oracle_hash)
    ):
        raise NewDeclarationLineageRequired("defect proof is incomplete or semantics changed")
    if authority.head != prior_release.head or not review_signature:
        raise DevelopmentLockedError("reviewed prior release head or signature is absent")
    dossier_bytes = dossier.canonical_bytes()
    try:
        reviewed = review_verifier(dossier_bytes, review_signature)
    except Exception as exc:
        raise DevelopmentLockedError("operator defect review could not be verified") from exc
    if not reviewed:
        raise DevelopmentLockedError("operator defect review signature is invalid")
    dossier_hash = hashlib.sha256(dossier_bytes).hexdigest()
    payload: dict[str, object] = {
        "dossier_sha256": dossier_hash,
        "failed_run_hash": dossier.failed_run_hash,
        "exact_diff_hash": dossier.exact_diff_hash,
        "prior_bundle_hash": dossier.prior_bundle_hash,
        "replacement_bundle_hash": dossier.replacement_bundle_hash,
        "unchanged_spec_hash": dossier.unchanged_spec_hash,
        "permitted_changed_artifacts": list(dossier.permitted_changed_artifacts),
        "unchanged_artifact_digest": dossier.unchanged_artifact_digest,
        "changed_artifact_digest": dossier.changed_artifact_digest,
        "oracle_artifact_digest": dossier.oracle_artifact_digest,
        "review_signature_sha256": hashlib.sha256(review_signature).hexdigest(),
        "outcome_triggered": dossier.outcome_triggered,
        "visible_outcome_artifacts": list(dossier.visible_outcome_artifacts),
        "prior_head": prior_release.head,
    }
    try:
        receipt = authority.append(
            "DEV_RERUN_AUTHORIZED", payload, expected_head=prior_release.head
        )
        if not authority.verify(
            receipt,
            state="DEV_RERUN_AUTHORIZED",
            payload=payload,
            expected_head=prior_release.head,
        ):
            raise DevelopmentLockedError("rerun receipt signature failed verification")
        head = authority.head
        if head == prior_release.head or re.fullmatch(r"[0-9a-f]{64}", head) is None:
            raise DevelopmentLockedError("rerun receipt did not advance ledger")
    except Exception as exc:
        raise DevelopmentLockedError("rerun authorization receipt was not committed") from exc
    return RerunAuthorization(
        "DEV_RERUN_AUTHORIZED",
        prior_release.head,
        head,
        dossier_hash,
        dossier.prior_bundle_hash,
        dossier.replacement_bundle_hash,
        payload,
        receipt,
    )
