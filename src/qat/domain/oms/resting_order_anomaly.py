"""A symbol carrying resting orders the book cannot justify (M141, item 23).

Deliberately NOT `PositionAnomalyStore`, and the reason is worth the file.

That store binds an anomaly to `broker_quantity`, and its `explains()` then
tells `check_reconciliation` a position divergence at that quantity is
accounted for - suppressing the kill-switch trip. Quarantining a FLAT symbol
through it (`broker_quantity=0.0`) would grant that symbol immunity from the
position-reconciliation halt at broker=0: precisely the rail that caught the
real mismatch on 24 August.

So item 23's fix would have partly disabled item 27's - the M31a shape, two
individually correct decisions combining into a defect. This store has no
`explains` method at all, so it cannot participate in that question, and a test
asserts the absence so re-adding one fails the suite.

**This contains damage; it does not repair it.** A quarantined symbol stays
quarantined until the orders are dealt with and somebody clears it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_FILENAME = "resting_order_anomalies.json"


@dataclass(frozen=True, slots=True)
class RestingOrderAnomaly:
    symbol: str
    reason: str
    declared_by: str
    declared_at: datetime
    excess: float


class RestingOrderAnomalyStore:
    """Active resting-order quarantines, persisted so a restart cannot erase
    them.

    Persistence is the point rather than a convenience: the 24 August orphans
    were INHERITED across a restart, so a quarantine that dies with the process
    is a quarantine that is never in force when it is needed.
    """

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self._path = Path(data_dir) / _FILENAME if data_dir is not None else None
        self._active: dict[str, RestingOrderAnomaly] = {}
        self._load()

    def declare(
        self, *, symbol: str, reason: str, declared_by: str, excess: float
    ) -> RestingOrderAnomaly:
        """Declares (or re-declares) one symbol's quarantine.

        `declared_at` is PRESERVED across a re-declare of a symbol already
        present (I5, final review). With cancelling off - the default - the
        scan calls this on every poll for as long as a divergence stays
        unresolved, and stamping a fresh timestamp each time would make the
        file say the orphans were "declared" a moment ago on their seventy-
        eighth re-detection, losing the one fact an operator arriving mid-day
        actually needs: how long has this been resting. `excess` and `reason`
        still update, because those DO change as legs fill or cancel.
        """
        existing = self._active.get(symbol)
        anomaly = RestingOrderAnomaly(
            symbol=symbol,
            reason=reason,
            declared_by=declared_by,
            declared_at=existing.declared_at if existing is not None else datetime.now(UTC),
            excess=excess,
        )
        self._active[symbol] = anomaly
        logger.warning(
            "RESTING ORDER QUARANTINE on %s by %s: %g shares of resting risk the book does "
            "not justify - %s. New entries in this symbol are refused until it is cleared. "
            "The ORDERS ARE NOT CANCELLED by this.",
            symbol,
            declared_by,
            excess,
            reason,
        )
        self._save()
        return anomaly

    def clear(self, symbol: str, operator: str) -> bool:
        """Releases a symbol. Returns False if it was not quarantined."""
        anomaly = self._active.pop(symbol, None)
        if anomaly is None:
            return False
        logger.warning(
            "Resting-order quarantine on %s cleared by %s (was: %s) - ordinary order flow "
            "resumes for this symbol",
            symbol,
            operator,
            anomaly.reason,
        )
        self._save()
        return True

    def get(self, symbol: str) -> RestingOrderAnomaly | None:
        return self._active.get(symbol)

    def is_quarantined(self, symbol: str) -> bool:
        return symbol in self._active

    def active(self) -> list[RestingOrderAnomaly]:
        return sorted(self._active.values(), key=lambda a: a.symbol)

    def _load(self) -> None:
        """No file, or an unreadable one, means nothing is quarantined - the
        WRONG direction, so it is logged at ERROR rather than swallowed. Still
        better than refusing to start: an application that will not launch
        protects nothing at all.
        """
        if self._path is None or not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._active = {
                str(entry["symbol"]): RestingOrderAnomaly(
                    symbol=str(entry["symbol"]),
                    reason=str(entry["reason"]),
                    declared_by=str(entry["declared_by"]),
                    declared_at=datetime.fromisoformat(entry["declared_at"]),
                    excess=float(entry["excess"]),
                )
                for entry in (raw.get("anomalies") or [])
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.error(
                "Could not read %s (%s) - NO symbol is quarantined for resting orders this "
                "session. The scan will re-detect on its first poll.",
                self._path,
                exc,
            )
            self._active = {}
            return
        if self._active:
            logger.warning(
                "Restored %d resting-order quarantine(s) from %s: %s",
                len(self._active),
                self._path.name,
                ", ".join(sorted(self._active)),
            )

    def _save(self) -> None:
        """Written on every change, not at shutdown: the restart this exists for
        is the one nobody planned."""
        if self._path is None:
            return
        payload = {
            "anomalies": [
                {
                    "symbol": a.symbol,
                    "reason": a.reason,
                    "declared_by": a.declared_by,
                    "declared_at": a.declared_at.isoformat(),
                    "excess": a.excess,
                }
                for a in self.active()
            ]
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            logger.exception(
                "Could not write %s - the quarantine will not survive a restart", self._path
            )
