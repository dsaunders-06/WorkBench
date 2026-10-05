"""Recorded, offline RFC 3161 verification with throwaway test PKI only."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from qat.promotion.rfc3161 import (
    TimestampVerificationError,
    TrustStore,
    verify_timestamp_token,
)

FIXTURES = Path(__file__).parent / "fixtures" / "rfc3161-throwaway-test-only"
DIGEST = bytes.fromhex("3c8802794f3df2f526604a15590aecd331decb6ce65ce4f36e85c3820e2ddb63")
NOW = datetime(2026, 10, 6, tzinfo=UTC)
POLICY = frozenset({"1.2.3.4.1"})


def _trust(crl: str = "root.crl.der") -> TrustStore:
    return TrustStore(
        roots=((FIXTURES / "root.der").read_bytes(),),
        crls=((FIXTURES / crl).read_bytes(),),
    )


def _token() -> bytes:
    return (FIXTURES / "token.der").read_bytes()


def test_recorded_throwaway_token_verifies_offline() -> None:
    stamp = verify_timestamp_token(
        _token(), DIGEST, trust=_trust(), now=NOW, allowed_policies=POLICY
    )
    assert stamp.policy_oid == "1.2.3.4.1"
    assert stamp.generated_at.date() == datetime(2026, 10, 5, tzinfo=UTC).date()


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
