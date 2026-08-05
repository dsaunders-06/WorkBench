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
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

# What to surface, and how to label it. Ordered: the first pattern that matches
# a message wins, so the specific sits above the general.
_RULES: tuple[tuple[str, str], ...] = (
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
    ("open lot(s) to the trade ledger", "RESTORE"),
    ("closed trade(s) from", "RESTORE"),
    ("Replayed ", "REPLAY"),
    ("Protective OCO resting", "PROTECT"),
    ("Protective stop resting", "PROTECT"),
    ("Protective OCO proposed", "PROTECT"),
    ("POSITION UNPROTECTED", "NAKED"),
    ("carries a stop resting", "ADOPT"),
    ("reconciliation mismatch", "RECONCILE"),
    ("KILL-SWITCH TRIPPED", "KILL"),
    ("Kill-switch active", "KILL"),
    ("Autonomy signed off", "SIGNED"),
    ("Autonomy blocked", "BLOCKED"),
    ("awaiting sign-off", "PROPOSED"),
    ("risk evaluation failed", "REJECTED"),
    ("duplicate timestamp", "DUPLICATE"),
    ("EventBus handler failed", "CRASH"),
    ("MARKET DATA DOWN", "FEED"),
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

    with args.log.open("r", encoding="utf-8", errors="replace") as handle:
        if not args.from_start:
            handle.seek(0, os.SEEK_END)
        while True:
            line = handle.readline()
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
                    print(f"    -- {datetime.now(UTC):%H:%M:%S} tally: {parts}")
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

            stamp = str(event.get("ts", ""))[11:19]
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
