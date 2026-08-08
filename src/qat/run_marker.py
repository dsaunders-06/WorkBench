"""Did the last run stop, or did it die (M57c)?

Nothing was written when the application exited, so an orderly close and a
silent death were the same thing in the log. That is the blind spot the M56a
crash hid in: it wrote its stamp, two restore lines, and then stopped - a
signature indistinguishable from the quiet session a full book is supposed to
produce, and one an operator had been primed to expect.

The mechanism is a file that exists only while the process is running. Startup
claims it, shutdown releases it, and a marker still present at the next startup
means the previous run never reached its shutdown path. It cannot distinguish a
crash from a power cut, and does not try to - the useful statement is "the last
run did not stop cleanly", and that is a statement the log could not make at
all.

Every operation here degrades to silence rather than raising. Losing this costs
the ability to tell those two apart; failing loudly would cost the session.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

MARKER_FILENAME = "session_running.json"


class RunMarker:
    def __init__(self, data_dir: str | Path, filename: str = MARKER_FILENAME) -> None:
        self.path = Path(data_dir) / filename

    def claim(self) -> dict[str, str] | None:
        """Records that a run has begun, and reports an unreleased predecessor.

        Returns the previous marker when one is still present - meaning that
        run never reached its shutdown - or None when the last run ended
        cleanly. A marker that cannot be parsed still counts as unreleased: its
        presence is the signal, and its contents are only detail.
        """
        previous = self._read()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(
                    {
                        "pid": str(os.getpid()),
                        "started_at": datetime.now(UTC).isoformat(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            logger.debug("Could not write the run marker at %s", self.path, exc_info=True)
        return previous

    def release(self) -> None:
        """Records that this run stopped on purpose."""
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            logger.debug("Could not remove the run marker at %s", self.path, exc_info=True)

    def _read(self) -> dict[str, str] | None:
        if not self.path.exists():
            return None
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Present but unreadable. Still an unreleased marker, which is the
            # part that matters - so say so rather than treating a damaged file
            # as evidence of a clean exit.
            return {}
        return loaded if isinstance(loaded, dict) else {}


def describe_previous_run(previous: dict[str, str] | None) -> str | None:
    """The warning to log when the last run left its marker behind."""
    if previous is None:
        return None
    started = previous.get("started_at")
    pid = previous.get("pid")
    detail = ""
    if started:
        detail = f" It started at {started}"
        if pid:
            detail += f" as pid {pid}"
        detail += "."
    return (
        "The previous run ended WITHOUT reaching its shutdown - it crashed, was killed, or the "
        "machine stopped." + detail + " Anything the log shows for that session ends where the "
        "process did, not where the session did."
    )


__all__ = ["MARKER_FILENAME", "RunMarker", "describe_previous_run"]
