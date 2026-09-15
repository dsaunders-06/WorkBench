"""Audit, the development chronology: drift, errors and milestones on one timeline.

Read-only. Reads the drift map (07-design-drift-map.md), the error log and
`git log`; prints per-period counts and the dated drift items.

    python chronology.py <repo_root>

Periods (AEST):
  0 before QAT       to 24 Jul   claude.ai chats, the reference app, the paper
  1 first builds     24-31 Jul   fa9ba47, autonomy (ab1ba97), M27
  2 US-era hardening 1-18 Aug    the US paper trial
  3 ASX move         19-23 Aug   IBKR, ASX, yfinance
  4 live ASX         24 Aug-11 Sep   the first orders to the last session
  5 M175 and audit   12-15 Sep

A drift item is dated by the first commit its "Introduced" cell names
(resolved with git), else by the first date written in the cell. Items
the cell calls "never built" or "absent since" the first commit are placed
in period 1, because that is where the absence began. Error entries are
placed by `backfill/tools/error_log_table.py`'s rule.
"""

from __future__ import annotations

import re
import subprocess  # nosec B404 - read-only git calls on the local repository
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backfill" / "tools"))
import error_log_table as elt  # noqa: E402

PERIODS = [
    (date(2026, 7, 1), date(2026, 7, 23), "0 before QAT (to 23 Jul)"),
    (date(2026, 7, 24), date(2026, 7, 31), "1 first builds (24-31 Jul)"),
    (date(2026, 8, 1), date(2026, 8, 18), "2 US-era hardening (1-18 Aug)"),
    (date(2026, 8, 19), date(2026, 8, 23), "3 ASX move (19-23 Aug)"),
    (date(2026, 8, 24), date(2026, 9, 11), "4 live ASX (24 Aug-11 Sep)"),
    (date(2026, 9, 12), date(2026, 9, 30), "5 M175 and the audit (12-15 Sep)"),
]
MONTHS = {"jul": 7, "aug": 8, "sep": 9}
HASH = re.compile(r"`([0-9a-f]{7})`")
DATE = re.compile(r"\b(\d{1,2})\s+(Jul|Aug|Sep)\b", re.I)


def period_of(d: date) -> str:
    for start, end, name in PERIODS:
        if start <= d <= end:
            return name
    return "?"


def git(root: Path, *args: str) -> str:
    return subprocess.run(  # nosec B603 B607 - fixed arguments, local git
        ["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8"
    ).stdout.strip()


def commit_date(root: Path, sha: str) -> date | None:
    out = git(root, "show", "-s", "--format=%ad", "--date=format:%Y-%m-%d", sha)
    return date.fromisoformat(out) if out else None


def drift_items(root: Path) -> list[dict]:
    text = (root / "docs/audit/2026-09-design-recovery/07-design-drift-map.md").read_text(
        encoding="utf-8"
    )
    items = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 9 or not cells[1].isdigit():
            continue
        num, comp, _, introduced, _, authority, klass, risk = cells[1:9]
        when = None
        m = HASH.search(introduced)
        if m:
            when = commit_date(root, m.group(1))
        if when is None:
            d = DATE.search(introduced)
            if d:
                when = date(2026, MONTHS[d.group(2).lower()], int(d.group(1)))
        if when is None and re.search(r"never built|absent", introduced, re.I):
            when = date(2026, 7, 25)
        auth = re.search(r"\*\*(OD|AP/OA|AO|U)\b", authority)
        cls = re.search(r"\*\*([A-G])\*\*", klass)
        items.append(
            {
                "num": int(num),
                "component": re.sub(r"\*\*", "", comp),
                "date": when,
                "period": period_of(when) if when else "?",
                "authority": auth.group(1) if auth else "?",
                "class": cls.group(1) if cls else "?",
                "risk": re.sub(r"\*\*", "", risk).split(":")[0].split(" ")[0],
            }
        )
    return items


def milestones(root: Path) -> dict[str, date]:
    first: dict[str, date] = {}
    log = git(root, "log", "--reverse", "--format=%ad %s", "--date=format:%Y-%m-%d")
    for line in log.splitlines():
        day, _, subject = line.partition(" ")
        for m in re.finditer(r"\bM(\d{1,3})\b", subject):
            first.setdefault(m.group(1), date.fromisoformat(day))
    return first


def main(root: Path) -> None:
    items = drift_items(root)
    print(f"=== DRIFT ITEMS (R7): {len(items)}")
    by_period: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_period[it["period"]].append(it)
    for name in [p[2] for p in PERIODS] + ["?"]:
        group = by_period.get(name, [])
        if not group:
            continue
        auth = Counter(i["authority"] for i in group)
        cls = Counter(i["class"] for i in group)
        high = [i["num"] for i in group if i["risk"].startswith("H")]
        print(
            f"{name}: {len(group)} items; authority {dict(auth)}; class {dict(cls)}; "
            f"rated H: {high}"
        )
        for i in sorted(group, key=lambda x: (x["date"] or date.max, x["num"])):
            stamp = i["date"].strftime("%d %b") if i["date"] else "  ?   "
            print(
                f"    {stamp}  #{i['num']:<3d} {i['authority']:6s} {i['class']}  "
                f"{i['risk']:4s} {i['component'][:70]}"
            )
    print()

    # A subject often names an OLDER milestone ("the sibling M167 left"), so a
    # count of milestones "first named" in a period is inflated. The highest
    # number first named in each period is the reliable measure of progress.
    ms = milestones(root)
    print("=== MILESTONES: the highest milestone number first named in each period")
    for name in [p[2] for p in PERIODS]:
        in_period = [int(k) for k, d in ms.items() if period_of(d) == name]
        print(f"{name}: {'M' + str(max(in_period)) if in_period else '-'}")
    print()

    print("=== COMMITS per period (all)")
    for start, end, name in PERIODS:
        n = git(
            root,
            "rev-list",
            "--count",
            f"--since={start.isoformat()} 00:00 +1000",
            f"--until={end.isoformat()} 23:59 +1000",
            "HEAD",
        )
        print(f"{name}: {n}")
    print()
    print("=== ERROR-LOG ENTRIES by period entered (error_log_table.py's rule)")
    elt.main(root)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
