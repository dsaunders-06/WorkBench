"""The QAT store copy must be restorable and detect startup changes."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "phase3_unwind_store_snapshot.py"


def _module():
    spec = importlib.util.spec_from_file_location("phase3_unwind_store_snapshot", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backup_copies_exact_files_and_diff_detects_all_change_types(tmp_path: Path):
    module = _module()
    source = tmp_path / "qat"
    source.mkdir()
    (source / ".env").write_bytes(b"secret-setting\n")
    data = source / "data"
    data.mkdir()
    (data / "open_position_entries.json").write_bytes(b'{"BOQ": 1}\n')
    snapshot = tmp_path / "outside-git" / "snapshot"

    manifest = module.backup(source, snapshot)
    assert (snapshot / "stores" / ".env").read_bytes() == b"secret-setting\n"
    assert (
        snapshot / "stores" / "data" / "open_position_entries.json"
    ).read_bytes() == b'{"BOQ": 1}\n'
    assert set(manifest["files"]) == {".env", "data/open_position_entries.json"}
    assert module.diff(source, manifest) == {"added": [], "changed": [], "removed": []}

    (source / ".env").write_bytes(b"changed\n")
    (data / "open_position_entries.json").unlink()
    (data / "new.json").write_bytes(b"new\n")
    assert module.diff(source, manifest) == {
        "added": ["data/new.json"],
        "changed": [".env"],
        "removed": ["data/open_position_entries.json"],
    }


def test_backup_never_overwrites_an_existing_snapshot(tmp_path: Path):
    module = _module()
    source = tmp_path / "qat"
    source.mkdir()
    snapshot = tmp_path / "outside-git" / "snapshot"
    module.backup(source, snapshot)
    with pytest.raises(FileExistsError):
        module.backup(source, snapshot)
