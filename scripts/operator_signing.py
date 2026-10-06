"""Offline operator-only Ed25519 key creation and exact-byte signing.

Run this script only from the operator's separate account. The research agent
may execute its tests with throwaway keys, but never with an operator key.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import re
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def generate_key_files(private_path: Path, public_path: Path, *, passphrase: bytes) -> str:
    """Create a passphrase-encrypted key and raw public key without overwriting either."""
    if not passphrase or private_path == public_path:
        raise ValueError("a passphrase and distinct key paths are required")
    if private_path.exists() or public_path.exists():
        raise FileExistsError("key output path already exists")
    key = Ed25519PrivateKey.generate()
    encrypted = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(passphrase),
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    with private_path.open("xb") as target:
        target.write(encrypted)
    with public_path.open("xb") as target:
        target.write(public)
    return hashlib.sha256(public).hexdigest()


def sign_canonical_file(
    private_path: Path,
    payload_path: Path,
    signature_path: Path,
    *,
    passphrase: bytes,
    expected_sha256: str,
) -> dict[str, str]:
    """Sign only when the exact input bytes match the operator-reviewed digest."""
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise ValueError("reviewed SHA-256 must be a lowercase 64-character digest")
    payload = payload_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != expected_sha256:
        raise ValueError("payload does not match reviewed SHA-256")
    if signature_path.exists():
        raise FileExistsError("signature output path already exists")
    key = serialization.load_pem_private_key(private_path.read_bytes(), password=passphrase)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("operator signing key must be Ed25519")
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    result = {
        "algorithm": "Ed25519",
        "payload_sha256": digest,
        "public_key_raw_b64": base64.b64encode(public).decode("ascii"),
        "public_key_sha256": hashlib.sha256(public).hexdigest(),
        "signature_b64": base64.b64encode(key.sign(payload)).decode("ascii"),
    }
    with signature_path.open("xb") as target:
        target.write(json.dumps(result, sort_keys=True, separators=(",", ":")).encode("ascii"))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline operator Ed25519 signing")
    actions = parser.add_subparsers(dest="action", required=True)
    create = actions.add_parser("generate-key")
    create.add_argument("--private-key", type=Path, required=True)
    create.add_argument("--public-key", type=Path, required=True)
    sign = actions.add_parser("sign")
    sign.add_argument("--private-key", type=Path, required=True)
    sign.add_argument("--canonical-file", type=Path, required=True)
    sign.add_argument("--signature-file", type=Path, required=True)
    sign.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    passphrase = getpass.getpass("Operator key passphrase: ").encode("utf-8")
    if args.action == "generate-key":
        again = getpass.getpass("Confirm passphrase: ").encode("utf-8")
        if passphrase != again:
            raise ValueError("passphrase confirmation differs")
        fingerprint = generate_key_files(args.private_key, args.public_key, passphrase=passphrase)
        print(f"Public key SHA-256: {fingerprint}")
    else:
        result = sign_canonical_file(
            args.private_key,
            args.canonical_file,
            args.signature_file,
            passphrase=passphrase,
            expected_sha256=args.expected_sha256,
        )
        print(f"Signed payload SHA-256: {result['payload_sha256']}")


if __name__ == "__main__":
    main()
