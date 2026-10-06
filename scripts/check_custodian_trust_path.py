"""Inspect the live custodian trust path and test rejection of a writable copy."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qat.promotion import operator_signatures as signatures  # noqa: E402


def _show_acl(component: Path) -> None:
    snapshot = signatures._windows_acl_snapshot(component)
    print(f"{component}: owner={snapshot.owner}")
    access_list = subprocess.run(
        ["icacls", str(component)], check=True, capture_output=True, text=True
    )
    print(access_list.stdout.rstrip())
    for principal, mask, inherit_only in snapshot.grants:
        print(f"  parsed allow={principal} mask=0x{mask:08x} inherit_only={inherit_only}")


def run_self_check(path: Path) -> None:
    """Read only metadata; the temporary copy contains no trust material."""
    if os.name != "nt":
        raise RuntimeError("the live ACL self-check runs on the operator's Windows machine")
    if path != signatures.PRODUCTION_TRUST_PATH:
        raise ValueError("only the fixed production trust path may be checked")
    print("Production trust path ACLs:")
    for component in (*reversed(path.parents), path):
        _show_acl(component)
    signatures._validate_trust_path_security(path)
    print("production trust path accepted")

    descriptor, temporary = tempfile.mkstemp(
        prefix="promotion-trust-selfcheck-", suffix=".json", dir=path.parent
    )
    os.close(descriptor)
    copy_path = Path(temporary)
    try:
        copy_path.write_text("public ACL test only\n", encoding="ascii")
        subprocess.run(
            ["icacls", str(copy_path), "/grant", "*S-1-5-32-545:(W)"],
            check=True,
            capture_output=True,
            text=True,
        )
        _show_acl(copy_path)
        copy_acl = signatures._windows_acl_snapshot(copy_path)
        if not any(
            principal == "S-1-5-32-545" and mask & signatures._BOUNDARY_WRITE_RIGHTS
            for principal, mask, _ in copy_acl.grants
        ):
            raise RuntimeError("test copy did not acquire the deliberate Users write grant")
        try:
            signatures._validate_trust_path_security(copy_path)
        except signatures.TrustConfigurationError as exc:
            if "grants replacement or write rights" not in str(exc):
                raise RuntimeError(f"test copy was refused for an unrelated reason: {exc}") from exc
            print("writable test copy refused: " + str(exc))
        else:
            raise RuntimeError("unsafe writable test copy was accepted")
    finally:
        copy_path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    run_self_check(signatures.PRODUCTION_TRUST_PATH)


if __name__ == "__main__":
    main()
