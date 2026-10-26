"""Conservative classification of broker protection before any restoration.

The unfiltered account-wide order book is the input. A stop in PendingCancel,
an unowned identity, or any other possible sell blocks a second stop.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from qat.data.broker.adapter import Position, RestingOrder
from qat.domain.market_calendar import is_trading_day
from qat.domain.oms.resting_orders import TERMINAL_STATUSES


@dataclass(frozen=True, slots=True)
class ProtectionAssessment:
    state: Literal["protected", "restore", "wait", "manual"]
    reason: str
    missing_role: str | None = None


@dataclass(frozen=True, slots=True)
class ApprovedStopLeg:
    role: str
    quantity: float
    stop_price: float
    order_ref: str = ""
    perm_id: int = 0
    oca_group: str | None = None
    target_order_ref: str = ""
    target_perm_id: int = 0
    target_price: float | None = None


@dataclass(frozen=True, slots=True)
class ApprovedEntryPlan:
    order_id: str
    operator: str
    stop_price: float
    opened_at: datetime
    legs: tuple[ApprovedStopLeg, ...]


class ProtectionLegLineage:
    """Confirmed replacement identities, separate from immutable DS approval."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> dict[str, dict[str, object]]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or any(not isinstance(item, dict) for item in raw.values()):
            raise ValueError("protection leg lineage is invalid")
        return raw

    def effective_legs(self, symbol: str, plan: ApprovedEntryPlan) -> tuple[ApprovedStopLeg, ...]:
        records = self._load()
        effective: list[ApprovedStopLeg] = []
        for leg in plan.legs:
            record = records.get(f"{symbol}:{leg.role}")
            if record is None:
                effective.append(leg)
                continue
            if (
                record.get("approval_order_id") != plan.order_id
                or record.get("original_order_ref") != leg.order_ref
                or record.get("quantity") != leg.quantity
                or record.get("stop_price") != leg.stop_price
                or record.get("oca_group") != leg.oca_group
                or record.get("target_order_ref") != leg.target_order_ref
                or record.get("target_perm_id") != leg.target_perm_id
                or record.get("target_price") != leg.target_price
            ):
                raise ValueError("restored leg does not match original approval")
            ref = record.get("current_order_ref")
            perm = record.get("current_perm_id")
            if not isinstance(ref, str) or not ref or not isinstance(perm, int) or perm <= 0:
                raise ValueError("restored leg identity is invalid")
            effective.append(replace(leg, order_ref=ref, perm_id=perm))
        return tuple(effective)

    def record(
        self,
        symbol: str,
        plan: ApprovedEntryPlan,
        leg: ApprovedStopLeg,
        confirmed: RestingOrder,
    ) -> None:
        if (
            confirmed.symbol != symbol
            or not confirmed.order_ref
            or confirmed.perm_id <= 0
            or confirmed.stop_price is None
            or not math.isclose(confirmed.stop_price, leg.stop_price, abs_tol=1e-6)
            or not math.isclose(confirmed.quantity, leg.quantity, abs_tol=1e-6)
            or confirmed.oca_group != leg.oca_group
        ):
            raise ValueError("replacement leg is not broker-confirmed at approved terms")
        original = next((item for item in plan.legs if item.role == leg.role), None)
        if original is None:
            raise ValueError("replacement leg has no original approval")
        records = self._load()
        records[f"{symbol}:{leg.role}"] = {
            "approval_order_id": plan.order_id,
            "original_order_ref": original.order_ref,
            "current_order_ref": confirmed.order_ref,
            "current_perm_id": confirmed.perm_id,
            "quantity": leg.quantity,
            "stop_price": leg.stop_price,
            "oca_group": leg.oca_group,
            "target_order_ref": leg.target_order_ref,
            "target_perm_id": leg.target_perm_id,
            "target_price": leg.target_price,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.tmp-{os.getpid()}")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(records, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise


def approved_entry_plan(
    data_dir: Path,
    journal_rows: Sequence[dict[str, str]],
    position: Position,
    *,
    operator_name: str,
) -> ApprovedEntryPlan | None:
    """Use only an entry plan whose original named sign-off is on the record."""
    path = data_dir / "open_position_entries.json"
    if not path.exists() or not operator_name.strip():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("position entry store is invalid")
    entry = raw.get(position.symbol)
    if not isinstance(entry, dict):
        return None
    order_id = entry.get("order_id")
    try:
        quantity = float(str(entry.get("quantity")))
        stop_price = float(str(entry.get("stop_price")))
        opened_at = datetime.fromisoformat(str(entry.get("opened_at")))
    except (TypeError, ValueError):
        return None
    if (
        not isinstance(order_id, str)
        or not order_id
        or not math.isfinite(quantity)
        or quantity + 1e-6 < position.quantity
        or not math.isfinite(stop_price)
        or stop_price <= 0
        or opened_at.tzinfo is None
        or opened_at.utcoffset() is None
    ):
        return None
    if not any(
        row.get("order_id") == order_id
        and row.get("outcome") == "signed_off"
        and row.get("entity_name") == operator_name.strip()
        for row in journal_rows
    ):
        return None
    # SignalToOrderBridge owns open_position_entries.json and rewrites each
    # row on fills. Card-leg approval lives in a separate file so a bridge
    # save cannot silently erase the two-stop plan. The entry identity pins
    # it to this exact signed entry rather than a later holding of the symbol.
    leg_path = data_dir / "approved_protection_legs.json"
    raw_legs = None
    if leg_path.exists():
        card_plans = json.loads(leg_path.read_text(encoding="utf-8"))
        if not isinstance(card_plans, dict):
            raise ValueError("approved protection leg store is invalid")
        card_plan = card_plans.get(position.symbol)
        if card_plan is not None:
            if (
                not isinstance(card_plan, dict)
                or card_plan.get("entry_order_id") != order_id
                or not isinstance(card_plan.get("legs"), list)
            ):
                return None
            raw_legs = card_plan.get("legs")
    legs: tuple[ApprovedStopLeg, ...]
    if raw_legs is None:
        legs = (ApprovedStopLeg("primary", position.quantity, stop_price),)
    else:
        if not isinstance(raw_legs, list) or not raw_legs:
            return None
        try:
            legs = tuple(
                ApprovedStopLeg(
                    role=str(item["role"]),
                    quantity=float(str(item["quantity"])),
                    stop_price=float(str(item["stop_price"])),
                    order_ref=str(item["order_ref"]),
                    perm_id=int(str(item["perm_id"])),
                    oca_group=str(item["oca_group"]) if item.get("oca_group") else None,
                    target_order_ref=str(item.get("target_order_ref") or ""),
                    target_perm_id=int(str(item.get("target_perm_id") or 0)),
                    target_price=(
                        float(str(item["target_price"]))
                        if item.get("target_price") is not None
                        else None
                    ),
                )
                for item in raw_legs
            )
        except (TypeError, ValueError, KeyError):
            return None
        if (
            len({leg.role for leg in legs}) != len(legs)
            or any(
                not leg.role
                or not leg.order_ref
                or leg.perm_id <= 0
                or not math.isfinite(leg.quantity)
                or leg.quantity <= 0
                or not math.isfinite(leg.stop_price)
                or leg.stop_price <= 0
                or (
                    leg.oca_group is not None
                    and (
                        not leg.target_order_ref
                        or leg.target_perm_id <= 0
                        or leg.target_price is None
                        or not math.isfinite(leg.target_price)
                        or leg.target_price <= 0
                    )
                )
                for leg in legs
            )
            or not math.isclose(
                sum(leg.quantity for leg in legs), position.quantity, rel_tol=0, abs_tol=1e-6
            )
        ):
            return None
    return ApprovedEntryPlan(order_id, operator_name.strip(), stop_price, opened_at, legs)


def corporate_action_warnings(
    actions: object, positions: Sequence[Position], today: date
) -> list[str]:
    """Warn about held names with a split/dividend by the next ASX session."""
    next_session = today + timedelta(days=1)
    while not is_trading_day("ASX", next_session):
        next_session += timedelta(days=1)
    held = {position.symbol for position in positions if position.quantity > 0}
    warnings: list[str] = []
    for action in actions.events:  # type: ignore[attr-defined]
        if (
            action.symbol in held
            and today <= action.ex_session <= next_session
            and (
                action.split_ratio.numerator != action.split_ratio.denominator
                or action.dividend > 0
            )
        ):
            warnings.append(
                f"{action.symbol} {action.ex_session.isoformat()}: "
                "split/dividend may cancel its stop"
            )
    return warnings


def assess_protection(
    position: Position,
    orders: Sequence[RestingOrder],
    *,
    approved_stop_price: float | None = None,
    approved_legs: Sequence[ApprovedStopLeg] | None = None,
    owns_order: Callable[[RestingOrder], bool],
    pending_identity: bool = False,
) -> ProtectionAssessment:
    """A restore verdict means a *complete* broker scan found no possible leg.

    The caller must still repeat the broker read under the sign-off lock before
    the existing recovery path can transmit anything.
    """
    if not position.qat_holding or position.quantity <= 0:
        return ProtectionAssessment("manual", "not a held QAT long")
    legs = (
        tuple(approved_legs)
        if approved_legs is not None
        else (
            (ApprovedStopLeg("primary", position.quantity, approved_stop_price),)
            if approved_stop_price is not None
            else ()
        )
    )
    if (
        not legs
        or len({leg.role for leg in legs}) != len(legs)
        or any(
            not leg.role
            or not math.isfinite(leg.quantity)
            or leg.quantity <= 0
            or not math.isfinite(leg.stop_price)
            or leg.stop_price <= 0
            for leg in legs
        )
        or not math.isclose(
            sum(leg.quantity for leg in legs), position.quantity, rel_tol=0, abs_tol=1e-6
        )
        or (len(legs) > 1 and any(not leg.order_ref or not leg.perm_id for leg in legs))
        or (
            len(legs) > 1
            and any(
                leg.oca_group
                and (not leg.target_order_ref or not leg.target_perm_id or leg.target_price is None)
                for leg in legs
            )
        )
    ):
        return ProtectionAssessment("wait", "approved stop plan unavailable")
    if pending_identity:
        return ProtectionAssessment("wait", "broker leg identity is unresolved")
    possible = [
        order
        for order in orders
        if order.symbol == position.symbol and order.status not in TERMINAL_STATUSES
    ]
    stops = [
        order
        for order in possible
        if order.side.lower() == "sell" and order.order_type.upper() == "STP"
    ]
    if len(stops) > len(legs):
        return ProtectionAssessment("wait", "duplicate or other working leg may sell")
    matches: dict[str, RestingOrder] = {}
    for stop in stops:
        remaining = stop.quantity if stop.quantity > 0 else stop.total_quantity
        candidates = [
            leg
            for leg in legs
            if math.isclose(remaining, leg.quantity, rel_tol=0, abs_tol=1e-6)
            and stop.stop_price is not None
            and math.isclose(stop.stop_price, leg.stop_price, rel_tol=0, abs_tol=1e-6)
            and (stop.oca_group == leg.oca_group or (len(legs) == 1 and leg.oca_group is None))
            and (not leg.order_ref or stop.order_ref == leg.order_ref)
            and (not leg.perm_id or stop.perm_id == leg.perm_id)
        ]
        if (
            len(candidates) != 1
            or candidates[0].role in matches
            or stop.status not in {"Submitted", "PreSubmitted"}
            or stop.tif.upper() != "GTC"
            or (stop.oca_group is not None and stop.oca_type != 1)
            or not stop.perm_id
            or not stop.order_ref
            or not owns_order(stop)
        ):
            return ProtectionAssessment(
                "wait", "stop status, identity, quantity or price is unverified"
            )
        matches[candidates[0].role] = stop
    partners = [order for order in possible if order not in stops]
    for partner in partners:
        remaining = partner.quantity if partner.quantity > 0 else partner.total_quantity
        approved = [
            leg
            for leg in legs
            if partner.oca_group
            and (
                leg.oca_group == partner.oca_group
                or (
                    len(legs) == 1
                    and leg.oca_group is None
                    and leg.role in matches
                    and matches[leg.role].oca_group == partner.oca_group
                )
            )
            and (
                (
                    leg.target_order_ref == partner.order_ref
                    and leg.target_perm_id == partner.perm_id
                    and leg.target_price is not None
                    and partner.limit_price is not None
                    and math.isclose(leg.target_price, partner.limit_price, abs_tol=1e-6)
                )
                or (len(legs) == 1 and not leg.target_order_ref and leg.role in matches)
            )
            and math.isclose(remaining, leg.quantity, rel_tol=0, abs_tol=1e-6)
        ]
        if (
            len(approved) != 1
            or partner.side.lower() != "sell"
            or partner.order_type.upper() not in {"LMT", "LIMIT"}
            or partner.status not in {"Submitted", "PreSubmitted"}
            or partner.tif.upper() != "GTC"
            or partner.oca_type != 1
            or not owns_order(partner)
        ):
            return ProtectionAssessment("wait", "other working leg is not a proven OCA target")
    missing = [leg for leg in legs if leg.role not in matches]
    if not missing:
        return ProtectionAssessment("protected", "all approved QAT stops are working")
    # A complete empty book confirms each leg absent. Restore the first one,
    # then require a fresh reconciliation before considering the next leg.
    # The durable recovery record permits only one submission at a time.
    return ProtectionAssessment(
        "restore", f"broker confirms approved {missing[0].role} stop is missing", missing[0].role
    )
