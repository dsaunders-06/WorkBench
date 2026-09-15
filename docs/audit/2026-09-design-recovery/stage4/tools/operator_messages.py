"""Dump every operator-typed message from the Claude Code transcripts (read-only).

Skips tool results, meta records and system-reminder blocks. Writes one block per
message: timestamp (UTC), session id, length, text.

Also skips context-compaction summaries (isCompactSummary): Claude's own text,
stored as a user record. Added at finalisation, 15 Sep; no authority entry
(AE-01 to AE-35) cites one of the nine.
"""

import glob
import json
import os
import re
import sys

SRC = os.path.expanduser(r"~\.claude\projects\C--Claude-Programming")
OUT = sys.argv[1]
SKIP_SESSION = sys.argv[2] if len(sys.argv) > 2 else ""

REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)

rows = []
for path in glob.glob(os.path.join(SRC, "*.jsonl")):
    sid = os.path.basename(path)[:8]
    if SKIP_SESSION and sid == SKIP_SESSION:
        continue
    with open(path, encoding="utf-8") as fh:
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
            if not text or text.startswith("<command-") or text.startswith("<local-command"):
                continue
            rows.append((rec.get("timestamp", ""), sid, text))

rows.sort()
with open(OUT, "w", encoding="utf-8") as out:
    for ts, sid, text in rows:
        out.write(f"=== {ts}  session {sid}  len={len(text)}\n{text}\n\n")
print(len(rows), "messages")
