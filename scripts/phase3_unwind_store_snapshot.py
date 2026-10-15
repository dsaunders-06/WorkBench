"""Make and compare a restorable, hashed copy of QAT's local stores outside Git."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _files(source: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"QAT store has a symlink: {path}")
        if path.is_file():
            result[path.relative_to(source).as_posix()] = path
    return result


def _outside_git(path: Path) -> None:
    if any((parent / ".git").exists() for parent in (path, *path.parents)):
        raise ValueError(f"store snapshot must stay outside Git: {path}")


def backup(source: Path, snapshot: Path) -> dict[str, Any]:
    source = source.expanduser().resolve()
    snapshot = snapshot.expanduser().resolve()
    if not source.is_dir():
        raise ValueError(f"QAT store source is not a directory: {source}")
    _outside_git(snapshot)
    if snapshot.is_relative_to(source):
        raise ValueError("snapshot cannot be inside the live QAT store")
    if snapshot.exists():
        raise FileExistsError(f"snapshot already exists: {snapshot}")
    started_utc = datetime.now(UTC).isoformat()
    paths = _files(source)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.mkdir()
    copied = snapshot / "stores"
    copied.mkdir()
    records: dict[str, dict[str, Any]] = {}
    for relative, original in sorted(paths.items()):
        target = copied / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        source_hash = _sha256(original)
        shutil.copy2(original, target)
        if _sha256(original) != source_hash or _sha256(target) != source_hash:
            raise OSError(f"QAT store changed during backup: {relative}")
        records[relative] = {"sha256": source_hash, "size": original.stat().st_size}
    manifest: dict[str, Any] = {
        "source": str(source),
        "snapshot": str(snapshot),
        "started_utc": started_utc,
        "finished_utc": datetime.now(UTC).isoformat(),
        "files": records,
    }
    manifest_path = snapshot / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    (snapshot / "manifest.sha256").write_text(
        f"{_sha256(manifest_path)}  manifest.json\n", encoding="ascii"
    )
    return manifest


def diff(source: Path, manifest: dict[str, Any]) -> dict[str, list[str]]:
    current = {relative: _sha256(path) for relative, path in _files(source).items()}
    before = {relative: row["sha256"] for relative, row in manifest["files"].items()}
    return {
        "added": sorted(current.keys() - before.keys()),
        "changed": sorted(
            key for key in current.keys() & before.keys() if current[key] != before[key]
        ),
        "removed": sorted(before.keys() - current.keys()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("backup", "diff"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "backup":
        manifest = backup(args.source, args.snapshot)
        print(f"Snapshot: {args.snapshot.resolve()} ({len(manifest['files'])} files)")
        return 0
    manifest_path = args.snapshot / "manifest.json"
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_hash = (args.snapshot / "manifest.sha256").read_text(encoding="ascii").split()[0]
    if _sha256(manifest_path) != expected_hash:
        raise ValueError("store snapshot manifest SHA-256 mismatch")
    print(json.dumps(diff(args.source, manifest), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
