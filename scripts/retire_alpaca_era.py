r"""Move the Alpaca/US trial out of the app's live record, into an offline archive.

    .\.venv\Scripts\python.exe scripts\retire_alpaca_era.py            # dry run
    .\.venv\Scripts\python.exe scripts\retire_alpaca_era.py --apply

RUN THIS UNDER POWERSHELL, NEVER BASH, and NEVER while the app is running. It
rewrites files `TradeLedger`, `EquityCurve` and `AuditLog` hold open and append
to. The script refuses if it finds the process.

**Operator decision, 21 August 2026: the app no longer needs the Alpaca data.**
That supersedes M122/M127, which LABELLED the two eras and left both in place so
the readers could scope past the old one. Scoping at every reader is the right
answer when both eras must stay; it is the wrong answer when one of them is
simply finished. Every reader that has to remember to filter is a reader that
can forget, and the weekly report of 21 August is what forgetting looks like: a
9.9x change of broker rendered as a "896.39% increase" with an LLM reasoning
about it as performance.

**Nothing is deleted.** The rows are written to an archive beside the repo's
other historical records, with their original headers, and the counts are
checked to add back up before the live files are rewritten. The US trial is the
only real evidence this system has ever produced about its own behaviour under
load - 1,598 staleness exclusions, 4,876 sizing decisions, five binding rails -
and it is worth keeping. It is just not worth CONSULTING at runtime.

**This retires the MNST question rather than answering it.** `closed_trades.csv`
holds a row with no strategy, no stop, and an exit at 45.9975 against an entry
of 91.1838 - an unadjusted split recorded as a stop-out, not a -375 loss.
M122's migration reported it and refused to rewrite it, because a migration has
no business adjudicating an outcome. Moving it offline means the app stops
counting it without anyone having to decide what it was.

THE CUTOVER. The IBKR/ASX account begins 2026-08-19; the equity curve steps
101,157.17 -> 1,003,733.21 between the 18th at 23:18 UTC and the 19th at 23:09.
Trades are partitioned on `closed_at`, not `opened_at`: a trade belongs to the
account that realised it. No trade in the live file straddles the boundary.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess  # nosec B404 - fixed argv, no shell, no untrusted input
import sys
from datetime import datetime
from pathlib import Path

CUTOVER = "2026-08-19"
CURRENT_MARKET = "ASX"
CURRENT_CURRENCY = "AUD"

# filename -> the column that decides which era a row belongs to.
FILES: dict[str, str] = {
    "closed_trades.csv": "closed_at",
    "equity_curve.csv": "ts",
    "risk_decisions.csv": "timestamp",
    "decision_journal.csv": "timestamp",
}

# The written reports. Sections are `## <date>`, and a section is retired when
# its window BEGINS before the cutover - not when it ends. A weekly report
# spanning 17-21 August was computed ACROSS the change of broker, which is
# precisely the one that rendered a 9.9x transfer as "a 896.39% increase" and
# had an LLM reason about it as performance. Keeping it because it ends on the
# ASX side would keep the worst one.
REPORTS = ("daily_reports.md", "weekly_reports.md")
_MONTH_NAMES = (
    "January February March April May June " "July August September October November December"
).split()
_MONTHS = {name.lower(): number for number, name in enumerate(_MONTH_NAMES, start=1)}


def app_is_running() -> bool:
    try:
        out = subprocess.run(  # nosec B603 B607 - fixed argv
            ["tasklist", "/FI", "IMAGENAME eq QuantAdvisoryTerminal.exe"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
    except OSError:
        return False
    return "QuantAdvisoryTerminal.exe" in out


def _label_current(row: dict[str, str], has_currency: bool) -> None:
    """Stamp a retained row with the era it belongs to.

    Necessary, not cosmetic. The ASX rows written before M127 carry no market,
    and `EquityCurve.points()` returns only the trailing run of rows sharing one
    label - so leaving them blank beside the M130-stamped ones would split the
    CURRENT account into two eras and silently drop the older half.
    """
    if not row.get("market"):
        row["market"] = CURRENT_MARKET
    if has_currency and not row.get("currency"):
        row["currency"] = CURRENT_CURRENCY


def retire(path: Path, ts_column: str, archive_dir: Path, apply: bool) -> bool:
    if not path.exists():
        print(f"\n{path.name}: not present, nothing to retire")
        return True

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    for column in ("market", "currency") if path.name == "closed_trades.csv" else ("market",):
        if column not in fieldnames:
            fieldnames.append(column)
    has_currency = "currency" in fieldnames

    retired = [r for r in rows if (r.get(ts_column) or "") < CUTOVER]
    kept = [r for r in rows if (r.get(ts_column) or "") >= CUTOVER]

    if len(retired) + len(kept) != len(rows):
        print(f"\n{path.name}: PARTITION LOST ROWS - refusing")
        return False

    for row in kept:
        _label_current(row, has_currency)

    print(
        f"\n{path.name}: {len(rows)} row(s) -> retire {len(retired)}, keep {len(kept)}"
        f" (labelled {CURRENT_MARKET})"
    )
    if not apply or not retired:
        return True

    archive_dir.mkdir(parents=True, exist_ok=True)
    archived = archive_dir / path.name
    with archived.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(retired)

    # Read the archive back and count it BEFORE touching the live file. An
    # archive that did not land is the one way this loses data.
    with archived.open(newline="", encoding="utf-8") as handle:
        written = len(list(csv.DictReader(handle)))
    if written != len(retired):
        print(
            f"  ARCHIVE MISMATCH: wrote {len(retired)}, read back {written} - live file UNTOUCHED"
        )
        return False

    backup = path.with_name(f"{path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(path, backup)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(kept)
    print(f"  archived -> {archived}")
    print(f"  backup   -> {backup.name}")
    return True


def _heading_date(heading: str) -> str | None:
    """The ISO date a `## ...` report section STARTS on, or None if unparseable.

    Handles "Monday 27 July 2026" and "Week of 27 Jul 2026 to 31 Jul 2026".
    Returns None rather than guessing: an unparseable heading is KEPT, because
    losing a report to a date format is worse than keeping one too many.
    """
    words = heading.replace("#", "").replace(",", "").split()
    for i, word in enumerate(words):
        month = _MONTHS.get(word.lower()) or _MONTHS.get(
            next((m for m in _MONTHS if m.startswith(word.lower())), ""), None
        )
        if month is None or i == 0 or i + 1 >= len(words):
            continue
        try:
            day, year = int(words[i - 1]), int(words[i + 1])
        except ValueError:
            continue
        return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def retire_report(path: Path, archive_dir: Path, apply: bool) -> bool:
    if not path.exists():
        print(f"\n{path.name}: not present, nothing to retire")
        return True

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    title: list[str] = []
    sections: list[tuple[str | None, list[str]]] = []
    for line in lines:
        if line.startswith("## "):
            sections.append((_heading_date(line), [line]))
        elif sections:
            sections[-1][1].append(line)
        else:
            title.append(line)

    retired = [s for s in sections if s[0] is not None and s[0] < CUTOVER]
    kept = [s for s in sections if s not in retired]
    unparsed = [s for s in sections if s[0] is None]

    print(f"\n{path.name}: {len(sections)} section(s) -> retire {len(retired)}, keep {len(kept)}")
    if unparsed:
        print(f"  {len(unparsed)} heading(s) unparseable - KEPT rather than guessed at")
    if not apply or not retired:
        return True

    archive_dir.mkdir(parents=True, exist_ok=True)
    archived = archive_dir / path.name
    archived.write_text(
        "".join(title) + "".join("".join(body) for _date, body in retired), encoding="utf-8"
    )
    backup = path.with_name(f"{path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(path, backup)
    path.write_text(
        "".join(title) + "".join("".join(body) for _date, body in kept), encoding="utf-8"
    )
    print(f"  archived -> {archived}")
    print(f"  backup   -> {backup.name}")
    return True


def retire_absorbed_fills(path: Path, archive_dir: Path, apply: bool) -> bool:
    """Clear the remembered fill ids, KEEP the watermark.

    The four remembered ids are Alpaca UUIDs from 5-11 August - two of them are
    the MNST entry and exit. They exist so a broker-side fill already recorded
    is not counted twice, and IBKR issues integer permIds, so an Alpaca UUID
    cannot reappear on this broker and these protect nothing.

    THE WATERMARK STAYS. It is current (21 August) and it is what stops the app
    replaying every execution since the account opened on the next start. That
    is live protection; the ids are not.
    """
    if not path.exists():
        print(f"\n{path.name}: not present")
        return True

    payload = json.loads(path.read_text(encoding="utf-8"))
    absorbed = payload.get("absorbed", {})
    print(f"\n{path.name}: {len(absorbed)} remembered fill(s) -> retire all, keep the watermark")
    if not apply or not absorbed:
        return True

    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / path.name).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    backup = path.with_name(f"{path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(path, backup)
    payload["absorbed"] = {}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"  archived -> {archive_dir / path.name}")
    print(f"  watermark kept: {payload.get('watermark')}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument(
        "--archive",
        default=r"C:\Claude Programming\docs\archive\alpaca-era",
        help="where the retired rows are written",
    )
    args = ap.parse_args()

    if args.apply and app_is_running():
        print("REFUSING: QuantAdvisoryTerminal.exe is running. Close it first.")
        return 1

    data = Path(os.environ["LOCALAPPDATA"]) / "QuantAdvisoryTerminal" / "data"
    archive_dir = Path(args.archive)
    print(f"live  : {data}")
    print(f"archive: {archive_dir}")
    print(f"cutover: rows before {CUTOVER} are retired")

    ok = True
    for filename, ts_column in FILES.items():
        ok = retire(data / filename, ts_column, archive_dir, args.apply) and ok
    for filename in REPORTS:
        ok = retire_report(data / filename, archive_dir, args.apply) and ok
    ok = retire_absorbed_fills(data / "absorbed_fills.json", archive_dir, args.apply) and ok

    if not ok:
        print("\nONE OR MORE FILES FAILED - see above. Nothing further was changed.")
        return 1
    if not args.apply:
        print("\nDRY RUN - nothing written. Re-run with --apply.")
    else:
        print("\nDone. session_check's closed_trades sha256 will change; that is expected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
