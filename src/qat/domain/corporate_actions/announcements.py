"""What the broker says is coming, remembered across restarts (M39).

**Deduped on `(symbol, ex_date)`**, not on the record id and never on a count.
Alpaca returned the same MNST announcement once on the Saturday and twice on the
Monday, byte-identical, and the difference was the `payable_date` arriving. A
detector reading a changing count as a changing action would adjust the same
position twice.

**Persisted**, because the query can fail on exactly the morning it matters. A
stop that has to be halved before the open cannot wait for the next successful
poll, and the announcement was knowable days earlier.

`ex_date` is the key throughout. `payable_date` is carried for the record only:
CRWD's are 1 and 2 July, so the payable date can PRECEDE the ex-date, and keying
on it would act a day early or not at all.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_FILENAME = "corporate_announcements.json"


@dataclass(frozen=True, slots=True)
class Announcement:
    """One corporate action the broker has published.

    `ratio` is `new_rate / old_rate`, which is how Alpaca expresses it: a forward
    split is `old_rate=1.0, new_rate=4.0` and a reverse split inverts it. So 2.0
    is a 2-for-1 and 0.001 is a 1-for-1000.
    """

    symbol: str
    ex_date: date
    ratio: float
    action_id: str
    payable_date: date | None
    fetched_at: datetime

    @property
    def key(self) -> tuple[str, date]:
        """The identity of the ACTION, as distinct from the identity of the
        record describing it. Two records for one split share this."""
        return (self.symbol, self.ex_date)


class AnnouncementStore:
    """Announcements seen so far, deduped and persisted.

    A store built with no data directory keeps everything in memory. That is for
    tests and for a monitor constructed without settings; it is not a supported
    production configuration, because the persistence is the point.
    """

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self._path = Path(data_dir) / _FILENAME if data_dir is not None else None
        self._known: dict[tuple[str, date], Announcement] = {}
        self._load()

    def remember(self, announcements: Iterable[Announcement]) -> list[Announcement]:
        """Stores any that are new, and returns only those.

        Returning just the new ones is what lets a caller log "first seen" at
        WARNING without re-announcing the same split on every sweep - a warning
        that fires every five minutes stops being read.
        """
        fresh = [a for a in announcements if a.key not in self._known]
        if not fresh:
            return []
        for announcement in fresh:
            self._known[announcement.key] = announcement
        self._save()
        return fresh

    def for_symbol(self, symbol: str) -> list[Announcement]:
        return sorted(
            (a for a in self._known.values() if a.symbol == symbol),
            key=lambda a: a.ex_date,
        )

    def all(self) -> list[Announcement]:
        return sorted(self._known.values(), key=lambda a: (a.symbol, a.ex_date))

    def _load(self) -> None:
        """An unreadable file reads as "nothing known", logged at ERROR because
        that is the WRONG direction: it means no split is known about this
        session, which is the state this file exists to prevent."""
        if self._path is None or not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for entry in raw.get("announcements") or []:
                announcement = Announcement(
                    symbol=str(entry["symbol"]),
                    ex_date=date.fromisoformat(entry["ex_date"]),
                    ratio=float(entry["ratio"]),
                    action_id=str(entry["action_id"]),
                    payable_date=(
                        date.fromisoformat(entry["payable_date"])
                        if entry.get("payable_date")
                        else None
                    ),
                    fetched_at=datetime.fromisoformat(entry["fetched_at"]),
                )
                self._known[announcement.key] = announcement
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.error(
                "Could not read %s (%s) - NO corporate action is known about this session. "
                "A split on a held position will not be detected until a query succeeds.",
                self._path,
                exc,
            )
            self._known = {}
            return
        if self._known:
            logger.info(
                "Restored %d corporate announcement(s) from %s: %s",
                len(self._known),
                self._path.name,
                ", ".join(f"{a.symbol} {a.ex_date}" for a in self.all()),
            )

    def _save(self) -> None:
        """Written on every change rather than at shutdown, for the reason every
        other store in this application is: the restart nobody planned."""
        if self._path is None:
            return
        payload = {
            "announcements": [
                {
                    "symbol": a.symbol,
                    "ex_date": a.ex_date.isoformat(),
                    "ratio": a.ratio,
                    "action_id": a.action_id,
                    "payable_date": a.payable_date.isoformat() if a.payable_date else None,
                    "fetched_at": a.fetched_at.isoformat(),
                }
                for a in self.all()
            ]
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            logger.exception(
                "Could not write %s - announcements will not survive a restart", self._path
            )
