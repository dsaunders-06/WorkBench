"""Stage A declarations refuse authority that the research agent does not own."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

import qat.promotion.declarations as declarations
from qat.promotion.declarations import (
    DeclarationLineageError,
    DeclarationReceipt,
    DeclarationRecord,
    SigningAuthorityError,
    TrustStore,
    append_declaration,
    verify_declaration_chain,
)
from qat.promotion.rfc3161 import VerifiedTimestamp


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
    receipt = DeclarationReceipt(record, b"", b"", (), b"")
    empty_trust = TrustStore(roots=(), crls=())
    with pytest.raises(DeclarationLineageError):
        verify_declaration_chain(
            (receipt,),
            operator_trust=empty_trust,
            tsa_trust=empty_trust,
            allowed_tsa_policies=frozenset({"1.2.3.4"}),
            now=datetime(2026, 10, 6, tzinfo=UTC),
        )


def _throwaway_chain(monkeypatch: pytest.MonkeyPatch) -> tuple[DeclarationReceipt, ...]:
    """Generate test-only signatures; the RFC 3161 parser has recorded DER tests separately."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "THROWAWAY TEST OPERATOR")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(datetime(2020, 1, 1, tzinfo=UTC))
        .not_valid_after(datetime(2040, 1, 1, tzinfo=UTC))
        .sign(key, hashes.SHA256())
    )
    cert_der = cert.public_bytes(serialization.Encoding.DER)

    def test_certificate(*_args: object, **_kwargs: object) -> x509.Certificate:
        return cert

    def test_timestamp(token: bytes, digest: bytes, **_kwargs: object) -> VerifiedTimestamp:
        if token[:32] != digest:
            raise ValueError("throwaway token imprint mismatch")
        instant = datetime.fromisoformat(token[32:].decode("ascii"))
        return VerifiedTimestamp(instant, 1, "1.2.3.4.1", hashlib.sha256(cert_der).hexdigest())

    monkeypatch.setattr(declarations, "verify_certificate_chain", test_certificate)
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
        signature = key.sign(record.canonical_bytes(), padding.PKCS1v15(), hashes.SHA256())
        token = hashlib.sha256(signature).digest() + (
            declared + timedelta(seconds=1)
        ).isoformat().encode("ascii")
        receipt = DeclarationReceipt(record, signature, cert_der, (), token)
        receipts.append(receipt)
        head = receipt.head
    return tuple(receipts)


def _verify_test_chain(receipts: tuple[DeclarationReceipt, ...]):
    trust = TrustStore(roots=(b"throwaway-test",), crls=(b"throwaway-test",))
    return verify_declaration_chain(
        receipts,
        operator_trust=trust,
        tsa_trust=trust,
        allowed_tsa_policies=frozenset({"1.2.3.4.1"}),
        now=datetime(2026, 10, 6, tzinfo=UTC),
    )


def test_recorded_throwaway_chain_verifies_end_to_end_offline() -> None:
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "rfc3161-throwaway-test-only"
        / "declaration-chain.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    assert data["status"] == "THROWAWAY TEST FIXTURE ONLY"
    decode = base64.b64decode
    receipts = []
    for item in data["receipts"]:
        raw = item["record"]
        record = DeclarationRecord(
            raw["name"],
            raw["sequence"],
            raw["previous_head"],
            raw["operator_id"],
            raw["strategy_spec_sha256"],
            raw["catalog_id"],
            raw["ledger_id"],
            raw["nonce"],
            datetime.fromisoformat(raw["declared_at"]),
            raw["payload_json"].encode("ascii"),
        )
        receipt = DeclarationReceipt(
            record,
            decode(item["signature_b64"]),
            decode(item["signer_certificate_der_b64"]),
            (),
            decode(item["rfc3161_token_b64"]),
        )
        assert receipt.head == item["head"]
        receipts.append(receipt)
    trust = TrustStore(
        (decode(data["operator_root_der_b64"]),), (decode(data["operator_crl_der_b64"]),)
    )
    tsa_trust = TrustStore((decode(data["tsa_root_der_b64"]),), (decode(data["tsa_crl_der_b64"]),))
    chain = verify_declaration_chain(
        receipts,
        operator_trust=trust,
        tsa_trust=tsa_trust,
        allowed_tsa_policies=frozenset(data["allowed_tsa_policies"]),
        now=datetime(2026, 10, 6, tzinfo=UTC),
    )
    assert chain.head == receipts[-1].head
    assert chain.names == (
        "EFFECT_DECLARED",
        "PROMOTION_PROTOCOL_DECLARED",
        "METHOD_AUDIT_DECLARED",
    )
    changed = list(receipts)
    changed[1] = replace(changed[1], signature=b"tampered")
    with pytest.raises(DeclarationLineageError):
        verify_declaration_chain(
            changed,
            operator_trust=trust,
            tsa_trust=tsa_trust,
            allowed_tsa_policies=frozenset(data["allowed_tsa_policies"]),
            now=datetime(2026, 10, 6, tzinfo=UTC),
        )


def test_three_signed_timestamped_declarations_have_one_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipts = _throwaway_chain(monkeypatch)
    chain = _verify_test_chain(receipts)
    assert chain.names == (
        "EFFECT_DECLARED",
        "PROMOTION_PROTOCOL_DECLARED",
        "METHOD_AUDIT_DECLARED",
    )
    assert chain.head == receipts[-1].head
    assert chain.ledger_id == "test-ledger"


def test_append_extends_only_the_expected_head(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = _throwaway_chain(monkeypatch)

    class ThrowawayTestAuthority:
        operator_trust = TrustStore((b"throwaway",), (b"throwaway",))
        tsa_trust = operator_trust
        allowed_tsa_policies = frozenset({"1.2.3.4.1"})

        def __init__(self) -> None:
            self.receipts: list[DeclarationReceipt] = []

        def read_receipts(self) -> tuple[DeclarationReceipt, ...]:
            return tuple(self.receipts)

        def sign(self, content: bytes) -> tuple[bytes, bytes, tuple[bytes, ...]]:
            selected = expected[len(self.receipts)]
            assert content == selected.record.canonical_bytes()
            return selected.signature, selected.signer_certificate_der, ()

        def timestamp(self, signed_digest: bytes) -> bytes:
            selected = expected[len(self.receipts)]
            assert signed_digest == hashlib.sha256(selected.signature).digest()
            return selected.rfc3161_token

        def append_if_head(self, expected_head: str, receipt: DeclarationReceipt) -> None:
            current = self.receipts[-1].head if self.receipts else "0" * 64
            if expected_head != current:
                raise ValueError("stale head")
            self.receipts.append(receipt)

    authority = ThrowawayTestAuthority()
    for expected_receipt in expected:
        receipt = append_declaration(
            authority, expected_receipt.record, now=datetime(2026, 10, 6, tzinfo=UTC)
        )
        assert receipt.head == expected_receipt.head
    assert len(authority.read_receipts()) == 3
    with pytest.raises(DeclarationLineageError):
        append_declaration(authority, expected[-1].record, now=datetime(2026, 10, 6, tzinfo=UTC))


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
    receipts = list(_throwaway_chain(monkeypatch))
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
        _verify_test_chain(tuple(receipts))
