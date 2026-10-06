"""Recorded, offline RFC 3161 verification with throwaway test PKI only."""

from __future__ import annotations

import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from qat.promotion.rfc3161 import (
    TimestampVerificationError,
    TrustStore,
    verify_timestamp_token,
)

FIXTURES = Path(__file__).parent / "fixtures" / "rfc3161-throwaway-test-only"
DIGEST = bytes.fromhex("3c8802794f3df2f526604a15590aecd331decb6ce65ce4f36e85c3820e2ddb63")
NOW = datetime(2026, 10, 6, tzinfo=UTC)
POLICY = frozenset({"1.2.3.4.1"})

# Reviewed OpenSSL tolerances. Each position is a byte offset in token.der;
# a new disagreement, even in the same region, must be reviewed separately.
_STRICTER_REJECTION_ALLOWLIST = {
    "SignedData version, RFC 5652 5.1 (TSTInfo requires version 3)": {25},
    "digestAlgorithms SHA-256 parameters, RFC 5652 5.1 / RFC 5754 2": {41},
    "unused embedded X.509 certificate syntax, RFC 5652 10.2.2 / RFC 5280 4.1": {
        1002,
        1019,
        1021,
        1032,
        1062,
        1063,
        1066,
        1068,
        1069,
        1070,
        1071,
        1074,
        1077,
        1078,
        1079,
        1080,
        1083,
        1084,
        1085,
        1086,
        1087,
        1089,
        1144,
        1434,
        1454,
    },
    "SignerInfo version and issuer-and-serial binding, RFC 5652 5.3": {
        1747,
        1765,
        1773,
        1781,
    },
    "SignerInfo digest parameters, RFC 5652 5.3 / RFC 5754 2": {1803},
    "signedAttrs syntax, RFC 5652 5.3 and 11.1": {1805, 1821},
    "signatureAlgorithm identifier, RFC 5652 5.3": set(range(1976, 1986)),
}


def _trust(crl: str = "root.crl.der") -> TrustStore:
    return TrustStore(
        roots=((FIXTURES / "root.der").read_bytes(),),
        crls=((FIXTURES / crl).read_bytes(),),
    )


def _token() -> bytes:
    return (FIXTURES / "token.der").read_bytes()


def _openssl() -> str:
    for executable in (
        "C:/Program Files/Git/ucrt64/bin/openssl.exe",
        shutil.which("openssl"),
    ):
        if executable and Path(executable).is_file():
            return executable
    pytest.fail("OpenSSL is required for the RFC 3161 differential test")


def _openssl_accepts(token: bytes, *, token_file: Path, root_file: Path) -> bool:
    token_file.write_bytes(token)
    result = subprocess.run(
        [
            _openssl(),
            "ts",
            "-verify",
            "-token_in",
            "-in",
            str(token_file),
            "-digest",
            DIGEST.hex(),
            "-CAfile",
            str(root_file),
        ],
        capture_output=True,
        check=False,
        timeout=5,
    )
    return result.returncode == 0


def _differential_files(tmp_path: Path) -> tuple[Path, Path]:
    root = x509.load_der_x509_certificate((FIXTURES / "root.der").read_bytes())
    root_file = tmp_path / "root.pem"
    root_file.write_bytes(root.public_bytes(serialization.Encoding.PEM))
    return tmp_path / "tampered-token.der", root_file


def _ours_accepts(token: bytes) -> bool:
    try:
        verify_timestamp_token(token, DIGEST, trust=_trust(), now=NOW, allowed_policies=POLICY)
    except TimestampVerificationError:
        return False
    return True


def test_recorded_throwaway_token_verifies_offline() -> None:
    stamp = verify_timestamp_token(
        _token(), DIGEST, trust=_trust(), now=NOW, allowed_policies=POLICY
    )
    assert stamp.policy_oid == "1.2.3.4.1"
    assert stamp.generated_at.date() == datetime(2026, 10, 5, tzinfo=UTC).date()


def test_certificate_parser_exception_is_contained(monkeypatch: pytest.MonkeyPatch) -> None:
    """cryptography 46 can raise KeyError while reading a malformed issuer."""

    def broken_certificate(_der: bytes) -> object:
        raise KeyError("malformed issuer")

    monkeypatch.setattr("qat.promotion.rfc3161.x509.load_der_x509_certificate", broken_certificate)
    with pytest.raises(TimestampVerificationError):
        verify_timestamp_token(_token(), DIGEST, trust=_trust(), now=NOW, allowed_policies=POLICY)


def test_byte_1032_tamper_cannot_escape_as_cryptography_exception() -> None:
    """cryptography 46.0.6 raises KeyError for this malformed certificate issuer."""
    token = bytearray(_token())
    token[1032] ^= 1 << (1032 % 8)
    with pytest.raises(TimestampVerificationError):
        verify_timestamp_token(
            bytes(token), DIGEST, trust=_trust(), now=NOW, allowed_policies=POLICY
        )


def test_unused_embedded_root_signature_does_not_define_the_pinned_path(tmp_path: Path) -> None:
    """A root carried in CertificateSet is optional path material (RFC 5652, 5.1)."""
    token = bytearray(_token())
    token[1500] ^= 1
    token_file, root_file = _differential_files(tmp_path)
    assert _openssl_accepts(bytes(token), token_file=token_file, root_file=root_file)
    assert _ours_accepts(bytes(token))


def test_mistagged_embedded_certificate_choice_is_rejected(tmp_path: Path) -> None:
    """A SET in CertificateSet is not a CertificateChoices value (RFC 5652, 10.2.2)."""
    token = bytearray(_token())
    token[990] ^= 1
    token_file, root_file = _differential_files(tmp_path)
    assert not _openssl_accepts(bytes(token), token_file=token_file, root_file=root_file)
    assert not _ours_accepts(bytes(token))


@pytest.mark.parametrize("offset", [1101, 1103, 1111, 1119])
def test_embedded_root_with_altered_subject_is_rejected(offset: int, tmp_path: Path) -> None:
    token = bytearray(_token())
    token[offset] ^= 1 << (offset % 8)
    token_file, root_file = _differential_files(tmp_path)
    assert not _openssl_accepts(bytes(token), token_file=token_file, root_file=root_file)
    assert not _ours_accepts(bytes(token))


def test_signer_identifier_must_be_issuer_and_serial_sequence(tmp_path: Path) -> None:
    token = bytearray(_token())
    token[1748] ^= 1 << (1748 % 8)
    token_file, root_file = _differential_files(tmp_path)
    assert not _openssl_accepts(bytes(token), token_file=token_file, root_file=root_file)
    assert not _ours_accepts(bytes(token))


@pytest.mark.parametrize(
    ("field", "offset"),
    [
        ("outer content tag", 15),
        ("SignedData digest list tag", 26),
        ("encapsulated content tag", 59),
        ("signer signature algorithm tag", 1972),
    ],
)
def test_unsigned_wrapper_bit_tamper_matches_openssl(
    field: str, offset: int, tmp_path: Path
) -> None:
    """Changing an unsigned CMS wrapper must not bypass structure validation."""
    token = bytearray(_token())
    token[offset] ^= 1
    token_file, root_file = _differential_files(tmp_path)
    assert not _openssl_accepts(bytes(token), token_file=token_file, root_file=root_file), field
    assert not _ours_accepts(bytes(token)), field


def test_every_byte_single_bit_tamper_rejects_all_openssl_rejections(tmp_path: Path) -> None:
    """One-directional parity, with only reviewed standards-based stricter rejects."""
    token = _token()
    token_file, root_file = _differential_files(tmp_path)
    assert _openssl_accepts(token, token_file=token_file, root_file=root_file)
    assert _ours_accepts(token)
    allowlisted = set().union(*_STRICTER_REJECTION_ALLOWLIST.values())
    assert sum(map(len, _STRICTER_REJECTION_ALLOWLIST.values())) == len(allowlisted)
    unexpected: list[tuple[int, bool, bool]] = []
    observed_stricter: set[int] = set()
    for position in range(len(token)):
        tampered = bytearray(token)
        tampered[position] ^= 1 << (position % 8)
        expected = _openssl_accepts(bytes(tampered), token_file=token_file, root_file=root_file)
        actual = _ours_accepts(bytes(tampered))
        if actual != expected:
            if expected and not actual and position in allowlisted:
                observed_stricter.add(position)
            else:
                unexpected.append((position, expected, actual))
    assert not unexpected, f"Unreviewed OpenSSL disagreement: {unexpected}"
    assert observed_stricter == allowlisted, "Reviewed divergence set changed; review the allowlist"


@pytest.mark.parametrize(
    "failure", ["wrong_imprint", "wrong_policy", "tampered_token", "revoked", "expired"]
)
def test_recorded_token_fails_closed(failure: str) -> None:
    token = _token()
    digest = DIGEST
    policy = POLICY
    trust = _trust()
    now = NOW
    if failure == "wrong_imprint":
        digest = bytes(32)
    elif failure == "wrong_policy":
        policy = frozenset({"1.2.3.4.2"})
    elif failure == "tampered_token":
        token = token[:-1] + bytes([token[-1] ^ 1])
    elif failure == "revoked":
        trust = _trust("root.revoked.crl.der")
    else:
        now = datetime(2041, 1, 1, tzinfo=UTC)
    with pytest.raises(TimestampVerificationError):
        verify_timestamp_token(token, digest, trust=trust, now=now, allowed_policies=policy)
