"""Offline script tests use runtime throwaway Ed25519 keys only."""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
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


def test_openssl_primary_path_signs_exact_bytes_with_throwaway_key(tmp_path: Path) -> None:
    openssl = shutil.which("openssl") or "C:/Program Files/Git/ucrt64/bin/openssl.exe"
    if not Path(openssl).is_file():
        pytest.fail("OpenSSL is required for the operator signing interoperability test")
    private = tmp_path / "THROWAWAY-TEST-ONLY-private.pem"
    public_der = tmp_path / "THROWAWAY-TEST-ONLY-public.der"
    payload = tmp_path / "THROWAWAY-TEST-ONLY-canonical.bin"
    signature = tmp_path / "THROWAWAY-TEST-ONLY-signature.bin"
    payload.write_bytes(b'QAT-OPERATOR-ACTION-v1\n{"action":"DEV_DATA_RELEASED","payload":{}}')
    subprocess.run(
        [
            openssl,
            "genpkey",
            "-algorithm",
            "Ed25519",
            "-aes-256-cbc",
            "-pass",
            "pass:THROWAWAY-TEST-ONLY",
            "-out",
            str(private),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            openssl,
            "pkey",
            "-in",
            str(private),
            "-passin",
            "pass:THROWAWAY-TEST-ONLY",
            "-pubout",
            "-outform",
            "DER",
            "-out",
            str(public_der),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            openssl,
            "pkeyutl",
            "-sign",
            "-rawin",
            "-inkey",
            str(private),
            "-passin",
            "pass:THROWAWAY-TEST-ONLY",
            "-in",
            str(payload),
            "-out",
            str(signature),
        ],
        check=True,
        capture_output=True,
    )
    spki = public_der.read_bytes()
    assert len(spki) == 44 and spki[:12].hex() == "302a300506032b6570032100"
    Ed25519PublicKey.from_public_bytes(spki[12:]).verify(
        signature.read_bytes(), payload.read_bytes()
    )
