"""Every AskUserQuestion dialog in the transcripts: question, options, operator's answer."""

import glob
import json
import os
import sys
from datetime import datetime, timedelta

SRC = os.path.expanduser(r"~\.claude\projects\C--Claude-Programming")
SKIP = sys.argv[2] if len(sys.argv) > 2 else ""
out = open(sys.argv[1], "w", encoding="utf-8")
seen = set()
rows = []
for path in glob.glob(os.path.join(SRC, "*.jsonl")):
    sid = os.path.basename(path)[:8]
    if sid == SKIP:
        continue
    asks = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = rec.get("message", {}).get("content")
            if not isinstance(content, list):
                continue
            for c in content:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "tool_use" and c.get("name") == "AskUserQuestion":
                    asks[c["id"]] = (rec.get("timestamp", ""), c.get("input", {}))
                elif c.get("type") == "tool_result" and c.get("tool_use_id") in asks:
                    ts, inp = asks.pop(c["tool_use_id"])
                    res = c.get("content")
                    if isinstance(res, list):
                        res = "\n".join(x.get("text", "") for x in res if isinstance(x, dict))
                    key = (ts, str(res)[:200])
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append((ts, sid, inp, res))
rows.sort(key=lambda r: r[0])
for ts, sid, inp, res in rows:
    aest = (datetime.fromisoformat(ts.replace("Z", "+00:00")) + timedelta(hours=10)).strftime(
        "%d %b %H:%M"
    )
    out.write(f"## {aest} AEST [{sid}]\n")
    for q in inp.get("questions", []):
        out.write(f"Q: {q.get('question')}\n")
        for o in q.get("options", []):
            out.write(f"   - {o.get('label')}: {o.get('description', '')[:300]}\n")
    out.write(f"ANSWER: {res}\n\n")
print(len(rows), "dialogs")
