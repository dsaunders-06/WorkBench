"""Audit, error-log back-fill: the operator's messages that correct or query Claude.

Read-only. Reads the Claude Code transcripts; prints to stdout.

    python operator_corrections.py <transcripts_dir>

Only the operator's TYPED messages are read (dialog answers are choices, not
corrections). A resumed session copies its parent's history into its own
file, so messages are de-duplicated on (timestamp, text). A context
compaction stores Claude's own summary as a user record (isCompactSummary);
it is not the operator's, and is skipped (finalisation, 15 Sep: the first
version counted them).

A message is listed when it carries a correction cue: the operator saying
something is wrong, asking why Claude did something, or pointing at a
contradiction. The cue list is deliberately wide. Each hit is a lead to
check against the error log, not an error in itself.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

AEST = timezone(timedelta(hours=10))
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
CUE = re.compile(
    r"\b(wrong|incorrect|not (right|correct|what i)|mistake|error you|you said|you told|"
    r"why (did|have|has|is|are|was|were) (you|it|this|that)|i (asked|told|said)|"
    r"contradict\w*|misalign\w*|misleading|inaccurate|that'?s not|isn'?t (right|true)|"
    r"doesn'?t (match|add up)|stale|confus\w*|breach\w*|without (asking|permission))\b",
    re.I,
)


def main(folder: Path) -> None:
    seen: set[tuple[str, str]] = set()
    hits: list[tuple[datetime, str, str]] = []
    total = 0
    for path in sorted(folder.glob("*.jsonl")):
        sid = path.name[:8]
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("type") != "user" or rec.get("isMeta") or rec.get("isCompactSummary"):
                    continue
                content = rec.get("message", {}).get("content")
                if isinstance(content, list):
                    if any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content):
                        continue
                    text = "\n".join(
                        c.get("text", "")
                        for c in content
                        if isinstance(c, dict) and c.get("type") == "text"
                    )
                else:
                    text = content or ""
                text = REMINDER.sub("", text).strip()
                if not text or text.startswith(("<command-", "<local-command", "Caveat:")):
                    continue
                ts = rec.get("timestamp", "")
                key = (ts, text)
                if key in seen:
                    continue
                seen.add(key)
                total += 1
                if CUE.search(text):
                    when = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(AEST)
                    hits.append((when, sid, text))
    hits.sort()
    print(f"operator messages (de-duplicated): {total}; with a correction cue: {len(hits)}\n")
    for when, sid, text in hits:
        flat = " ".join(text.split())
        print(f"{when:%d %b %H:%M} [{sid}] {flat[:400]}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
