"""Print user and assistant TEXT (no tool calls/results) from a transcript in a UTC window.

usage: window.py <session-prefix> <from-utc-iso> <to-utc-iso> [maxchars-per-msg]
"""

import glob
import json
import os
import re
import sys

SRC = os.path.expanduser(r"~\.claude\projects\C--Claude-Programming")
prefix, t0, t1 = sys.argv[1], sys.argv[2], sys.argv[3]
cap = int(sys.argv[4]) if len(sys.argv) > 4 else 6000
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)

path = glob.glob(os.path.join(SRC, prefix + "*.jsonl"))[0]
with open(path, encoding="utf-8") as fh:
    for line in fh:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = rec.get("timestamp", "")
        if not (t0 <= ts <= t1) or rec.get("type") not in ("user", "assistant"):
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
        if not text:
            continue
        if len(text) > cap:
            text = text[:cap] + f"\n[... {len(text)} chars]"
        print(f"----- {rec['type'].upper()} {ts}\n{text}\n")
