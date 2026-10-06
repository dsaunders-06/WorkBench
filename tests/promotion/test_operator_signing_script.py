"""Offline script tests use runtime throwaway Ed25519 keys only."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from scripts.operator_signing import generate_key_files, sign_canonical_file


def test_throwaway_key_is_encrypted_and_signs_exact_reviewed_bytes(tmp_path: Path) -> None:
    private = tmp_path / "THROWAWAY-TEST-ONLY-encrypted-key.pem"
    public = tmp_path / "THROWAWAY-TEST-ONLY-public-key.bin"
    payload = tmp_path / "THROWAWAY-TEST-ONLY-canonical-payload.bin"
    signature = tmp_path / "THROWAWAY-TEST-ONLY-signature.json"
    passphrase = b"THROWAWAY-TEST-ONLY-passphrase"
    payload.write_bytes(b'QAT-OPERATOR-ACTION-v1\n{"action":"DEV_DATA_RELEASED","payload":{}}')

    fingerprint = generate_key_files(private, public, passphrase=passphrase)
    assert b"ENCRYPTED PRIVATE KEY" in private.read_bytes()
    assert fingerprint == hashlib.sha256(public.read_bytes()).hexdigest()
    result = sign_canonical_file(
        private,
        payload,
        signature,
        passphrase=passphrase,
        expected_sha256=hashlib.sha256(payload.read_bytes()).hexdigest(),
    )
    recorded = json.loads(signature.read_text(encoding="ascii"))
    assert result == recorded
    assert recorded["algorithm"] == "Ed25519"
    Ed25519PublicKey.from_public_bytes(base64.b64decode(recorded["public_key_raw_b64"])).verify(
        base64.b64decode(recorded["signature_b64"]), payload.read_bytes()
    )
    with pytest.raises(FileExistsError):
        sign_canonical_file(
            private,
            payload,
            signature,
            passphrase=passphrase,
            expected_sha256=hashlib.sha256(payload.read_bytes()).hexdigest(),
        )


def test_signer_refuses_unreviewed_payload_hash(tmp_path: Path) -> None:
    private = tmp_path / "THROWAWAY-TEST-ONLY-key.pem"
    public = tmp_path / "THROWAWAY-TEST-ONLY-public.bin"
    payload = tmp_path / "THROWAWAY-TEST-ONLY-payload.bin"
    output = tmp_path / "THROWAWAY-TEST-ONLY-signature.json"
    generate_key_files(private, public, passphrase=b"THROWAWAY-TEST-ONLY-passphrase")
    payload.write_bytes(b"changed after review")
    with pytest.raises(ValueError, match="reviewed SHA-256"):
        sign_canonical_file(
            private,
            payload,
            output,
            passphrase=b"THROWAWAY-TEST-ONLY-passphrase",
            expected_sha256="0" * 64,
        )
    assert not output.exists()
