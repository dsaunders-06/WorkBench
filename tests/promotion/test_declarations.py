"""Stage A declarations refuse authority that the research agent does not own."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import qat.promotion.declarations as declarations
from qat.promotion.declarations import (
    DeclarationLineageError,
    DeclarationReceipt,
    DeclarationRecord,
    SigningAuthorityError,
    append_declaration,
    verify_declaration_chain,
)
from qat.promotion.operator_signatures import CustodianTrust
from qat.promotion.rfc3161 import TrustStore, VerifiedTimestamp


def test_agent_cannot_append_a_research_declaration() -> None:
    record = DeclarationRecord(
        name="EFFECT_DECLARED",
        sequence=1,
        previous_head="0" * 64,
        operator_id="operator-1",
        strategy_spec_sha256="a" * 64,
        catalog_id="catalog-1",
        ledger_id="ledger-1",
        nonce="unique-1",
        declared_at=datetime(2026, 10, 5, tzinfo=UTC),
        payload_json=b'{"delta_MME":"0.2","rationale":"economic hurdle"}',
    )

    with pytest.raises(SigningAuthorityError):
        append_declaration(None, record, now=datetime(2026, 10, 6, tzinfo=UTC))


def test_effect_declaration_requires_positive_decimal_hurdle_and_canonical_payload() -> None:
    record = DeclarationRecord(
        name="EFFECT_DECLARED",
        sequence=1,
        previous_head="0" * 64,
        operator_id="operator-1",
        strategy_spec_sha256="a" * 64,
        catalog_id="catalog-1",
        ledger_id="ledger-1",
        nonce="unique-1",
        declared_at=datetime(2026, 10, 5, tzinfo=UTC),
        payload_json=b'{"delta_MME":"0.2","rationale":"economic hurdle"}',
    )

    with pytest.raises(ValueError, match="positive"):
        replace(record, payload_json=b'{"delta_MME":"-0.2","rationale":"economic hurdle"}')
    with pytest.raises(ValueError, match="canonical"):
        replace(record, payload_json=b'{ "delta_MME": "0.2", "rationale": "economic hurdle" }')
    with pytest.raises(ValueError, match="decimal string"):
        replace(record, payload_json=b'{"delta_MME":0.2,"rationale":"economic hurdle"}')
    with pytest.raises(ValueError, match="rationale"):
        replace(record, payload_json=b'{"delta_MME":"0.2","rationale":{"not":"text"}}')


def test_protocol_declaration_requires_statistical_rule_binding() -> None:
    payload = {
        key: {"test": "bound"}
        for key in (
            "edge_rules",
            "tail_risk_rules",
            "data_rules",
            "portfolio_rules",
            "feasibility_rules",
            "promotion_thresholds",
        )
    }
    with pytest.raises(ValueError, match="rule family"):
        DeclarationRecord(
            "PROMOTION_PROTOCOL_DECLARED",
            2,
            "a" * 64,
            "test-operator",
            "b" * 64,
            "test-catalog",
            "test-ledger",
            "test-nonce",
            datetime(2026, 10, 5, tzinfo=UTC),
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii"),
        )


def test_declaration_payload_rejects_binary_float_thresholds() -> None:
    payload = {
        key: {"threshold": "0.1"}
        for key in (
            "edge_rules",
            "tail_risk_rules",
            "data_rules",
            "portfolio_rules",
            "feasibility_rules",
            "promotion_thresholds",
            "statistical_rules",
        )
    }
    payload["edge_rules"] = {"threshold": 0.1}
    with pytest.raises(ValueError, match="decimal string"):
        DeclarationRecord(
            "PROMOTION_PROTOCOL_DECLARED",
            2,
            "a" * 64,
            "test-operator",
            "b" * 64,
            "test-catalog",
            "test-ledger",
            "test-nonce",
            datetime(2026, 10, 5, tzinfo=UTC),
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii"),
        )


def test_record_rejects_unbound_identity_hash_or_naive_time() -> None:
    record = DeclarationRecord(
        name="EFFECT_DECLARED",
        sequence=1,
        previous_head="0" * 64,
        operator_id="operator-1",
        strategy_spec_sha256="a" * 64,
        catalog_id="catalog-1",
        ledger_id="ledger-1",
        nonce="unique-1",
        declared_at=datetime(2026, 10, 5, tzinfo=UTC),
        payload_json=b'{"delta_MME":"0.2","rationale":"economic hurdle"}',
    )

    with pytest.raises(ValueError, match="hash"):
        replace(record, previous_head="not-a-hash")
    with pytest.raises(ValueError, match="UTC"):
        replace(record, declared_at=datetime(2026, 10, 5))
    with pytest.raises(ValueError, match="nonce"):
        replace(record, nonce="")


def test_unsigned_chain_cannot_authorize_development_release() -> None:
    record = DeclarationRecord(
        name="EFFECT_DECLARED",
        sequence=1,
        previous_head="0" * 64,
        operator_id="operator-1",
        strategy_spec_sha256="a" * 64,
        catalog_id="catalog-1",
        ledger_id="ledger-1",
        nonce="unique-1",
        declared_at=datetime(2026, 10, 5, tzinfo=UTC),
        payload_json=b'{"delta_MME":"0.2","rationale":"economic hurdle"}',
    )
    receipt = DeclarationReceipt(record, b"", b"")
    with pytest.raises(DeclarationLineageError):
        verify_declaration_chain(
            (receipt,),
            now=datetime(2026, 10, 6, tzinfo=UTC),
        )


def _throwaway_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[tuple[DeclarationReceipt, ...], CustodianTrust]:
    """Generate test-only signatures; the RFC 3161 parser has recorded DER tests separately."""
    key = Ed25519PrivateKey.generate()
    public_key_raw = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    root = b"THROWAWAY TEST TSA ROOT"
    trust = CustodianTrust(
        public_key_raw,
        hashlib.sha256(public_key_raw).hexdigest(),
        (hashlib.sha256(root).hexdigest(),),
        TrustStore((root,), (b"THROWAWAY TEST TSA CRL",)),
        frozenset({"1.2.3.4.1"}),
    )

    def test_timestamp(token: bytes, digest: bytes, **_kwargs: object) -> VerifiedTimestamp:
        if token[:32] != digest:
            raise ValueError("throwaway token imprint mismatch")
        instant = datetime.fromisoformat(token[32:].decode("ascii"))
        return VerifiedTimestamp(instant, 1, "1.2.3.4.1", hashlib.sha256(root).hexdigest())

    monkeypatch.setattr(declarations, "verify_timestamp_token", test_timestamp)
    payloads = (
        {"delta_MME": "0.2", "rationale": "throwaway test hurdle"},
        {
            key: {"test": "bound"}
            for key in (
                "edge_rules",
                "tail_risk_rules",
                "data_rules",
                "portfolio_rules",
                "feasibility_rules",
                "promotion_thresholds",
                "statistical_rules",
            )
        },
        {
            "method_family": "throwaway-test",
            "scenario_matrix": ["test"],
            "generators": ["test"],
            "seeds": {"test": 1},
            "acceptance_caps": {"test": "0.05"},
            "code_sha256": "b" * 64,
            "pilot_report_sha256": "c" * 64,
        },
    )
    names = ("EFFECT_DECLARED", "PROMOTION_PROTOCOL_DECLARED", "METHOD_AUDIT_DECLARED")
    receipts: list[DeclarationReceipt] = []
    head = "0" * 64
    for index, (name, payload) in enumerate(zip(names, payloads, strict=True), 1):
        declared = datetime(2026, 10, 5, index, tzinfo=UTC)
        record = DeclarationRecord(
            name,
            index,
            head,
            "THROWAWAY TEST OPERATOR",
            "a" * 64,
            "test-catalog",
            "test-ledger",
            f"test-nonce-{index}",
            declared,
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii"),
        )
        signature = key.sign(record.canonical_bytes())
        token = hashlib.sha256(signature).digest() + (
            declared + timedelta(seconds=1)
        ).isoformat().encode("ascii")
        receipt = DeclarationReceipt(record, signature, token)
        receipts.append(receipt)
        head = receipt.head
    return tuple(receipts), trust


def _verify_test_chain(receipts: tuple[DeclarationReceipt, ...], trust: CustodianTrust):
    return verify_declaration_chain(
        receipts,
        now=datetime(2026, 10, 6, tzinfo=UTC),
        test_mode=True,
        test_trust=trust,
    )


def test_throwaway_ed25519_chain_verifies_end_to_end_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipts, trust = _throwaway_chain(monkeypatch)
    chain = _verify_test_chain(receipts, trust)
    assert chain.head == receipts[-1].head
    changed = list(receipts)
    changed[1] = replace(changed[1], signature=b"tampered")
    with pytest.raises(DeclarationLineageError):
        _verify_test_chain(tuple(changed), trust)


def test_production_chain_rejects_caller_supplied_trust(monkeypatch: pytest.MonkeyPatch) -> None:
    receipts, trust = _throwaway_chain(monkeypatch)
    with pytest.raises(DeclarationLineageError):
        verify_declaration_chain(
            receipts,
            now=datetime(2026, 10, 6, tzinfo=UTC),
            test_trust=trust,
        )


def test_three_signed_timestamped_declarations_have_one_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipts, trust = _throwaway_chain(monkeypatch)
    chain = _verify_test_chain(receipts, trust)
    assert chain.names == (
        "EFFECT_DECLARED",
        "PROMOTION_PROTOCOL_DECLARED",
        "METHOD_AUDIT_DECLARED",
    )
    assert chain.head == receipts[-1].head
    assert chain.ledger_id == "test-ledger"


def test_append_extends_only_the_expected_head(monkeypatch: pytest.MonkeyPatch) -> None:
    expected, trust = _throwaway_chain(monkeypatch)

    class ThrowawayTestAuthority:
        def __init__(self) -> None:
            self.receipts: list[DeclarationReceipt] = []

        def read_receipts(self) -> tuple[DeclarationReceipt, ...]:
            return tuple(self.receipts)

        def append_if_head(self, expected_head: str, receipt: DeclarationReceipt) -> None:
            current = self.receipts[-1].head if self.receipts else "0" * 64
            if expected_head != current:
                raise ValueError("stale head")
            self.receipts.append(receipt)

    authority = ThrowawayTestAuthority()
    for expected_receipt in expected:
        receipt = append_declaration(
            authority,
            expected_receipt,
            now=datetime(2026, 10, 6, tzinfo=UTC),
            test_mode=True,
            test_trust=trust,
        )
        assert receipt.head == expected_receipt.head
    assert len(authority.read_receipts()) == 3
    with pytest.raises(DeclarationLineageError):
        append_declaration(
            authority,
            expected[-1],
            now=datetime(2026, 10, 6, tzinfo=UTC),
            test_mode=True,
            test_trust=trust,
        )


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "reordered",
        "backdated",
        "wrong_head",
        "wrong_nonce",
        "wrong_signature",
        "wrong_operator_identity",
    ],
)
def test_declaration_lineage_refuses_tampering(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    original, trust = _throwaway_chain(monkeypatch)
    receipts = list(original)
    if failure == "missing":
        receipts.pop()
    elif failure == "reordered":
        receipts[0], receipts[1] = receipts[1], receipts[0]
    elif failure == "backdated":
        receipts[1] = replace(
            receipts[1],
            record=replace(receipts[1].record, declared_at=datetime(2026, 10, 5, 1, tzinfo=UTC)),
        )
    elif failure == "wrong_head":
        receipts[1] = replace(
            receipts[1], record=replace(receipts[1].record, previous_head="d" * 64)
        )
    elif failure == "wrong_nonce":
        receipts[1] = replace(receipts[1], record=replace(receipts[1].record, nonce="test-nonce-1"))
    elif failure == "wrong_operator_identity":
        receipts = [
            replace(item, record=replace(item.record, operator_id="other-operator"))
            for item in receipts
        ]
    else:
        receipts[1] = replace(receipts[1], signature=b"not-a-signature")
    with pytest.raises(DeclarationLineageError):
        _verify_test_chain(tuple(receipts), trust)
