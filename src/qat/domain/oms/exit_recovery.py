"""Durable intent for protection QAT is about to remove during an exit.

An uncertain transmission is deliberately not retried: absence from one broker
read cannot prove that an unacknowledged order was never accepted.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Literal

RecoveryStage = Literal["prepared", "uncertain", "working"]


@dataclass(frozen=True)
class ExitRecovery:
    symbol: str
    quantity: float
    stop_price: float | None
    stage: RecoveryStage = "prepared"
    other_orders_present: bool = False
    # Watchdog restorations cite the original entry sign-off; old recovery
    # records remain readable with these fields absent.
    approval_order_id: str | None = None
    approval_operator: str | None = None
    # A multi-stop card plan restores only one missing approved leg. The
    # sibling references are a snapshot; any change before submission halts.
    leg_role: str | None = None
    leg_quantity: float | None = None
    leg_oca_group: str | None = None
    permitted_order_refs: tuple[str, ...] = ()
    previous_order_ref: str | None = None
    replacement_order_ref: str | None = None
    replacement_app_order_id: str | None = None


class ExitRecoveryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.plans: dict[str, ExitRecovery] = {}
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            for symbol, data in raw.items():
                if "permitted_order_refs" in data:
                    data = {**data, "permitted_order_refs": tuple(data["permitted_order_refs"])}
                plan = ExitRecovery(**data)
                if (
                    symbol != plan.symbol
                    or not math.isfinite(plan.quantity)
                    or plan.quantity <= 0
                    or (
                        plan.stop_price is not None
                        and (not math.isfinite(plan.stop_price) or plan.stop_price <= 0)
                    )
                    or plan.stage not in {"prepared", "uncertain", "working"}
                    or (
                        plan.leg_role is not None
                        and (
                            not plan.leg_role
                            or plan.leg_quantity is None
                            or not math.isfinite(plan.leg_quantity)
                            or plan.leg_quantity <= 0
                            or plan.leg_quantity > plan.quantity
                            or not plan.previous_order_ref
                            or len(set(plan.permitted_order_refs)) != len(plan.permitted_order_refs)
                        )
                    )
                ):
                    raise ValueError("invalid exit recovery record")
                self.plans[symbol] = plan

    def _save(self, plans: dict[str, ExitRecovery]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump({symbol: asdict(plan) for symbol, plan in plans.items()}, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(self.path)
        self.plans = plans

    def put(self, plan: ExitRecovery) -> None:
        self._save({**self.plans, plan.symbol: plan})

    def stage(self, symbol: str, stage: RecoveryStage) -> None:
        if symbol in self.plans:
            self.put(replace(self.plans[symbol], stage=stage))

    def replacement(self, symbol: str, app_order_id: str, order_ref: str) -> None:
        if symbol in self.plans:
            self.put(
                replace(
                    self.plans[symbol],
                    replacement_app_order_id=app_order_id,
                    replacement_order_ref=order_ref,
                    stage="uncertain",
                )
            )

    def remove(self, symbol: str) -> None:
        self._save({key: value for key, value in self.plans.items() if key != symbol})


@dataclass(frozen=True)
class ExitAttempt:
    """Operator-facing facts for one sign-off attempt; not a recovery journal."""

    issued: tuple[str, ...] = ()
    cancelled: tuple[str, ...] = ()
