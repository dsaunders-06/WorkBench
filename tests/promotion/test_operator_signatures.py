"""Runtime throwaway Ed25519 keys only; no operator key or private fixture."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

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
