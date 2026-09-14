"""Audit, brief §9: what the AI/LLM layer actually did live.

Read-only. Reads qat.log and its rotated files, and daily_reports.md and
weekly_reports.md from the data folder; writes nothing.

    python ai_evidence.py <data_dir>

<data_dir> is %LOCALAPPDATA%\\QuantAdvisoryTerminal\\data. Run from PowerShell
(HANDOFF, "THE ONE RULE").

Sections:
  1. launches, and which of them fell back to the demo engine because the local
     model was unreachable (runtime.py; the choice is made once per launch);
  2. AI Advisor requests (one "Advisory context for" line per question,
     advisory_account.py) and every logged AI failure;
  3. the report narratives: which reports carry "Analyst notes", and whether
     each is the model's text or the demo engine's canned notice. A report with
     no notes and no "Could not generate" line that day had an EMPTY narrative:
     reporter.py:261 drops it without logging.

The success of a request is not logged, only its context and its failure, so
section 2 counts questions asked, not answers received.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

AEST = timezone(timedelta(hours=10))

BUILD = re.compile(r"^Build: (M\d+)")
DEMO_FALLBACK = re.compile(r"^Local LLM at (\S+) is not reachable - using demo")
ASKED = re.compile(r"^Advisory context for (\S+): (\d+) position\(s\), (IS|NOT) held")
FAILURES = [
    ("AI Advisor request failed", r"^AI advisor request failed"),
    ("Workbench AI note failed", r"^AI robustness note failed|^AI .*note failed"),
    ("report narrative could not be generated", r"^Could not generate a report narrative"),
    ("macro matrix narrative disagreed with arithmetic", r"^The macro matrix narrative disagreed"),
    ("model returned figures for a matrix refusal", r"^The model returned change="),
]
DEMO_NOTICE = "[Demo mode - no real LLM configured]"


def records(logs: Path):
    files = sorted(
        logs.glob("qat.log*"), key=lambda p: -int(p.suffix[1:]) if p.suffix[1:].isdigit() else 0
    )
    for path in files:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                if raw.startswith("{"):
                    try:
                        yield json.loads(raw)
                    except json.JSONDecodeError:
                        continue


def section_log(logs: Path) -> None:
    launches: list[tuple[datetime, str]] = []
    # One line PER SLOT (runtime.py resolves general and sensitive separately),
    # so two lines are one launch. Keyed by launch index, not counted as lines.
    demo: dict[int, str] = {}
    asked: list[tuple[datetime, str, bool]] = []
    failures: Counter = Counter()
    failure_days: dict[str, set] = {}
    compiled = [(label, re.compile(p)) for label, p in FAILURES]
    for rec in records(logs):
        msg = rec.get("message", "")
        ts = datetime.fromisoformat(rec["ts"]).astimezone(AEST)
        if m := BUILD.match(msg):
            launches.append((ts, m.group(1)))
        elif m := DEMO_FALLBACK.match(msg):
            demo[len(launches) - 1] = m.group(1)
        elif m := ASKED.match(msg):
            asked.append((ts, m.group(1), m.group(3) == "IS"))
        else:
            for label, rx in compiled:
                if rx.match(msg):
                    failures[label] += 1
                    failure_days.setdefault(label, set()).add(ts.date())
                    break

    print("=== 1. LAUNCHES, AND THE DEMO FALLBACK ===")
    span = f"{launches[0][0]:%d %b} to {launches[-1][0]:%d %b}"
    print(f"launches (Build lines): {len(launches)}, {span}")
    print(f"launches that fell back to the demo engine (local model unreachable): {len(demo)}")
    for index, url in sorted(demo.items()):
        ts, build = launches[index]
        nxt = launches[index + 1] if index + 1 < len(launches) else None
        after = f"; next launch {nxt[0]:%d %b %H:%M} {nxt[1]}" if nxt else "; no later launch"
        print(f"  {ts:%a %d %b %H:%M} {build} tried {url}{after}")
    print()

    print("=== 2. AI ADVISOR QUESTIONS, AND AI FAILURES ===")
    print(f"questions asked (context lines): {len(asked)}", end="")
    if asked:
        days = sorted({t.date() for t, _, _ in asked})
        held = sum(1 for _, _, h in asked if h)
        print(
            f", {len(days)} days, {asked[0][0]:%d %b} to {asked[-1][0]:%d %b}; "
            f"about a held symbol {held}, not held {len(asked) - held}"
        )
        by_symbol = Counter(s for _, s, _ in asked)
        print("  by symbol: " + ", ".join(f"{s} {n}" for s, n in by_symbol.most_common()))
    else:
        print()
    for label, _ in FAILURES:
        n = failures.get(label, 0)
        days = ", ".join(f"{d:%d %b}" for d in sorted(failure_days.get(label, set())))
        print(f"  {label}: {n}" + (f" ({days})" if n else ""))
    print()


def section_reports(data: Path) -> None:
    print("=== 3. REPORT NARRATIVES ('Analyst notes') ===")
    for name in ("daily_reports.md", "weekly_reports.md"):
        text = (data / name).read_text(encoding="utf-8")
        sections = re.split(r"(?m)^## ", text)[1:]
        with_notes = model = demo = 0
        missing: list[str] = []
        for body in sections:
            title = body.splitlines()[0].strip()
            notes = re.search(r"(?ms)^### Analyst notes\s*\n(.*?)(?=^#|\Z)", body)
            if not notes:
                missing.append(title)
                continue
            with_notes += 1
            if DEMO_NOTICE in notes.group(1):
                demo += 1
            else:
                model += 1
        print(
            f"{name}: {len(sections)} reports ({sections[0].splitlines()[0].strip()} to "
            f"{sections[-1].splitlines()[0].strip()}); with notes {with_notes} "
            f"(model text {model}, demo notice {demo}); without notes {len(missing)}"
        )
        for title in missing:
            print(f"  no notes: {title}")


def main(data: Path) -> None:
    section_log(data / "logs")
    section_reports(data)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
