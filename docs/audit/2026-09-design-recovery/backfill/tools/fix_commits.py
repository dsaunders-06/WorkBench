"""Audit, error-log back-fill: every commit whose message records a fix or a correction.

Read-only. Runs `git log` in the repository; writes one CSV (a derived list,
no personal data) to the path given.

    python fix_commits.py <repo_root> <out.csv>

Every line of QAT's code and documents was written by Claude, so a commit that
fixes something records a Claude error, found at that commit. The error
itself entered earlier. Each commit is tagged with the cues its message
carries:
  fix      - fix, bug, defect, broken, wrong, regression, repair
  retract  - retract, revert, undo, superseded, "was not"
  correct  - correct, correction, misread, misstated, mislabel
  live     - a cue that the fault reached a live session: live, broker, IBKR
             rejected, kill switch, trip, phantom, orphan, unprotected
  docs     - the commit touches only docs/ (a written claim, not code)

The tags are a sort, not a verdict. The CSV is the back-fill's starting
inventory; each High or Medium error is then read in full.
"""

from __future__ import annotations

import csv
import re
import subprocess  # nosec B404 - read-only git log on the local repository
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

AEST = timezone(timedelta(hours=10))
SEP = "\x1f"  # between the fields of one commit
START = "\x1e"  # before each commit's record
FILES = "\x1d"  # after the message; git's --name-only list follows it

CUES = {
    "fix": r"\b(fix(es|ed)?|bug|defect|broken|wrong|regression|repair(s|ed)?)\b",
    "retract": r"\b(retract(ed|s|ion)?|revert(ed|s)?|undo|superseded|was not)\b",
    "correct": r"\b(correct(s|ed|ion)?|misread|misstat\w*|mislabel\w*)\b",
    "live": r"\b(live|broker|rejected|kill[- ]switch|trip(s|ped)?|phantom|orphan\w*|unprotected)\b",
}
MILESTONE = re.compile(r"\bM(\d{1,3}[a-z]?)\b")


def main(root: Path, out: Path) -> None:
    fmt = START + SEP.join(["%H", "%h", "%aI", "%s", "%b"]) + FILES
    text = subprocess.run(  # nosec B603 B607 - fixed arguments, local git
        ["git", "-C", str(root), "log", "--reverse", f"--format={fmt}", "--name-only"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    rows = []
    records = [c for c in text.split(START) if c.strip()]
    for chunk in records:
        head, _, files_part = chunk.partition(FILES)
        fields = head.split(SEP)
        if len(fields) < 5:
            continue
        full, short, date, subject, body = fields[0], fields[1], fields[2], fields[3], fields[4]
        files = [f for f in files_part.splitlines() if f.strip()]
        message = f"{subject}\n{body}"
        tags = [name for name, rx in CUES.items() if re.search(rx, message, re.I)]
        if files and all(f.startswith("docs/") for f in files):
            tags.append("docs")
        if not any(t in tags for t in ("fix", "retract", "correct")):
            continue
        when = datetime.fromisoformat(date).astimezone(AEST)
        milestone = MILESTONE.search(subject)
        rows.append(
            {
                "date_aest": when.strftime("%Y-%m-%d %H:%M"),
                "commit": short,
                "milestone": f"M{milestone.group(1)}" if milestone else "",
                "tags": " ".join(tags),
                "src_files": sum(1 for f in files if f.startswith("src/")),
                "subject": subject,
                "full": full,
            }
        )
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"commits scanned {len(records)}; with a fix, retraction or correction cue: {len(rows)}")
    by_tag: dict[str, int] = {}
    for r in rows:
        for t in r["tags"].split():
            by_tag[t] = by_tag.get(t, 0) + 1
    print("by tag: " + ", ".join(f"{k} {v}" for k, v in sorted(by_tag.items())))
    by_month: dict[str, int] = {}
    for r in rows:
        key = r["date_aest"][:10]
        by_month[key] = by_month.get(key, 0) + 1
    print("by day: " + ", ".join(f"{k[5:]} {v}" for k, v in sorted(by_month.items())))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
