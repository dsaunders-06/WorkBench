"""Live view of a running session, for watching an open (M38 tooling).

The log is one JSON object per line, which is right for machine reading and
useless at 13:30 when something is going wrong and you have minutes to decide
whether to intervene. On 3 August the first failure landed 83 seconds after
the bell and repeated 1,413 times; nothing on any screen said so.

    python scripts/watch_session.py

Follows the live log and prints one short line per event that matters, with a
running tally. Read-only - it opens the log for reading and touches nothing
else, so it cannot affect the session it is watching.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

# The usage line above is `python scripts/watch_session.py`, and until 26 August
# that command did not work: `qat` lives under src/ and is importable only from
# an interpreter it has been installed into, so a bare `python` answered
# `ModuleNotFoundError: No module named 'qat'`. Nine sibling scripts already
# carry this line - preflight, ibkr_probe, flatten_positions and the rest - and
# the one tool an operator reaches for WHILE a session is running was the one
# without it. Nothing here needs a third-party package, so with src on the path
# any interpreter can run it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.domain.display_dates import format_session_time  # noqa: E402

# What to surface, and how to label it. Ordered: the first pattern that matches
# a message wins, so the specific sits above the general.
_RULES: tuple[tuple[str, str], ...] = (
    # First, because it identifies the build every line below it came from.
    # The operator is told to check the stamp at the open, and until 6 August
    # the watcher filtered out the only line carrying it - so the check could
    # only be done by reading qat.log separately, which defeats the point of
    # having a live view at all.
    ("Build: ", "BUILD"),
    # Immediately after the stamp, because it changes how the PREVIOUS
    # session's log should be read (M57c). A log that simply stops is
    # otherwise identical to a quiet session, which is where M56a hid.
    ("ended WITHOUT reaching its shutdown", "LOSTRUN"),
    ("shutdown reached normally", "STOPPED"),
    # Above the generic rule, because it is the line that explains the one
    # below it. Without this the watcher printed "Trading session started - US
    # is open" on its own and the operator had no way to see that the open was
    # forced rather than reached - which is exactly what happened on 5 August.
    ("force-started by operator", "FORCED"),
    ("Trading session started", "SESSION"),
    ("Trading session stood down", "SESSION"),
    ("REGIME ", "REGIME"),
    ("regime engine has published nothing", "REGIME"),
    ("REGIME ENGINE NOT CLASSIFYING", "REGIME"),
    ("BROKER-SIDE FILL", "CLOSED"),
    # Startup evidence that M49 and M50 wired up (added 5 August). These are
    # INFO and match no other rule, so the three lines the operator was told to
    # watch for would not have appeared at all.
    ("Broker-fill watermark restored", "RESTORE"),
    # The AGE warning, which is a different line from the restore above and is
    # the one that says whether this run will replay a long window - and that
    # fills from the app's own pre-restart orders will read as FOREIGN.
    ("watermark is", "RESTORE"),
    ("open lot(s) to the trade ledger", "RESTORE"),
    ("closed trade(s) from", "RESTORE"),
    # Whether this session can trade without asking. It is logged once, at
    # startup, at WARNING, and it was not surfaced at all.
    ("AUTONOMOUS EXECUTION IS ENABLED", "AUTO"),
    ("Replayed ", "REPLAY"),
    ("Protective OCO resting", "PROTECT"),
    ("Protective stop resting", "PROTECT"),
    ("Protective OCO proposed", "PROTECT"),
    ("POSITION UNPROTECTED", "NAKED"),
    # ⚠️ WAS `"carries a stop resting"` AND MATCHED NOTHING, EVER. `oms.py:961`
    # logs "%d of %d carry a stop resting" - plural, always, because it is a
    # count. So the one line naming every adopted position and how many of them
    # are protected has been invisible in the live view since the rule was
    # written. Anchored on the phrase that identifies the event rather than on
    # a verb that can agree with a number.
    ("pre-existing broker position", "ADOPT"),
    # The heartbeat that proves the scan RAN. Item 34 was a reconciliation poll
    # wedged silently - 3 scans in a day against 78 - and nothing on any screen
    # said so. One line per 300s is the price of never repeating that.
    ("RESTING ORDER SCAN", "SCAN"),
    # Item 59: quarantines are restored at startup and cleared only by hand, and
    # a quarantined symbol cannot be entered. Both halves matter, and they
    # differ only in the leading capital, so the needle starts after it.
    ("-order quarantine", "QUARANTINE"),
    ("reconciliation mismatch", "RECONCILE"),
    ("KILL-SWITCH TRIPPED", "KILL"),
    ("Kill-switch active", "KILL"),
    # ⚠️ THE line for item 56. It carries the order id the app registered, and
    # the whole before/after of M148 is whether that id is a NUMERIC permId or
    # a UUID. `Autonomy signed off` below names the same id, so this is not the
    # only sighting - but this is the one whose wording says "transmitted", and
    # on the day the fix is first exercised it should not depend on a sibling.
    ("signed off and transmitted", "TRANSMIT"),
    # Item 56's SECOND, independent confirmation: it cannot appear unless the
    # identity bridge resolved. Absence proves nothing - it is suppressed inside
    # the price tolerance - so it is evidence one way only.
    ("Corrected the recorded entry price", "PRICEFIX"),
    ("Autonomy signed off", "SIGNED"),
    ("Autonomy blocked", "BLOCKED"),
    ("awaiting sign-off", "PROPOSED"),
    ("risk evaluation failed", "REJECTED"),
    ("duplicate timestamp", "DUPLICATE"),
    ("EventBus handler failed", "CRASH"),
    ("MARKET DATA DOWN", "FEED"),
    # ⚠️ M119's THREE lines, and none of them was surfaced. Its whole purpose is
    # surviving the open: before it, five empty 60s polls ENDED the stream
    # permanently and the account sat flat and blind on an open market until it
    # was restarted by hand. Yahoo publishes ASX intraday ~20 minutes late, so
    # every poll from the bell lands inside the delay window.
    #
    # "has recovered" is the SUCCESS signal and the only positive evidence M119
    # worked. It is WARNING, it fires exactly once per outage, and it matched no
    # rule - so the live view would have been silent about the one thing the
    # 10:00 open exists to test.
    #
    # Bounded, checked in `yfinance_source.py:243-271` rather than assumed: the
    # empty-poll warning fires at most `max_consecutive_failures - 1` times per
    # outage, then the loop goes quiet and backs off.
    ("yfinance market data has recovered", "FEED"),
    ("market data is down", "FEED"),
    ("produced no ticks", "FEED"),
    # The rail that decides whether an entry is possible at all. On 27 August it
    # sat at 5.03% against a 5.00% cap - blocking every entry - and said so only
    # in qat.log, every 300s, where the live view never looked.
    ("Aggregate risk-at-stop", "AGGRISK"),
    ("could not be fetched", "MACRO"),
    ("TIME STOP", "TIMESTOP"),
    ("Turnover budget", "BUDGET"),
)

# Counted but not printed line by line - these arrive in the hundreds.
_QUIET = {"SIGNAL"}


def _classify(message: str, level: str) -> str | None:
    for needle, label in _RULES:
        if needle in message:
            return label
    if level in {"ERROR", "CRITICAL"}:
        return "ERROR"
    return None


def _default_log() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "QuantAdvisoryTerminal" / "data" / "logs" / "qat.log"


def _event_time(ts: object) -> str:
    """The event's own time, in the market's zone and NAMED (item 40).

    This was `str(ts)[11:19]` - a raw slice of the log's UTC-with-offset `ts`,
    which threw the offset away and printed a bare UTC clock with no zone. An
    08:43:40 AEST event rendered as `22:43:40`, ten hours out and nothing on
    the line to say so.

    That is precisely the failure item 40 was written about: *read 03:21:34 off
    it at 13:21 AEST and a ten-hour error lands in the middle of an incident,
    which is the only time anyone reads it.* M144 converted every human-facing
    time - including the tally line **in this same file**, twenty lines below -
    and missed this one. One of two printers in one file, which is the sibling
    check that habit exists for.

    Falls back to the raw slice rather than raising. A monitoring tool that
    dies on a malformed line is worse than one showing an awkward timestamp,
    and this runs unattended for a whole session.
    """
    text = str(ts or "")
    try:
        return format_session_time(datetime.fromisoformat(text))
    except (TypeError, ValueError):
        return text[11:19]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, default=_default_log())
    parser.add_argument(
        "--from-start",
        action="store_true",
        help="replay the whole file rather than following from the end",
    )
    parser.add_argument("--summary-every", type=int, default=60, help="tally interval, seconds")
    parser.add_argument(
        "--no-follow",
        action="store_true",
        help="stop at the end of the file instead of waiting - for reviewing a finished session",
    )
    args = parser.parse_args()

    if not args.log.exists():
        print(f"No log at {args.log}")
        return 1

    print(f"watching {args.log}")
    print("  Ctrl-C to stop.  Blank means nothing worth reporting.\n")

    tally: Counter[str] = Counter()
    last_summary = time.monotonic()

    # POLLED, never held open, and that is a correctness requirement rather
    # than a style choice (24 August 2026).
    #
    # This used to be `with args.log.open(...)` around the whole loop, holding
    # the file for the watcher's entire run. On Windows a plain open() does not
    # grant delete-sharing, so `RotatingFileHandler.doRollover()`'s os.rename
    # fails with WinError 32 - and the handler's rollover leaves `stream=None`
    # and swallows the error, so THE APPLICATION'S LOG STOPS FOR EVER, silently.
    #
    # It happened live: the log froze at 5,242,781 bytes - 99 short of the
    # 5 MiB cap - at 10:06:27 on Monday's open, and stayed frozen across a full
    # application restart, because this process still held the handle. The tool
    # whose only purpose is to watch a session is what blinded it, and it went
    # on displaying nothing while doing so.
    #
    # Opening per poll costs one syscall every 0.4s and cannot lock anything.
    offset = 0
    if not args.from_start and args.log.exists():
        offset = args.log.stat().st_size

    def _read_new() -> list[str]:
        """New lines since `offset`, reopening each time so nothing is held.

        A file SHORTER than the offset has been rotated out from under us, so
        the offset restarts at zero rather than seeking past the end of the new
        file and going quiet - which would reproduce the very blindness this
        function was rewritten to prevent.
        """
        nonlocal offset
        try:
            size = args.log.stat().st_size
        except OSError:
            return []
        if size < offset:
            offset = 0
        if size == offset:
            return []
        with args.log.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            lines = handle.readlines()
            offset = handle.tell()
        return lines

    pending: list[str] = []
    while True:
        if not pending:
            pending = _read_new()
        line = pending.pop(0) if pending else ""
        if not line:
            if args.no_follow:
                if tally:
                    parts = ", ".join(f"{k} {v}" for k, v in sorted(tally.items()))
                    print("")
                    print(f"  totals: {parts}")
                return 0
            now = time.monotonic()
            if tally and now - last_summary >= args.summary_every:
                parts = ", ".join(f"{k} {v}" for k, v in sorted(tally.items()))
                # Item 40. This printed a bare UTC clock with NO zone label into the
                # live console an operator reads during a session. Read
                # 03:21:34 off it at 13:21 AEST, correlate against the
                # Blotter or your own watch, and a ten-hour error lands in
                # the middle of an incident.
                print(f"    -- {format_session_time(datetime.now(UTC))} tally: {parts}")
                last_summary = now
            time.sleep(0.4)
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue

        message = str(event.get("message", ""))
        label = _classify(message, str(event.get("level", "")))
        if label is None:
            continue
        tally[label] += 1
        if label in _QUIET:
            continue

        stamp = _event_time(event.get("ts"))
        # The traceback is the point on a crash, and noise everywhere else.
        detail = message.strip().replace("\n", " ")
        if label == "CRASH":
            exc = str(event.get("exc_info", "")).strip().splitlines()
            if exc:
                detail = f"{detail} | {exc[-1][:100]}"
        print(f"  {stamp}  {label:<9} {detail[:150]}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nstopped")
