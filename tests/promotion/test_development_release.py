"""Synthetic Stage A release-gate tests; no promotion shard is opened."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import qat.promotion.development_release as release
from qat.promotion.declarations import VerifiedDeclarationChain
from qat.promotion.operator_signatures import (
    CustodianTrust,
    OperatorApproval,
    operator_action_bytes,
)
from qat.promotion.rfc3161 import TrustStore

H = "a" * 64
NOW = datetime(2026, 10, 6, tzinfo=UTC)


def _throwaway_approval(
    action: str, payload: dict[str, object], *, key: Ed25519PrivateKey | None = None
) -> tuple[OperatorApproval, CustodianTrust]:
    key = key or Ed25519PrivateKey.generate()  # throwaway test key only
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    root = b"THROWAWAY TEST TSA ROOT"
    trust = CustodianTrust(
        public,
        sha256(public).hexdigest(),
        (sha256(root).hexdigest(),),
        TrustStore((root,), (b"THROWAWAY TEST TSA CRL",)),
        frozenset({"1.2.3.4.1"}),
    )
    return OperatorApproval(key.sign(operator_action_bytes(action, payload))), trust


def _release_payload(
    request: release.ReleaseRequest, *, validation: bool = False
) -> dict[str, object]:
    payload: dict[str, object] = {
        "catalog_id": request.catalog_id,
        "shard_id": request.shard_id,
        "bundle_hash": request.bundle_hash,
        "strategy_spec_sha256": request.strategy_spec_sha256,
        "ledger_id": request.ledger_id,
        "scope": request.scope,
        "declaration_head": "c" * 64,
        "expected_ledger_head": request.expected_ledger_head,
    }
    if validation:
        payload["development_fingerprint"] = "d" * 64
        payload["frozen_artifacts_hash"] = "e" * 64
    return payload


class RecordingAuthority:
    def __init__(self) -> None:
        self.head = H
        self.states: list[str] = []

    def append(self, state: str, payload: dict[str, object], *, expected_head: str) -> object:
        if expected_head != self.head:
            raise ValueError("stale head")
        self.states.append(state)
        self.head = sha256(
            (self.head + state + json.dumps(payload, sort_keys=True)).encode()
        ).hexdigest()
        return {"state": state, "payload": payload, "head": self.head}

    def verify(
        self, receipt: object, *, state: str, payload: dict[str, object], expected_head: str
    ) -> bool:
        return receipt == {"state": state, "payload": payload, "head": self.head}


def _request(shard: str = "synthetic-development") -> release.ReleaseRequest:
    return release.ReleaseRequest(
        catalog_id="synthetic-catalog",
        shard_id=shard,
        bundle_hash="b" * 64,
        strategy_spec_sha256=H,
        ledger_id="synthetic-ledger",
        scope="synthetic-development-only",
        expected_ledger_head=H,
    )


def _verified_chain() -> VerifiedDeclarationChain:
    return VerifiedDeclarationChain(
        records=tuple(
            SimpleNamespace(
                record=SimpleNamespace(catalog_id="synthetic-catalog", strategy_spec_sha256=H)
            )
            for _ in range(3)
        ),
        names=("EFFECT_DECLARED", "PROMOTION_PROTOCOL_DECLARED", "METHOD_AUDIT_DECLARED"),
        head="c" * 64,
        ledger_id="synthetic-ledger",
    )


def _authorize(
    monkeypatch: pytest.MonkeyPatch,
    authority: RecordingAuthority,
    *,
    receipts: tuple[object, ...] = (object(), object(), object()),
    request: release.ReleaseRequest | None = None,
    opener=None,
    install_verifier: bool = True,
):
    if install_verifier:
        monkeypatch.setattr(
            release, "verify_declaration_chain", lambda *args, **kwargs: _verified_chain()
        )
    request = request or _request()
    approval, trust = _throwaway_approval("DEV_DATA_RELEASED", _release_payload(request))
    return release.authorize_development(
        receipts=receipts,
        request=request,
        declared_catalog_id="synthetic-catalog",
        declared_shard_id="synthetic-development",
        declared_bundle_hash="b" * 64,
        declared_scope="synthetic-development-only",
        operator_approval=approval,
        test_mode=True,
        test_trust=trust,
        now=NOW,
        authority=authority,
        shard_opener=opener or (lambda shard: type("TestHandle", (), {"shard_id": shard})()),
    )


def test_development_release_precedes_every_scoped_open(monkeypatch: pytest.MonkeyPatch) -> None:
    authority = RecordingAuthority()
    seen: list[tuple[str, ...]] = []

    def opener(shard: str):
        seen.append(tuple(authority.states))
        return type("TestHandle", (), {"shard_id": shard})()

    access = _authorize(monkeypatch, authority, opener=opener)
    assert authority.states == ["DEV_DATA_RELEASED"]
    assert access.latest_receipt.state == "DEV_DATA_RELEASED"
    assert access.open().shard_id == "synthetic-development"
    assert access.open().shard_id == "synthetic-development"
    assert seen == [
        ("DEV_DATA_RELEASED", "DEV_DATA_OPENED"),
        ("DEV_DATA_RELEASED", "DEV_DATA_OPENED", "DEV_DATA_OPENED"),
    ]


def test_stale_release_head_cannot_open_synthetic_shard(monkeypatch: pytest.MonkeyPatch) -> None:
    authority = RecordingAuthority()
    opened: list[str] = []
    access = _authorize(
        monkeypatch,
        authority,
        opener=lambda shard: opened.append(shard),
    )
    authority.head = "0" * 64
    with pytest.raises(release.DevelopmentLockedError):
        access.open()
    assert opened == []


def test_unsigned_release_approval_never_appends(monkeypatch: pytest.MonkeyPatch) -> None:
    authority = RecordingAuthority()
    approval, trust = _throwaway_approval("DEV_DATA_RELEASED", _release_payload(_request()))
    wrong = replace(approval, signature=b"0" * 64)
    monkeypatch.setattr(
        release, "verify_declaration_chain", lambda *args, **kwargs: _verified_chain()
    )
    with pytest.raises(release.DevelopmentLockedError):
        release.authorize_development(
            receipts=(object(), object(), object()),
            request=_request(),
            declared_catalog_id="synthetic-catalog",
            declared_shard_id="synthetic-development",
            declared_bundle_hash="b" * 64,
            declared_scope="synthetic-development-only",
            operator_approval=wrong,
            now=NOW,
            authority=authority,
            shard_opener=lambda shard: type("TestHandle", (), {"shard_id": shard})(),
            test_mode=True,
            test_trust=trust,
        )
    assert authority.states == []


def test_production_release_rejects_caller_trust(monkeypatch: pytest.MonkeyPatch) -> None:
    authority = RecordingAuthority()
    approval, trust = _throwaway_approval("DEV_DATA_RELEASED", _release_payload(_request()))
    monkeypatch.setattr(
        release, "verify_declaration_chain", lambda *args, **kwargs: _verified_chain()
    )
    with pytest.raises(release.DevelopmentLockedError):
        release.authorize_development(
            receipts=(object(), object(), object()),
            request=_request(),
            declared_catalog_id="synthetic-catalog",
            declared_shard_id="synthetic-development",
            declared_bundle_hash="b" * 64,
            declared_scope="synthetic-development-only",
            operator_approval=approval,
            now=NOW,
            authority=authority,
            shard_opener=lambda shard: type("TestHandle", (), {"shard_id": shard})(),
            test_trust=trust,
        )
    assert authority.states == []


def test_raw_development_requires_three_timestamped_declarations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = RecordingAuthority()
    monkeypatch.setattr(
        release,
        "verify_declaration_chain",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("unverified token")),
    )
    with pytest.raises(release.DevelopmentLockedError):
        _authorize(monkeypatch, authority, receipts=(object(), object()), install_verifier=False)
    assert authority.states == []


def test_catalog_shard_bundle_and_scope_are_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    for change in (
        {"catalog_id": "other"},
        {"shard_id": "other"},
        {"bundle_hash": "0" * 64},
        {"scope": ""},
        {"expected_ledger_head": "0" * 64},
    ):
        authority = RecordingAuthority()
        with pytest.raises(release.DevelopmentLockedError):
            _authorize(monkeypatch, authority, request=replace(_request(), **change))
        assert authority.states == []


def test_validation_requires_frozen_development_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = RecordingAuthority()
    approval, trust = _throwaway_approval(
        "VALIDATION_DATA_RELEASED",
        _release_payload(_request("synthetic-validation"), validation=True),
    )
    monkeypatch.setattr(
        release, "verify_declaration_chain", lambda *args, **kwargs: _verified_chain()
    )
    kwargs = dict(
        receipts=(object(), object(), object()),
        request=_request("synthetic-validation"),
        declared_catalog_id="synthetic-catalog",
        declared_shard_id="synthetic-validation",
        declared_bundle_hash="b" * 64,
        declared_scope="synthetic-development-only",
        operator_approval=approval,
        test_mode=True,
        test_trust=trust,
        now=NOW,
        authority=authority,
        shard_opener=lambda shard: type("TestHandle", (), {"shard_id": shard})(),
    )
    with pytest.raises(release.DevelopmentLockedError):
        release.authorize_validation(
            **kwargs, development_fingerprint=None, frozen_artifacts_hash=None
        )
    assert authority.states == []
    access = release.authorize_validation(
        **kwargs, development_fingerprint="d" * 64, frozen_artifacts_hash="e" * 64
    )
    assert access.latest_receipt.state == "VALIDATION_DATA_RELEASED"


def test_changed_bundle_after_holdout_data_opened_never_regains_freshness() -> None:
    with pytest.raises(release.FreshHoldoutRequired):
        release.check_holdout_freshness(
            prior_states=("EXPOSURE_RESERVED", "DATA_OPENED"),
            prior_bundle_hash="b" * 64,
            requested_bundle_hash="c" * 64,
        )


def _dossier(**changes: object) -> release.DefectDossier:
    initial = release.DefectDossier(
        discovery_channel="failing_test",
        discovery_actor="test-reviewer",
        data_tier="development",
        first_observed_at=datetime(2026, 10, 5, 1, tzinfo=UTC),
        patch_authored_at=datetime(2026, 10, 5, 2, tzinfo=UTC),
        visible_outcome_artifacts=("test-visible-artifact-sha256",),
        symptom="rounding violates frozen arithmetic contract",
        hypothesis="cast occurred before Decimal conversion",
        pre_patch_failure_hash="1" * 64,
        independent_oracle_hash="2" * 64,
        failed_run_hash="3" * 64,
        exact_diff_hash="4" * 64,
        prior_bundle_hash="b" * 64,
        replacement_bundle_hash="c" * 64,
        unchanged_spec_hash=H,
        permitted_changed_artifacts=("numeric-conformance",),
        unchanged_artifact_digest="5" * 64,
        changed_artifact_digest="6" * 64,
        oracle_artifact_digest="6" * 64,
        regression_gate_hashes=("7" * 64,) * 5,
        changed_surfaces=("implementation_defect",),
        outcome_triggered=False,
    )
    return replace(initial, **changes)


def test_reviewed_semantics_preserving_rerun_binds_dossier_and_head() -> None:
    authority = RecordingAuthority()
    prior = release.DevelopmentReleaseReceipt(
        "DEV_DATA_OPENED",
        "synthetic-catalog",
        "synthetic-development",
        "b" * 64,
        "synthetic-development-only",
        "d" * 64,
        "0" * 64,
        H,
    )
    dossier = _dossier()
    payload = release.rerun_approval_payload(dossier, prior)
    approval, trust = _throwaway_approval("DEV_RERUN_AUTHORIZED", payload)
    accepted = release.authorize_development_rerun(
        dossier=dossier,
        prior_release=prior,
        authority=authority,
        frozen_spec_sha256=H,
        operator_approval=approval,
        test_mode=True,
        test_trust=trust,
    )
    assert authority.states == ["DEV_RERUN_AUTHORIZED"]
    assert accepted.state == "DEV_RERUN_AUTHORIZED"
    assert accepted.prior_head == prior.head
    assert accepted.replacement_bundle_hash == "c" * 64


def test_replacement_bundle_requires_verified_rerun_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = RecordingAuthority()
    prior = release.DevelopmentReleaseReceipt(
        "DEV_DATA_OPENED",
        "synthetic-catalog",
        "synthetic-development",
        "b" * 64,
        "synthetic-development-only",
        "d" * 64,
        "0" * 64,
        H,
    )
    dossier = _dossier()
    key = Ed25519PrivateKey.generate()  # throwaway test key only
    approval, trust = _throwaway_approval(
        "DEV_RERUN_AUTHORIZED", release.rerun_approval_payload(dossier, prior), key=key
    )
    approved = release.authorize_development_rerun(
        dossier=dossier,
        prior_release=prior,
        frozen_spec_sha256=H,
        authority=authority,
        operator_approval=approval,
        test_mode=True,
        test_trust=trust,
    )
    replacement = replace(_request(), bundle_hash="c" * 64, expected_ledger_head=approved.head)
    with pytest.raises(release.DevelopmentLockedError):
        _authorize(monkeypatch, authority, request=replacement)
    assert authority.states == ["DEV_RERUN_AUTHORIZED"]
    chain = _verified_chain()
    monkeypatch.setattr(release, "verify_declaration_chain", lambda *args, **kwargs: chain)
    release_approval, release_trust = _throwaway_approval(
        "DEV_DATA_RELEASED", _release_payload(replacement), key=key
    )
    with pytest.raises(release.DevelopmentLockedError):
        release.authorize_development(
            receipts=(object(), object(), object()),
            request=replacement,
            declared_catalog_id="synthetic-catalog",
            declared_shard_id="synthetic-development",
            declared_bundle_hash="b" * 64,
            declared_scope="synthetic-development-only",
            operator_approval=release_approval,
            test_mode=True,
            test_trust=release_trust,
            now=NOW,
            authority=authority,
            shard_opener=lambda shard: type("TestHandle", (), {"shard_id": shard})(),
            rerun_authorization=replace(
                approved,
                operator_approval=replace(approval, signature=b"0" * 64),
            ),
        )
    assert authority.states == ["DEV_RERUN_AUTHORIZED"]
    access = release.authorize_development(
        receipts=(object(), object(), object()),
        request=replacement,
        declared_catalog_id="synthetic-catalog",
        declared_shard_id="synthetic-development",
        declared_bundle_hash="b" * 64,
        declared_scope="synthetic-development-only",
        operator_approval=release_approval,
        test_mode=True,
        test_trust=release_trust,
        now=NOW,
        authority=authority,
        shard_opener=lambda shard: type("TestHandle", (), {"shard_id": shard})(),
        rerun_authorization=approved,
    )
    assert access.latest_receipt.state == "DEV_DATA_RELEASED"
    assert access.latest_receipt.bundle_hash == "c" * 64


@pytest.mark.parametrize(
    "change",
    [
        {"changed_surfaces": ("threshold",)},
        {"changed_surfaces": ("calendar",)},
        {"changed_surfaces": ("numeric_policy",)},
        {"outcome_triggered": True, "independent_oracle_hash": ""},
        {"changed_artifact_digest": "8" * 64},
        {"pre_patch_failure_hash": ""},
    ],
)
def test_unproven_or_semantics_changing_rerun_requires_new_lineage(
    change: dict[str, object],
) -> None:
    authority = RecordingAuthority()
    prior = release.DevelopmentReleaseReceipt(
        "DEV_DATA_OPENED",
        "synthetic-catalog",
        "synthetic-development",
        "b" * 64,
        "synthetic-development-only",
        "d" * 64,
        "0" * 64,
        H,
    )
    with pytest.raises(release.NewDeclarationLineageRequired):
        release.authorize_development_rerun(
            dossier=_dossier(**change),
            prior_release=prior,
            authority=authority,
            frozen_spec_sha256=H,
            operator_approval=OperatorApproval(b"0" * 64),
        )
    assert authority.states == []
