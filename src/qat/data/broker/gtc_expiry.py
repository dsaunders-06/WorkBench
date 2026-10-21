"""Durable broker-reported auto-cancel dates for QAT-owned protective stops."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path

from qat.data.broker.adapter import RestingStopOrder


@dataclass(frozen=True, slots=True)
class GtcRenewalPlan:
    """Pinned broker terms requiring a named operator's explicit approval."""

    symbol: str
    order_id: str
    broker_order_id: int
    quantity: float
    stop_price: float
    auto_cancel_date: date
    account: str
    con_id: int
    oca_group: str
    oca_type: int

    @property
    def digest(self) -> str:
        payload = {**asdict(self), "auto_cancel_date": self.auto_cancel_date.isoformat()}
        return sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _atomic_json(path: Path, payload: object) -> None:
    content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


class GtcRenewalJournal:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: dict[str, object]) -> None:
        prior = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []
        if not isinstance(prior, list):
            raise ValueError("GTC renewal journal is invalid")
        _atomic_json(self.path, [*prior, record])


class GtcExpiryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        if path.exists():
            stored = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(stored, dict) or not isinstance(stored.get("stops"), dict):
                raise ValueError("GTC expiry store is invalid")

    def record(self, stops: list[RestingStopOrder]) -> None:
        payload = {
            "stops": {
                stop.order_id: {
                    "symbol": stop.symbol,
                    "order_id": stop.order_id,
                    "stop_price": stop.stop_price,
                    "quantity": stop.quantity,
                    "auto_cancel_date": (
                        stop.auto_cancel_date.isoformat() if stop.auto_cancel_date else None
                    ),
                }
                for stop in sorted(stops, key=lambda item: item.order_id)
            }
        }
        content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if self.path.exists() and self.path.read_text(encoding="utf-8") == content:
            return
        _atomic_json(self.path, payload)
