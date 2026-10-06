"""The operator's live trust-path diagnostic never needs a signing key."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import qat.promotion.operator_signatures as signatures


def test_self_check_reports_acl_and_refuses_writable_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    check = importlib.import_module("scripts.check_custodian_trust_path")
    path = tmp_path / "QAT" / "Custodian" / "promotion-trust.json"
    path.parent.mkdir(parents=True)
    path.write_text("public-test-only", encoding="ascii")

    def snapshot(component: Path) -> SimpleNamespace:
        grants = [("ADMIN", 0x001F01FF, False)]
        if component.name.startswith("promotion-trust-selfcheck-"):
            grants.append(("S-1-5-32-545", 0x00000002, False))
        return SimpleNamespace(owner="ADMIN", grants=grants)

    monkeypatch.setattr(signatures, "_windows_acl_snapshot", snapshot)
    monkeypatch.setattr(signatures, "PRODUCTION_TRUST_PATH", path)
    monkeypatch.setattr(signatures, "_is_reparse_point", lambda _: False)
    monkeypatch.setattr(
        signatures,
        "_trusted_windows_sids",
        lambda: {
            "custodian": "CUSTODIAN",
            "administrators": "ADMIN",
            "system": "SYSTEM",
            "trusted_installer": "TRUSTED_INSTALLER",
        },
    )
    monkeypatch.setattr(
        check.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="full access list: DENY and ALLOW"),
    )

    check.run_self_check(path)
    output = capsys.readouterr().out
    assert str(path) in output
    assert "owner=ADMIN" in output
    assert "S-1-5-32-545" in output
    assert "full access list: DENY and ALLOW" in output
    assert "writable test copy refused" in output
    assert not list(path.parent.glob("promotion-trust-selfcheck-*.json"))
