"""Durable identity for each leg sent to IBKR.

The order reference is an application-owned UUID. A zero permId leaves the
leg pending: it is evidence of delayed acknowledgement, never rejection.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from uuid import UUID, uuid5

# Fixed namespace: changing it would change broker orderRef values on replay.
LEG_NAMESPACE = UUID("c843db81-14ca-55fd-bae5-c7b56b6cffaa")


def _uuid_shaped(value: str) -> bool:
    try:
        parsed = UUID(value)
    except ValueError:
        return False
    return value in (parsed.hex, str(parsed))


def leg_order_ref(app_order_id: str, role: str) -> str:
    """Stable UUIDv5 for an application order's particular broker leg."""
    if role == "primary" and _uuid_shaped(app_order_id):
        return app_order_id
    return str(uuid5(LEG_NAMESPACE, f"{app_order_id}:{role}"))


@dataclass(frozen=True, slots=True)
class PendingLeg:
    app_order_id: str
    symbol: str
    role: str
    account: str
    con_id: int
    order_ref: str
    client_id: int
    broker_order_id: int = 0
    perm_id: int = 0
    resolved: bool = False


class PendingLegStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.legs: dict[str, PendingLeg] = {}
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            for item in raw.get("legs", []):
                leg = PendingLeg(**item)
                if not _uuid_shaped(leg.order_ref):
                    raise ValueError("invalid durable leg orderRef")
                if leg.order_ref in self.legs:
                    raise ValueError("duplicate durable leg orderRef")
                self.legs[leg.order_ref] = leg

    def _save(self, legs: dict[str, PendingLeg]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.tmp-{os.getpid()}")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump({"legs": [asdict(leg) for leg in legs.values()]}, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)
        self.legs = legs

    def begin(
        self,
        app_order_id: str,
        symbol: str,
        role: str,
        account: str,
        con_id: int,
        order_ref: str,
        client_id: int,
    ) -> None:
        if order_ref in self.legs:
            raise ValueError(f"leg {order_ref} already handed to broker")
        if not _uuid_shaped(order_ref):
            raise ValueError("orderRef must be UUID-shaped")
        leg = PendingLeg(app_order_id, symbol, role, account, con_id, order_ref, client_id)
        self._save({**self.legs, order_ref: leg})

    def observe(self, order_ref: str, *, broker_order_id: int = 0, perm_id: int = 0) -> None:
        leg = self.legs[order_ref]
        self._save(
            {
                **self.legs,
                order_ref: replace(
                    leg,
                    broker_order_id=broker_order_id or leg.broker_order_id,
                    perm_id=perm_id or leg.perm_id,
                    resolved=bool(perm_id or leg.perm_id),
                ),
            }
        )

    def resolve_match(
        self,
        order_ref: str,
        account: str,
        con_id: int,
        client_id: int,
        *,
        perm_id: int,
        broker_order_id: int = 0,
    ) -> bool:
        leg = self.legs.get(order_ref)
        if (
            leg is None
            or not perm_id
            or (leg.account, leg.con_id, leg.client_id) != (account, con_id, client_id)
        ):
            return False
        self.observe(order_ref, broker_order_id=broker_order_id, perm_id=perm_id)
        return True

    def unresolved(self, symbol: str) -> tuple[str, ...]:
        return tuple(
            leg.order_ref for leg in self.legs.values() if leg.symbol == symbol and not leg.resolved
        )

    def application_id_for(self, order_ref: str) -> str | None:
        leg = self.legs.get(order_ref)
        return leg.app_order_id if leg is not None else None
