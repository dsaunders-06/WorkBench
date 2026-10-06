"""Pinned public-key verification for operator-authorised promotion actions.

The private key is never loaded here. Production trust comes from a fixed
custodian-owned configuration path; test injection is explicit and separate.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from qat.promotion.rfc3161 import TrustStore


class OperatorSignatureError(ValueError):
    """An action lacks a signature by the pinned operator public key."""


class TrustConfigurationError(ValueError):
    """Custodian-controlled promotion trust configuration is unavailable."""


PRODUCTION_TRUST_PATH = (
    Path("C:/ProgramData/QAT/Custodian/promotion-trust.json")
    if os.name == "nt"
    else Path("/etc/qat/promotion-trust.json")
)

_ACTIONS = frozenset(
    {
        "REFERENCE_VIEW_RELEASED",
        "DEV_DATA_RELEASED",
        "VALIDATION_DATA_RELEASED",
        "DEV_RERUN_AUTHORIZED",
        "HOLDOUT_PERMIT",
        "HOLDOUT_RERUN_AUTHORIZED",
    }
)


@dataclass(frozen=True, slots=True)
class CustodianTrust:
    operator_public_key_raw: bytes
    operator_public_key_sha256: str
    tsa_root_sha256: tuple[str, ...]
    tsa_trust: TrustStore
    allowed_tsa_policies: frozenset[str]

    def __post_init__(self) -> None:
        fingerprints = self.tsa_root_sha256
        if (
            len(self.operator_public_key_raw) != 32
            or hashlib.sha256(self.operator_public_key_raw).hexdigest()
            != self.operator_public_key_sha256
            or re.fullmatch(r"[0-9a-f]{64}", self.operator_public_key_sha256) is None
            or not fingerprints
            or len(set(fingerprints)) != len(fingerprints)
            or len(fingerprints) != len(self.tsa_trust.roots)
            or any(re.fullmatch(r"[0-9a-f]{64}", x) is None for x in fingerprints)
            or tuple(hashlib.sha256(root).hexdigest() for root in self.tsa_trust.roots)
            != fingerprints
            or not self.tsa_trust.crls
            or not self.allowed_tsa_policies
        ):
            raise TrustConfigurationError("invalid pinned operator or TSA trust")


@dataclass(frozen=True, slots=True)
class OperatorApproval:
    signature: bytes


def _decode_base64(value: object) -> bytes:
    if not isinstance(value, str):
        raise TrustConfigurationError("trust entry must be base64 text")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise TrustConfigurationError("invalid trust base64") from exc


def resolve_custodian_trust(
    *, test_mode: bool = False, test_trust: CustodianTrust | None = None
) -> CustodianTrust:
    """Load fixed production pins, or explicit throwaway pins in test mode."""
    if test_mode:
        if test_trust is None:
            raise TrustConfigurationError("test mode needs explicit throwaway trust")
        return test_trust
    if test_trust is not None:
        raise TrustConfigurationError("production mode refuses caller-supplied trust")
    try:
        if PRODUCTION_TRUST_PATH.is_symlink():
            raise TrustConfigurationError("production trust path cannot be a symlink")
        raw = json.loads(PRODUCTION_TRUST_PATH.read_bytes())
        if raw["schema"] != "qat-promotion-trust-v1":
            raise TrustConfigurationError("unsupported custodian trust schema")
        roots = tuple(_decode_base64(item["der_base64"]) for item in raw["tsa_roots"])
        fingerprints = tuple(item["sha256"] for item in raw["tsa_roots"])
        crls = tuple(_decode_base64(value) for value in raw["tsa_crls_der_base64"])
        return CustodianTrust(
            operator_public_key_raw=_decode_base64(raw["operator_ed25519_public_key_raw_base64"]),
            operator_public_key_sha256=raw["operator_ed25519_public_key_sha256"],
            tsa_root_sha256=fingerprints,
            tsa_trust=TrustStore(roots, crls),
            allowed_tsa_policies=frozenset(raw["allowed_tsa_policies"]),
        )
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise TrustConfigurationError("custodian trust could not be loaded") from exc


def verify_operator_signature(content: bytes, signature: bytes, *, trust: CustodianTrust) -> None:
    """Require Ed25519 over exact bytes by the externally pinned key."""
    if len(signature) != 64:
        raise OperatorSignatureError("invalid Ed25519 signature length")
    fingerprint = hashlib.sha256(trust.operator_public_key_raw).hexdigest()
    if not hmac.compare_digest(fingerprint, trust.operator_public_key_sha256):
        raise OperatorSignatureError("operator public key differs from custodian pin")
    try:
        Ed25519PublicKey.from_public_bytes(trust.operator_public_key_raw).verify(signature, content)
    except (InvalidSignature, ValueError) as exc:
        raise OperatorSignatureError("operator signature is invalid") from exc


def operator_action_bytes(action: str, payload: dict[str, object]) -> bytes:
    """Domain-separated canonical bytes for releases, permits and reruns."""
    if action not in _ACTIONS:
        raise OperatorSignatureError("unknown operator action")
    try:
        canonical = json.dumps(
            {"action": action, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise OperatorSignatureError("operator action payload is not canonical JSON") from exc
    return b"QAT-OPERATOR-ACTION-v1\n" + canonical


def verify_operator_approval(
    approval: OperatorApproval, action: str, payload: dict[str, object], *, trust: CustodianTrust
) -> None:
    verify_operator_signature(
        operator_action_bytes(action, payload),
        approval.signature,
        trust=trust,
    )
