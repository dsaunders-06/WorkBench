"""Durable identity and context for orders already handed to a broker.

Unsigned proposals do not belong here.  Restoring one would let a later
session approve stale sizing and risk evidence.  This store begins only after
the broker has accepted an order and preserves the application id alongside
the broker id used by later execution reports.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal, cast

from qat.data.broker.adapter import Order


@dataclass(frozen=True, slots=True)
class DurableOrderIdentity:
    app_order_id: str
    order: Order
    stage: Literal["transmitting", "accepted"] = "accepted"


class OrderIdentityStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.records: dict[str, DurableOrderIdentity] = {}
        if not path.exists():
            return
        raw = json.loads(path.read_text(encoding="utf-8"))
        for app_order_id, data in (raw.get("orders") or {}).items():
            order_data = dict(data["order"])
            order_data["created_at"] = datetime.fromisoformat(order_data["created_at"])
            if order_data.get("earnings_date") is not None:
                order_data["earnings_date"] = date.fromisoformat(order_data["earnings_date"])
            order = Order(**order_data)
            app_order_id = str(app_order_id)
            stage = str(data.get("stage", "accepted"))
            if (
                not app_order_id
                or not order.order_id
                or stage not in {"transmitting", "accepted"}
                or (stage == "accepted" and order.status == "pending_signoff")
                or not math.isfinite(order.quantity)
                or order.quantity <= 0
            ):
                raise ValueError("invalid durable order identity record")
            self.records[app_order_id] = DurableOrderIdentity(
                app_order_id, order, cast(Literal["transmitting", "accepted"], stage)
            )

    def _save(self, records: dict[str, DurableOrderIdentity]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.tmp-{os.getpid()}")
        orders: dict[str, object] = {}
        payload: dict[str, object] = {"orders": orders}
        for app_order_id, record in records.items():
            order = asdict(record.order)
            order["created_at"] = record.order.created_at.isoformat()
            order["earnings_date"] = (
                record.order.earnings_date.isoformat()
                if record.order.earnings_date is not None
                else None
            )
            orders[app_order_id] = {"stage": record.stage, "order": order}
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)
        self.records = records

    def put(
        self,
        app_order_id: str,
        order: Order,
        *,
        stage: Literal["transmitting", "accepted"] = "accepted",
    ) -> None:
        record = DurableOrderIdentity(app_order_id, Order(**asdict(order)), stage)
        self._save({**self.records, app_order_id: record})

    def remove(self, app_order_id: str) -> None:
        self._save({key: record for key, record in self.records.items() if key != app_order_id})
