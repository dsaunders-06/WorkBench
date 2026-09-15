"""Audit, error-log back-fill: where Claude's own records admit an error.

Read-only. Reads docs/HANDOFF.md, docs/archive/HANDOFF-2026-08-20-superseded.md
and ROADMAP.md; prints to stdout.

    python doc_incidents.py <repo_root>

HANDOFF and ROADMAP were written by Claude and are claims, not evidence
(CE-018). What they are good for here is an index: every place the writer
itself recorded that something it did was wrong. Each hit is then checked
against a commit, a log line or a transcript before it becomes an entry.

A hit is a markdown heading carrying a warning marker, or any line with an
admission cue ("retracted", "was wrong", "corrected", "my error", ...).
Headings give the date section they fall under, so each hit is dated.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DOCS = (
    "docs/HANDOFF.md",
    "docs/archive/HANDOFF-2026-08-20-superseded.md",
    "ROADMAP.md",
)
ADMISSION = re.compile(
    r"\b(retract(ed|ion)?|was wrong|were wrong|is wrong|wrong\b.*\b(claim|figure|diagnosis)|"
    r"corrected|my (error|mistake)|i was wrong|misread|misdiagnos\w*|vacuous|"
    r"did not land|non-landing|escaped|false positive|phantom|never (ran|run|reached|asked))\b",
    re.I,
)
HEADING = re.compile(r"^(#{1,4})\s+(.*)")
DATE = re.compile(
    r"\b(\d{1,2})\s+(JULY|AUGUST|SEPTEMBER|July|August|September|Jul|Aug|Sep)\b|\b(M\d{2,3})\b"
)


def main(root: Path) -> None:
    for rel in DOCS:
        path = root / rel
        if not path.exists():
            print(f"=== {rel}: not found")
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        section = ""
        headings = admissions = 0
        print(f"=== {rel} ({len(lines)} lines)")
        for n, line in enumerate(lines, 1):
            h = HEADING.match(line)
            if h:
                if DATE.search(h.group(2)):
                    section = h.group(2)[:70]
                if "⚠" in h.group(2) or "❌" in h.group(2) or ADMISSION.search(h.group(2)):
                    headings += 1
                    print(f"  H {n:5d} [{section[:40]}] {h.group(2)[:110]}")
                continue
            if ADMISSION.search(line):
                admissions += 1
                print(f"  L {n:5d} [{section[:40]}] {line.strip()[:110]}")
        print(f"  -> {headings} warning headings, {admissions} admission lines\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
