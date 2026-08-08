"""A held position in a state the ordinary path must not treat as ordinary.

Two things outside this application change a position it holds: a corporate
action changes the share count (M39), and a halt makes it unexitable (M43).
Both need the same two seams - reconciliation being able to be told a
difference is EXPLAINED, and the write path being able to be told a symbol is
not safe to act on. Built once, here, so the second one costs a producer
rather than a mechanism.

**This contains damage; it does not repair it.** A declared anomaly stays
quarantined until the underlying records are corrected by hand, as the CVS
ledger was on 6 August. Any screen rendering this must say so - "declared"
reading as "fixed" is the one failure this module could introduce.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_FILENAME = "position_anomalies.json"

# Share counts are whole numbers at every broker this app talks to, so this is
# a float-comparison guard rather than a real tolerance.
_QUANTITY_TOLERANCE = 1e-6


@dataclass(frozen=True, slots=True)
class PositionAnomaly:
    """One symbol, declared to be in a state nothing ordinary should act on.

    `broker_quantity` is not decoration. It is what the explanation is BOUND
    to: see `PositionAnomalyStore.explains`.
    """

    symbol: str
    reason: str
    declared_by: str
    declared_at: datetime
    tracked_quantity: float
    broker_quantity: float


class PositionAnomalyStore:
    """Active anomalies, persisted so a restart cannot erase them.

    Persistence is the point rather than a convenience. `adopt_broker_positions`
    reseeds tracked quantities wholesale from the broker at every launch, so a
    divergence VANISHES across a restart - tracked matches broker,
    reconciliation is content, and the entry record and ledger stay wrong. With
    an overnight session and a restart between each one, that is the normal
    path and not an edge case.

    A store built with no data directory keeps everything in memory. That is
    for tests and for an OMS constructed without settings; it is not a
    supported production configuration.
    """

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self._path = Path(data_dir) / _FILENAME if data_dir is not None else None
        self._active: dict[str, PositionAnomaly] = {}
        self._load()

    def declare(
        self,
        *,
        symbol: str,
        reason: str,
        declared_by: str,
        tracked_quantity: float,
        broker_quantity: float,
    ) -> PositionAnomaly:
        """Records that a difference on `symbol` is accounted for.

        WARNING rather than INFO, and it names both quantities. Declaring an
        anomaly suppresses a halt that would otherwise have happened, which is
        the most consequential thing an operator can tell this application.
        """
        anomaly = PositionAnomaly(
            symbol=symbol,
            reason=reason,
            declared_by=declared_by,
            declared_at=datetime.now(UTC),
            tracked_quantity=tracked_quantity,
            broker_quantity=broker_quantity,
        )
        self._active[symbol] = anomaly
        logger.warning(
            "POSITION ANOMALY DECLARED by %s: %s tracked=%g broker=%g - %s. New entries, "
            "de-lever trims and protection re-arming are refused for this symbol until it "
            "is cleared. The records are NOT corrected by this - that is still manual.",
            declared_by,
            symbol,
            tracked_quantity,
            broker_quantity,
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
            "Position anomaly on %s cleared by %s (was: %s) - ordinary order flow resumes "
            "for this symbol",
            symbol,
            operator,
            anomaly.reason,
        )
        self._save()
        return True

    def get(self, symbol: str) -> PositionAnomaly | None:
        return self._active.get(symbol)

    def is_quarantined(self, symbol: str) -> bool:
        return symbol in self._active

    def active(self) -> list[PositionAnomaly]:
        return sorted(self._active.values(), key=lambda a: a.symbol)

    def explains(self, symbol: str, broker_quantity: float) -> bool:
        """Whether a difference on `symbol` has already been accounted for.

        Bound to the quantity the broker reported when the anomaly was
        declared, and that binding IS the design. Without it, declaring a
        symbol explained once grants permanent immunity and the next genuine
        divergence passes in silence - the failure `adopt_broker_positions`
        already warns about, where an operator learns to ignore the one signal
        meaning "my view of the account cannot be trusted". A difference
        declared at 16-to-64 does not explain a later 64-to-128.

        Note this is a narrower question than `is_quarantined`. A position that
        moves again is no LESS suspect, so it stays quarantined while ceasing
        to be explained.
        """
        anomaly = self._active.get(symbol)
        if anomaly is None:
            return False
        return abs(anomaly.broker_quantity - broker_quantity) <= _QUANTITY_TOLERANCE

    def _load(self) -> None:
        """No file, no directory, or an unreadable one all mean "nothing is
        quarantined" - and that is the WRONG direction, so it is logged at
        ERROR rather than swallowed. It is still better than refusing to start:
        an application that will not launch protects nothing at all, and the
        reconciliation halt is still there to catch the divergence the hard
        way.
        """
        if self._path is None or not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._active = {
                str(entry["symbol"]): PositionAnomaly(
                    symbol=str(entry["symbol"]),
                    reason=str(entry["reason"]),
                    declared_by=str(entry["declared_by"]),
                    declared_at=datetime.fromisoformat(entry["declared_at"]),
                    tracked_quantity=float(entry["tracked_quantity"]),
                    broker_quantity=float(entry["broker_quantity"]),
                )
                for entry in (raw.get("anomalies") or [])
            }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.error(
                "Could not read %s (%s) - NOTHING is quarantined this session. Any position "
                "that was declared explained will halt reconciliation again instead.",
                self._path,
                exc,
            )
            self._active = {}
            return
        if self._active:
            logger.warning(
                "Restored %d quarantined position(s) from %s: %s",
                len(self._active),
                self._path.name,
                ", ".join(sorted(self._active)),
            )

    def _save(self) -> None:
        """Written on every change, not at shutdown: the restart this exists
        for is the one nobody planned."""
        if self._path is None:
            return
        payload = {
            "anomalies": [
                {
                    "symbol": a.symbol,
                    "reason": a.reason,
                    "declared_by": a.declared_by,
                    "declared_at": a.declared_at.isoformat(),
                    "tracked_quantity": a.tracked_quantity,
                    "broker_quantity": a.broker_quantity,
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
