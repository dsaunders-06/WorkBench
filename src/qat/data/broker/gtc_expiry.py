"""Durable stop placement times and documented GTC expiry warnings."""

from __future__ import annotations

import json
import math
import os
from calendar import monthrange
from datetime import date, datetime, timedelta
from pathlib import Path

from qat.data.broker.adapter import RestingStopOrder
from qat.domain.market_calendar import ASX_TZ, is_trading_day


def expected_gtc_auto_cancel_date(placed_at: datetime) -> date:
    """Expected last ASX session of the quarter after placement/modification.

    IBKR Australia documents the scheduled end-of-following-quarter cancellation
    and a new Auto Expire date on modification:
    https://www.interactivebrokers.com.au/en/trading/ordertypes.php?m=hiddenModal
    Corporate actions, certain dividends, and other events can cancel sooner;
    this date is only an advance-warning estimate, never proof of protection.
    """
    if placed_at.tzinfo is None or placed_at.utcoffset() is None:
        raise ValueError("GTC placement time must include a timezone")
    local = placed_at.astimezone(ASX_TZ)
    quarter = (local.month - 1) // 3
    end_month = (quarter + 2) * 3
    end_year = local.year
    if end_month > 12:
        end_month -= 12
        end_year += 1
    end = date(end_year, end_month, monthrange(end_year, end_month)[1])
    while not is_trading_day("ASX", end):
        end -= timedelta(days=1)
    return end


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


class GtcExpiryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        if path.exists():
            stored = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(stored, dict) or not isinstance(stored.get("stops"), dict):
                raise ValueError("GTC expiry store is invalid")

    def _load(self) -> dict[str, object]:
        if not self.path.exists():
            return {
                "placements": {},
                "stops": {},
                "last_owned": {},
                "last_owned_by_ref": {},
                "pending_modifications": {},
            }
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("stops"), dict):
            raise ValueError("GTC expiry store is invalid")
        raw.setdefault("placements", {})
        raw.setdefault("last_owned", {})
        raw.setdefault("last_owned_by_ref", {})
        raw.setdefault("pending_modifications", {})
        if any(
            not isinstance(raw[key], dict)
            for key in ("placements", "last_owned", "last_owned_by_ref", "pending_modifications")
        ):
            raise ValueError("GTC placement journal is invalid")
        return raw

    def _save(self, payload: dict[str, object]) -> None:
        content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if self.path.exists() and self.path.read_text(encoding="utf-8") == content:
            return
        _atomic_json(self.path, payload)

    def mark_placed(self, order_ref: str, placed_at: datetime) -> None:
        if not order_ref or placed_at.tzinfo is None or placed_at.utcoffset() is None:
            raise ValueError("GTC placement requires an order reference and aware time")
        payload = self._load()
        placements = payload["placements"]
        if not isinstance(placements, dict):
            raise ValueError("GTC placement journal is invalid")
        placements.setdefault(order_ref, placed_at.astimezone(ASX_TZ).isoformat())
        self._save(payload)

    def mark_modification_submitted(
        self, order_ref: str, stop_price: float, quantity: float, submitted_at: datetime
    ) -> None:
        """Keep the original expiry until a later broker scan proves new terms."""
        if (
            not order_ref
            or not math.isfinite(stop_price)
            or stop_price <= 0
            or not math.isfinite(quantity)
            or quantity <= 0
            or submitted_at.tzinfo is None
            or submitted_at.utcoffset() is None
        ):
            raise ValueError("invalid GTC modification intent")
        payload = self._load()
        pending = payload["pending_modifications"]
        if not isinstance(pending, dict):
            raise ValueError("GTC modification journal is invalid")
        pending[order_ref] = {
            "stop_price": stop_price,
            "quantity": quantity,
            "submitted_at": submitted_at.astimezone(ASX_TZ).isoformat(),
        }
        self._save(payload)

    def record(
        self,
        stops: list[RestingStopOrder],
        *,
        owned_stops: list[RestingStopOrder] | None = None,
        observed_at: datetime | None = None,
    ) -> None:
        observed = observed_at or datetime.now(ASX_TZ)
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("GTC observation time must include a timezone")
        payload = self._load()
        previous = payload["stops"]
        placements = payload["placements"]
        pending = payload["pending_modifications"]
        if (
            not isinstance(previous, dict)
            or not isinstance(placements, dict)
            or not isinstance(pending, dict)
        ):
            raise ValueError("GTC expiry store is invalid")
        current: dict[str, dict[str, object]] = {}
        for stop in sorted(stops, key=lambda item: item.order_id):
            key = stop.order_id
            old = previous.get(key, {})
            if not isinstance(old, dict):
                old = {}
            change = pending.get(stop.order_ref) if stop.order_ref else None
            if (
                isinstance(change, dict)
                and old
                and (old.get("stop_price"), old.get("quantity")) != (stop.stop_price, stop.quantity)
                and change.get("stop_price") == stop.stop_price
                and change.get("quantity") == stop.quantity
            ):
                placements[stop.order_ref] = change["submitted_at"]
                pending.pop(stop.order_ref, None)
            placed_at = placements.get(stop.order_ref) if stop.order_ref else None
            expected = (
                expected_gtc_auto_cancel_date(datetime.fromisoformat(str(placed_at))).isoformat()
                if placed_at
                else None
            )
            current[key] = {
                "symbol": stop.symbol,
                "order_id": stop.order_id,
                "order_ref": stop.order_ref,
                "stop_price": stop.stop_price,
                "quantity": stop.quantity,
                # Historical IBKR field retained for evidence, never used for a decision.
                "auto_cancel_date": (
                    stop.auto_cancel_date.isoformat() if stop.auto_cancel_date else None
                ),
                "placed_at": placed_at,
                "first_seen_at": (
                    old.get("first_seen_at") or observed.astimezone(ASX_TZ).isoformat()
                ),
                "expected_auto_cancel_date": expected,
                "last_alert_date": old.get("last_alert_date"),
            }
        payload["stops"] = current
        if owned_stops is not None:
            last_owned = payload["last_owned"]
            by_ref = payload["last_owned_by_ref"]
            if not isinstance(last_owned, dict) or not isinstance(by_ref, dict):
                raise ValueError("GTC ownership journal is invalid")
            by_symbol: dict[str, list[RestingStopOrder]] = {}
            for stop in owned_stops:
                by_symbol.setdefault(stop.symbol, []).append(stop)
                if stop.order_ref:
                    by_ref[stop.order_ref] = {
                        "symbol": stop.symbol,
                        "order_id": stop.order_id,
                        "order_ref": stop.order_ref,
                        "stop_price": stop.stop_price,
                        "quantity": stop.quantity,
                        "seen_at": observed.astimezone(ASX_TZ).isoformat(),
                    }
            for symbol, matches in by_symbol.items():
                if len(matches) == 1 and matches[0].order_ref:
                    stop = matches[0]
                    last_owned[symbol] = {
                        "order_id": stop.order_id,
                        "order_ref": stop.order_ref,
                        "stop_price": stop.stop_price,
                        "quantity": stop.quantity,
                        "seen_at": observed.astimezone(ASX_TZ).isoformat(),
                    }
        self._save(payload)

    def last_owned_stop(
        self, symbol: str, order_ref: str | None = None
    ) -> dict[str, object] | None:
        last_owned = self._load()["last_owned_by_ref" if order_ref else "last_owned"]
        if not isinstance(last_owned, dict):
            raise ValueError("GTC ownership journal is invalid")
        record = last_owned.get(order_ref or symbol)
        return (
            record
            if isinstance(record, dict) and (not order_ref or record.get("symbol") == symbol)
            else None
        )

    def active_alerts(self, today: date) -> list[dict[str, object]]:
        """Persistent warnings; unknown placement age is urgent from first sight."""
        stops = self._load()["stops"]
        if not isinstance(stops, dict):
            raise ValueError("GTC expiry store is invalid")
        return self._active_alerts_in(stops, today)

    @staticmethod
    def _active_alerts_in(stops: dict[str, object], today: date) -> list[dict[str, object]]:
        due: list[dict[str, object]] = []
        for record in stops.values():
            if not isinstance(record, dict):
                continue
            expected = record.get("expected_auto_cancel_date")
            if expected is None or today >= date.fromisoformat(str(expected)) - timedelta(days=30):
                due.append(record)
        return due

    def due_alerts(self, today: date) -> list[dict[str, object]]:
        payload = self._load()
        stops = payload["stops"]
        if not isinstance(stops, dict):
            raise ValueError("GTC expiry store is invalid")
        due = [
            item
            for item in self._active_alerts_in(stops, today)
            if item.get("last_alert_date") != today.isoformat()
        ]
        if due:
            for item in due:
                item["last_alert_date"] = today.isoformat()
            self._save(payload)
        return due
