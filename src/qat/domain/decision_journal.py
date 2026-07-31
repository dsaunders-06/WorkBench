"""Append-only journal of every ORDER decision (spec M13, widened at M20).

Both halves matter, and the skipped half matters more. A journal of only the
orders that fired tells you what happened but not what the system decided -
you cannot tell a day with no qualifying setups from a day where the cash
floor blocked eleven of them, and those are completely different states of the
world. Every decision is written: executed, blocked, and why.

Written by the OMS in every execution mode, not only by the autonomous
executor. Until M20 this recorded autonomy decisions alone, which meant a
recommend-mode session - the default, and the one an operator actually runs
first - produced an empty file and no record of why anything was proposed or
refused. Moved out of domain/autonomy for the same reason: it stopped being
an autonomy concern.

CSV rather than the SQLite store, deliberately: this file is meant to be
opened in pandas or Excel during a post-mortem without the app running, and an
append-only text file survives a crashed process mid-write far better than a
database transaction does. Same reasoning the original ShareTrader app used
for autonomous_trade_journal.csv.
"""

from __future__ import annotations

import csv
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

JOURNAL_FILENAME = "decision_journal.csv"

_FIELDS = (
    "timestamp",
    "order_id",
    "symbol",
    "entity_name",
    "side",
    "quantity",
    "price",
    "strategy",
    "outcome",
    "reason",
    "market",
    "session_phase",
    "equity",
    "cash",
    "day_pnl_pct",
    "execution_mode",
)


@dataclass(frozen=True, slots=True)
class JournalEntry:
    order_id: str
    symbol: str
    side: str
    outcome: str
    reason: str
    entity_name: str = ""
    quantity: float = 0.0
    price: float | None = None
    strategy: str | None = None
    market: str = ""
    session_phase: str | None = None
    equity: float | None = None
    cash: float | None = None
    day_pnl_pct: float | None = None
    execution_mode: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))


class DecisionJournal:
    """Thread-safe append-only writer.

    A write failure is logged and swallowed rather than raised: losing a
    journal row is bad, but letting a disk error propagate into the execution
    path - where it could abort a sequence partway through - is worse. The
    caller's decision has already been made by the time this is called.
    """

    def __init__(self, data_dir: str | Path, filename: str = JOURNAL_FILENAME) -> None:
        self.path = Path(data_dir) / filename
        self._lock = threading.Lock()
        # The last unchanged verdict per symbol, so a rail that refuses the
        # same setup every minute is recorded once (M31b).
        self._last_verdict: dict[str, tuple[str, str]] = {}

    def _is_a_repeat(self, entry: JournalEntry) -> bool:
        """Whether this verdict is identical to the last one for this symbol.

        A strategy re-emits its signal on every tick, so a standing refusal is
        re-decided once a minute for as long as the setup holds. SPY was
        refused by the cost rail 249 times in one session - 249 of 262 rows,
        burying every real event under a decision that had not changed since
        the first one.

        Only a repeat of the SAME outcome and reason is dropped. A change
        either way is news and is always written, so the journal still shows
        when a refusal started and when it stopped.
        """
        verdict = (entry.outcome, entry.reason)
        if self._last_verdict.get(entry.symbol) == verdict:
            return True
        self._last_verdict[entry.symbol] = verdict
        return False

    def record(self, entry: JournalEntry) -> None:
        if self._is_a_repeat(entry):
            return
        row = asdict(entry)
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                is_new = not self.path.exists() or self.path.stat().st_size == 0
                with self.path.open("a", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=_FIELDS, extrasaction="ignore")
                    if is_new:
                        writer.writeheader()
                    writer.writerow(row)
        except OSError:
            logger.exception("Could not write the decision journal entry for %s", entry.order_id)

    def entries(self, limit: int | None = None) -> list[dict[str, str]]:
        """Reads the journal back, newest last. Returns an empty list when the
        journal does not exist yet - a fresh install is not an error."""
        if not self.path.exists():
            return []
        try:
            with self.path.open("r", newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
        except OSError:
            logger.exception("Could not read the decision journal at %s", self.path)
            return []
        return rows[-limit:] if limit else rows
