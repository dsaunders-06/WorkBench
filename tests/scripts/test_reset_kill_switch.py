"""A reset is complete only when a fresh reader sees a clear switch."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from qat.domain.risk_engine.kill_switch import KillSwitch
from scripts import reset_kill_switch


def test_apply_refuses_a_reset_that_was_not_persisted(tmp_path, monkeypatch, capsys):
    KillSwitch(tmp_path).trip("broker mismatch")
    monkeypatch.setattr(reset_kill_switch, "Settings", lambda: SimpleNamespace(data_dir=tmp_path))
    monkeypatch.setattr(sys, "argv", ["reset_kill_switch.py", "--apply", "--operator", "DS"])

    def memory_only_reset(self: KillSwitch, operator: str) -> None:
        del operator
        self._tripped = False
        self._reason = None

    monkeypatch.setattr(KillSwitch, "reset", memory_only_reset)
    assert reset_kill_switch.main() != 0
    assert KillSwitch(tmp_path).tripped
    assert "persist" in capsys.readouterr().out.lower()


def test_apply_requires_a_named_operator(tmp_path, monkeypatch, capsys):
    KillSwitch(tmp_path).trip("broker mismatch")
    monkeypatch.setattr(
        reset_kill_switch,
        "Settings",
        lambda: SimpleNamespace(data_dir=tmp_path, operator_name=""),
    )
    monkeypatch.setattr(sys, "argv", ["reset_kill_switch.py", "--apply"])

    assert reset_kill_switch.main() != 0
    assert KillSwitch(tmp_path).tripped
    assert "operator" in capsys.readouterr().out.lower()
