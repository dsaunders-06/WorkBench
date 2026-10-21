"""Durable symbol quarantine for broker orders QAT cannot prove it placed."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qat.data.broker.gtc_expiry import _atomic_json


class ForeignOrderQuarantine:
    """A vanished foreign order remains a block until DS explicitly clears it."""

    def __init__(self, path: Path) -> None:
        self.path = path
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("active"), dict)
                or not isinstance(payload.get("clearances"), list)
            ):
                raise ValueError("foreign-order quarantine store is invalid")
            self._payload: dict[str, Any] = payload
        else:
            self._payload = {"active": {}, "clearances": []}

    def reason(self, symbol: str) -> str | None:
        active = self._payload["active"]
        if not isinstance(active, dict):
            raise ValueError("foreign-order quarantine store is invalid")
        return (
            f"unowned broker order on {symbol}; DS reconciliation and clearance required"
            if symbol in active
            else None
        )

    def record(self, symbol: str, identity: dict[str, int]) -> None:
        active = dict(self._payload["active"])
        if symbol in active:
            return
        active[symbol] = {"first_seen_utc": datetime.now(UTC).isoformat(), **identity}
        payload = {**self._payload, "active": active}
        _atomic_json(self.path, payload)
        self._payload = payload

    def clear(self, symbol: str, *, operator: str, ds_approval_ref: str) -> bool:
        active = dict(self._payload["active"])
        if symbol not in active:
            return False
        active.pop(symbol)
        clearances = list(self._payload["clearances"])
        clearances.append(
            {
                "symbol": symbol,
                "operator": operator,
                "ds_approval_ref": ds_approval_ref,
                "cleared_at_utc": datetime.now(UTC).isoformat(),
            }
        )
        payload = {"active": active, "clearances": clearances}
        _atomic_json(self.path, payload)
        self._payload = payload
        return True
