"""The DU read-only check must refuse every order path offline."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from qat.data.broker.ib_adapter import LivePortInPaperModeError

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "phase1_exit_readiness_du_check.py"


def _module():
    spec = importlib.util.spec_from_file_location("phase1_exit_readiness_du_check", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_each_gateway_request_rechecks_exactly_one_du_account() -> None:
    module = _module()
    accounts = ["DU123"]
    called = []
    client = SimpleNamespace(
        managedAccounts=lambda: accounts,
        reqPositionsAsync=lambda: called.append(tuple(accounts)) or "request",
    )
    guarded = module.GuardedReadOnlyClient(client)
    assert guarded.reqPositionsAsync() == "request"
    assert called == [("DU123",)]

    accounts[:] = ["U123"]
    with pytest.raises(LivePortInPaperModeError, match="non-paper"):
        guarded.reqPositionsAsync()
    assert len(called) == 1


def test_guarded_client_exposes_no_order_submission_or_cancel() -> None:
    module = _module()
    client = SimpleNamespace(managedAccounts=lambda: ["DU123"], placeOrder=lambda *a: None)
    guarded = module.GuardedReadOnlyClient(client)
    with pytest.raises(RuntimeError, match="read-only"):
        guarded.placeOrder(None, None)
