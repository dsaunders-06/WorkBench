"""Audit, error-log back-fill: every CE entry, placed in the period its error entered.

Read-only. Reads docs/CLAUDE_ERROR_LOG.md; prints a markdown table and the
counts by period and severity.

    python error_log_table.py <repo_root>

"Entered" is the first date in the entry's Made line. Where the Made line
names the first build instead of a date (`fa9ba47`, "the first build"), it
is placed there. Where it names neither, the entry is placed by the date it
was found, and the table marks it "(found)".
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

PERIODS = [
    (date(2026, 7, 24), date(2026, 7, 31), "1 first builds (24-31 Jul)"),
    (date(2026, 8, 1), date(2026, 8, 18), "2 US-era hardening (1-18 Aug)"),
    (date(2026, 8, 19), date(2026, 8, 23), "3 ASX move (19-23 Aug)"),
    (date(2026, 8, 24), date(2026, 9, 11), "4 live ASX (24 Aug-11 Sep)"),
    (date(2026, 9, 12), date(2026, 9, 30), "5 M175 and the audit (12-15 Sep)"),
]
MONTHS = {"jul": 7, "aug": 8, "sep": 9}

# Entries whose Made line names a mechanism, not a date, dated here from the
# commit that introduced the mechanism (git log -S / --grep, run 15 Sep).
# Kept in the tool, not written into the entries: the log's rule is that an
# entry is never edited after the fact.
ENTERED = {
    "CE-003": (date(2026, 7, 25), "fa9ba47: _IB_STATUS_MAP, first build"),
    "CE-005": (date(2026, 7, 25), "fa9ba47: booking at sign-off, first build (R7 #42)"),
    "CE-039": (date(2026, 8, 5), "3ac992e: M50, fills recorded after downtime"),
    "CE-040": (date(2026, 8, 19), "fbce78d: M97, recent_fills on IBKR"),
    "CE-041": (date(2026, 7, 26), "ab1ba97: OMS.pending_orders"),
    "CE-048": (date(2026, 8, 19), "40274fa: M95, the IBKR order builders"),
    "CE-049": (date(2026, 7, 31), "9b9fa50: M27b, eligibility gate"),
    "CE-050": (date(2026, 8, 27), "7f3efe3: M151"),
    "CE-057": (date(2026, 8, 30), "85b4c02: the footer's rewrite"),
    "CE-066": (date(2026, 8, 5), "3ac992e: M50 replay; the warning is from ab1ba97"),
}
DATE = re.compile(r"\b(\d{1,2})(?:[–-]\d{1,2})?\s+(Jul|Aug|Sep)\w*", re.I)
FIRST_BUILD = re.compile(r"first build|fa9ba47", re.I)


def period_of(d: date) -> str:
    for start, end, name in PERIODS:
        if start <= d <= end:
            return name
    return "?"


def main(root: Path) -> None:
    text = (root / "docs" / "CLAUDE_ERROR_LOG.md").read_text(encoding="utf-8")
    entries = re.split(r"(?m)^### (?=CE-\d+)", text)[1:]
    rows = []
    for body in entries:
        head = body.splitlines()[0]
        ce, _, title = head.partition(": ")
        made = re.search(r"\*\*Made[^*]*\*\*(.*?)(?=\n\* \*\*|\Z)", body, re.S)
        made_text = " ".join(made.group(1).split()) if made else ""
        sev = re.search(r"\*\*Severity:\*\*\s*(\w+)", body)
        severity = sev.group(1) if sev else "?"
        found_only = False
        m = DATE.search(made_text.split("**Found")[0])
        if ce in ENTERED:
            entered = period_of(ENTERED[ce][0])
        elif m:
            entered = period_of(date(2026, MONTHS[m.group(2).lower()[:3]], int(m.group(1))))
        elif FIRST_BUILD.search(made_text):
            entered = PERIODS[0][2]
        else:
            m = DATE.search(made_text)
            entered = (
                period_of(date(2026, MONTHS[m.group(2).lower()[:3]], int(m.group(1)))) if m else "?"
            )
            found_only = True
        rows.append((entered, ce, severity, title, found_only))

    rows.sort(key=lambda r: (r[0], int(r[1][3:])))
    print("| Period entered | Entry | Severity | Error |")
    print("|---|---|---|---|")
    for entered, ce, severity, title, found_only in rows:
        mark = " (found)" if found_only else ""
        mark += f" [{ENTERED[ce][1]}]" if ce in ENTERED else ""
        print(f"| {entered[2:]}{mark} | {ce} | {severity} | {title} |")
    print()
    by_period = Counter(r[0] for r in rows)
    sev_by_period: dict[str, Counter] = {}
    for entered, _, severity, _, _ in rows:
        sev_by_period.setdefault(entered, Counter())[severity] += 1
    print(f"entries: {len(rows)}")
    for name in [p[2] for p in PERIODS] + ["?"]:
        if by_period.get(name):
            sev = ", ".join(f"{k} {v}" for k, v in sorted(sev_by_period[name].items()))
            print(f"  {name}: {by_period[name]} ({sev})")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
