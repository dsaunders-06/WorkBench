"""Research-declaration authority boundary and immutable record types."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol

from qat.promotion.operator_signatures import (
    CustodianTrust,
    resolve_custodian_trust,
    verify_operator_signature,
)
from qat.promotion.rfc3161 import verify_timestamp_token


class SigningAuthorityError(PermissionError):
    """The caller lacks an operator-controlled declaration capability."""


class DeclarationLineageError(ValueError):
    """A signed declaration chain is incomplete, reordered, or invalid."""


_NAMES = (
    "EFFECT_DECLARED",
    "PROMOTION_PROTOCOL_DECLARED",
    "METHOD_AUDIT_DECLARED",
)


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate declaration JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


class _BinaryFloatPayloadError(ValueError):
    pass


def _reject_float(value: str) -> None:
    raise _BinaryFloatPayloadError(f"declaration numeric threshold needs decimal string: {value}")


@dataclass(frozen=True, slots=True)
class DeclarationRecord:
    name: str
    sequence: int
    previous_head: str
    operator_id: str
    strategy_spec_sha256: str
    catalog_id: str
    ledger_id: str
    nonce: str
    declared_at: datetime
    payload_json: bytes

    def __post_init__(self) -> None:
        if self.name not in _NAMES or self.sequence < 1:
            raise ValueError("unknown declaration name or sequence")
        if any(
            re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in (self.previous_head, self.strategy_spec_sha256)
        ):
            raise ValueError("declaration requires 64-character hexadecimal hash bindings")
        if not self.operator_id or not self.catalog_id or not self.ledger_id or not self.nonce:
            raise ValueError("declaration requires operator, catalog, ledger, and nonce")
        offset = self.declared_at.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("declaration time must be UTC")
        try:
            payload = json.loads(
                self.payload_json,
                object_pairs_hook=_unique_pairs,
                parse_constant=_reject_constant,
                parse_float=_reject_float,
            )
        except _BinaryFloatPayloadError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError("declaration payload must be canonical JSON") from exc
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
        if canonical != self.payload_json or not isinstance(payload, dict):
            raise ValueError("declaration payload must be canonical JSON object")
        if self.name == "EFFECT_DECLARED":
            if not isinstance(payload.get("delta_MME"), str):
                raise ValueError("effect declaration needs a decimal string")
            try:
                effect = Decimal(payload["delta_MME"])
            except (KeyError, InvalidOperation, TypeError) as exc:
                raise ValueError("effect declaration needs a positive decimal delta_MME") from exc
            if (
                not effect.is_finite()
                or effect <= 0
                or not isinstance(payload.get("rationale"), str)
                or not payload["rationale"].strip()
            ):
                raise ValueError("effect declaration needs a positive decimal and rationale")
        elif self.name == "PROMOTION_PROTOCOL_DECLARED":
            protocol_required = (
                "edge_rules",
                "tail_risk_rules",
                "data_rules",
                "portfolio_rules",
                "feasibility_rules",
                "promotion_thresholds",
                "statistical_rules",
            )
            if any(
                not isinstance(payload.get(key), dict) or not payload[key]
                for key in protocol_required
            ):
                raise ValueError("promotion protocol must bind every rule family")
        else:
            method_required = (
                "method_family",
                "scenario_matrix",
                "generators",
                "seeds",
                "acceptance_caps",
                "code_sha256",
                "pilot_report_sha256",
            )
            if any(not payload.get(key) for key in method_required):
                raise ValueError("method audit must bind method, matrix, seeds, caps and pilot")
            for key in ("code_sha256", "pilot_report_sha256"):
                if re.fullmatch(r"[0-9a-f]{64}", str(payload[key])) is None:
                    raise ValueError("method audit requires SHA-256 code and pilot hashes")

    def canonical_bytes(self) -> bytes:
        """The exact bytes signed by the operator Ed25519 key."""
        envelope = {
            "name": self.name,
            "sequence": self.sequence,
            "previous_head": self.previous_head,
            "operator_id": self.operator_id,
            "strategy_spec_sha256": self.strategy_spec_sha256,
            "catalog_id": self.catalog_id,
            "ledger_id": self.ledger_id,
            "nonce": self.nonce,
            "declared_at": self.declared_at.isoformat(),
            "payload_sha256": hashlib.sha256(self.payload_json).hexdigest(),
        }
        return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("ascii")


@dataclass(frozen=True, slots=True)
class DeclarationReceipt:
    record: DeclarationRecord
    signature: bytes
    rfc3161_token: bytes

    @property
    def head(self) -> str:
        digest = hashlib.sha256()
        for part in (
            self.record.canonical_bytes(),
            self.signature,
            self.rfc3161_token,
        ):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
        return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class VerifiedDeclarationChain:
    """Proof object that development gates may accept after fresh verification."""

    records: tuple[DeclarationReceipt, ...]
    names: tuple[str, ...]
    head: str
    ledger_id: str


def verify_declaration_chain(
    receipts: Sequence[DeclarationReceipt],
    *,
    now: datetime,
    test_mode: bool = False,
    test_trust: CustodianTrust | None = None,
) -> VerifiedDeclarationChain:
    """Verify all three declarations with pinned Ed25519 and offline TSA trust."""
    if now.tzinfo is None or len(receipts) != len(_NAMES):
        raise DeclarationLineageError("three declarations and aware verification time required")
    try:
        trust = resolve_custodian_trust(test_mode=test_mode, test_trust=test_trust)
    except Exception as exc:
        raise DeclarationLineageError("custodian trust is unavailable") from exc
    _verify_receipts(receipts, trust=trust, now=now)
    return VerifiedDeclarationChain(
        tuple(receipts), _NAMES, receipts[-1].head, receipts[0].record.ledger_id
    )


def _verify_receipts(
    receipts: Sequence[DeclarationReceipt], *, trust: CustodianTrust, now: datetime
) -> None:
    """Verify a complete chain or a prefix before append."""
    if not receipts or len(receipts) > len(_NAMES) or now.tzinfo is None:
        raise DeclarationLineageError("invalid declaration prefix")
    expected_head = "0" * 64
    seen_nonces: set[str] = set()
    first = receipts[0].record
    prior_time: datetime | None = None
    prior_stamp: datetime | None = None
    for sequence, receipt in enumerate(receipts, 1):
        record = receipt.record
        if (
            record.name != _NAMES[sequence - 1]
            or record.sequence != sequence
            or record.previous_head != expected_head
            or record.nonce in seen_nonces
            or (
                record.operator_id,
                record.strategy_spec_sha256,
                record.catalog_id,
                record.ledger_id,
            )
            != (first.operator_id, first.strategy_spec_sha256, first.catalog_id, first.ledger_id)
            or (prior_time is not None and record.declared_at <= prior_time)
            or (prior_stamp is not None and record.declared_at < prior_stamp)
            or record.declared_at > now
        ):
            raise DeclarationLineageError("declaration order, identity, nonce, or time invalid")
        if not receipt.signature or not receipt.rfc3161_token:
            raise DeclarationLineageError("declaration lacks signed timestamped receipt")
        try:
            verify_operator_signature(
                record.canonical_bytes(),
                receipt.signature,
                trust=trust,
            )
            stamp = verify_timestamp_token(
                receipt.rfc3161_token,
                hashlib.sha256(receipt.signature).digest(),
                trust=trust.tsa_trust,
                now=now,
                allowed_policies=trust.allowed_tsa_policies,
            )
        except Exception as exc:
            raise DeclarationLineageError(
                "signature, timestamp, or trust verification failed"
            ) from exc
        if stamp.generated_at < record.declared_at or (
            prior_stamp is not None and stamp.generated_at <= prior_stamp
        ):
            raise DeclarationLineageError("RFC 3161 time precedes declaration or prior receipt")
        expected_head = receipt.head
        seen_nonces.add(record.nonce)
        prior_time = record.declared_at
        prior_stamp = stamp.generated_at


class DeclarationAuthority(Protocol):
    """Append-only ledger port; it has no signing or timestamp capability."""

    def read_receipts(self) -> tuple[DeclarationReceipt, ...]: ...

    def append_if_head(self, expected_head: str, receipt: DeclarationReceipt) -> None: ...


def append_declaration(
    authority: DeclarationAuthority | None,
    receipt: DeclarationReceipt,
    *,
    now: datetime,
    test_mode: bool = False,
    test_trust: CustodianTrust | None = None,
) -> DeclarationReceipt:
    """Append a separately signed and timestamped receipt after verification."""
    if authority is None or not all(
        hasattr(authority, key) for key in ("read_receipts", "append_if_head")
    ):
        raise SigningAuthorityError("operator declaration authority is unavailable")
    existing = authority.read_receipts()
    expected_head = existing[-1].head if existing else "0" * 64
    record = receipt.record
    if record.sequence != len(existing) + 1 or record.previous_head != expected_head:
        raise DeclarationLineageError("append does not extend the current ledger head")
    if len(existing) == 3:
        raise DeclarationLineageError("declaration ledger is complete")
    try:
        trust = resolve_custodian_trust(test_mode=test_mode, test_trust=test_trust)
    except Exception as exc:
        raise DeclarationLineageError("custodian trust is unavailable") from exc
    _verify_receipts((*existing, receipt), trust=trust, now=now)
    authority.append_if_head(expected_head, receipt)
    return receipt
