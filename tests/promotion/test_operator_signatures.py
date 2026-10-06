"""Runtime throwaway Ed25519 keys only; no operator key or private fixture."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import qat.promotion.operator_signatures as signatures
from qat.promotion.operator_signatures import (
    CustodianTrust,
    OperatorApproval,
    OperatorSignatureError,
    TrustConfigurationError,
    operator_action_bytes,
    resolve_custodian_trust,
    verify_operator_approval,
    verify_operator_signature,
)
from qat.promotion.rfc3161 import TrustStore

FIXTURES = Path(__file__).parent / "fixtures" / "rfc3161-throwaway-test-only"


def _public_key(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _trust(key: Ed25519PrivateKey) -> CustodianTrust:
    root = (FIXTURES / "root.der").read_bytes()
    return CustodianTrust(
        operator_public_key_raw=_public_key(key),
        operator_public_key_sha256=hashlib.sha256(_public_key(key)).hexdigest(),
        tsa_root_sha256=(hashlib.sha256(root).hexdigest(),),
        tsa_trust=TrustStore((root,), ((FIXTURES / "root.crl.der").read_bytes(),)),
        allowed_tsa_policies=frozenset({"1.2.3.4.1"}),
    )


def test_throwaway_ed25519_signature_needs_pinned_operator_fingerprint() -> None:
    key = Ed25519PrivateKey.generate()
    content = b'{"name":"EFFECT_DECLARED","sequence":1}'
    verify_operator_signature(content, key.sign(content), trust=_trust(key))
    other = Ed25519PrivateKey.generate()
    with pytest.raises(OperatorSignatureError):
        verify_operator_signature(content, key.sign(content), trust=_trust(other))
    with pytest.raises(OperatorSignatureError):
        verify_operator_signature(content + b" ", key.sign(content), trust=_trust(key))


def test_throwaway_approval_cannot_authorize_another_action_or_payload() -> None:
    key = Ed25519PrivateKey.generate()
    payload = {"catalog_id": "public-test", "ledger_head": "a" * 64}
    signature = key.sign(operator_action_bytes("DEV_DATA_RELEASED", payload))
    approval = OperatorApproval(signature=signature)
    verify_operator_approval(approval, "DEV_DATA_RELEASED", payload, trust=_trust(key))
    with pytest.raises(OperatorSignatureError):
        verify_operator_approval(approval, "VALIDATION_DATA_RELEASED", payload, trust=_trust(key))
    with pytest.raises(OperatorSignatureError):
        verify_operator_approval(
            approval,
            "DEV_DATA_RELEASED",
            {**payload, "ledger_head": "b" * 64},
            trust=_trust(key),
        )


def test_production_mode_refuses_caller_supplied_trust_or_key() -> None:
    key = Ed25519PrivateKey.generate()
    trust = _trust(key)
    with pytest.raises(TrustConfigurationError):
        resolve_custodian_trust(test_mode=False, test_trust=trust)
    assert resolve_custodian_trust(test_mode=True, test_trust=trust) is trust
    with pytest.raises(TrustConfigurationError):
        resolve_custodian_trust(test_mode=True)


def _production_trust_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "QAT" / "Custodian" / "promotion-trust.json"
    path.parent.mkdir(parents=True)
    trust = _trust(Ed25519PrivateKey.generate())
    path.write_text(
        json.dumps(
            {
                "schema": "qat-promotion-trust-v1",
                "operator_ed25519_public_key_raw_base64": base64.b64encode(
                    trust.operator_public_key_raw
                ).decode("ascii"),
                "operator_ed25519_public_key_sha256": trust.operator_public_key_sha256,
                "tsa_roots": [
                    {
                        "der_base64": base64.b64encode(root).decode("ascii"),
                        "sha256": fingerprint,
                    }
                    for root, fingerprint in zip(
                        trust.tsa_trust.roots, trust.tsa_root_sha256, strict=True
                    )
                ],
                "tsa_crls_der_base64": [
                    base64.b64encode(crl).decode("ascii") for crl in trust.tsa_trust.crls
                ],
                "allowed_tsa_policies": sorted(trust.allowed_tsa_policies),
            }
        ),
        encoding="ascii",
    )
    monkeypatch.setattr(signatures, "PRODUCTION_TRUST_PATH", path)
    return path


@pytest.mark.parametrize(
    ("target", "owner", "principal", "mask", "reparse"),
    [
        ("file", "CUSTODIAN", "USERS", 0x00000002, False),
        ("custodian", "ADMIN", "AUTHENTICATED_USERS", 0x00000004, False),
        ("qat", "SYSTEM", "EVERYONE", 0x00010000, False),
        ("qat", "SYSTEM", "CREATOR_OWNER", 0x10000000, False),
        ("file", "CUSTODIAN", "USERS", 0x00040000, False),
        ("file", "CUSTODIAN", "USERS", 0x00080000, False),
        ("programdata", "SYSTEM", "INTERACTIVE", 0x00000040, False),
        ("programdata", "CUSTODIAN", None, 0, False),
        ("drive", "CURRENT_USER", None, 0, False),
        ("file", "CURRENT_USER", None, 0, False),
        ("custodian", "ADMIN", None, 0, True),
    ],
)
def test_production_trust_refuses_unsafe_path_acl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    owner: str,
    principal: str | None,
    mask: int,
    reparse: bool,
) -> None:
    path = _production_trust_file(tmp_path, monkeypatch)
    roles = {path: "file", path.parent: "custodian", path.parent.parent: "qat"}
    roles[path.parent.parent.parent] = "programdata"

    def snapshot(component: Path) -> SimpleNamespace:
        role = roles.get(component, "drive")
        base_owner = "ADMIN" if role in {"file", "custodian", "qat"} else "SYSTEM"
        grants = [("ADMIN", 0x001F01FF, False)]
        if role == target and principal:
            grants.append((principal, mask, role != "programdata"))
        return SimpleNamespace(owner=owner if role == target else base_owner, grants=grants)

    monkeypatch.setattr(signatures, "_windows_acl_snapshot", snapshot, raising=False)
    monkeypatch.setattr(
        signatures,
        "_trusted_windows_sids",
        lambda: {
            "custodian": "CUSTODIAN",
            "administrators": "ADMIN",
            "system": "SYSTEM",
            "trusted_installer": "TRUSTED_INSTALLER",
        },
        raising=False,
    )
    monkeypatch.setattr(
        signatures,
        "_is_reparse_point",
        lambda component: reparse and component == path.parent,
        raising=False,
    )
    with pytest.raises(TrustConfigurationError):
        resolve_custodian_trust()


def test_production_trust_loads_only_from_locked_custody_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _production_trust_file(tmp_path, monkeypatch)
    monkeypatch.setattr(
        signatures,
        "_windows_acl_snapshot",
        lambda component: SimpleNamespace(owner="ADMIN", grants=[("ADMIN", 0x001F01FF, False)]),
        raising=False,
    )
    monkeypatch.setattr(
        signatures,
        "_trusted_windows_sids",
        lambda: {
            "custodian": "CUSTODIAN",
            "administrators": "ADMIN",
            "system": "SYSTEM",
            "trusted_installer": "TRUSTED_INSTALLER",
        },
        raising=False,
    )
    monkeypatch.setattr(signatures, "_is_reparse_point", lambda _: False, raising=False)
    assert resolve_custodian_trust().operator_public_key_sha256
    assert path.exists()
