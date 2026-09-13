"""Condense operator_messages.txt: dedupe identical (ts, text), truncate long pastes."""

import re
import sys
from datetime import datetime, timedelta

src, out, limit = sys.argv[1], sys.argv[2], int(sys.argv[3])
blocks = re.split(r"^=== ", open(src, encoding="utf-8").read(), flags=re.M)
seen = set()
kept = 0
with open(out, "w", encoding="utf-8") as fh:
    for b in blocks:
        if not b.strip():
            continue
        head, _, text = b.partition("\n")
        ts = head.split()[0]
        text = text.strip()
        key = (ts, text[:200])
        if key in seen:
            continue
        seen.add(key)
        aest = (datetime.fromisoformat(ts.replace("Z", "+00:00")) + timedelta(hours=10)).strftime(
            "%d %b %H:%M"
        )
        sid = head.split("session ")[1].split()[0]
        if len(text) > limit:
            text = text[:limit] + f"\n[... truncated, {len(text)} chars total]"
        fh.write(f"## {aest} AEST [{sid}] {ts}\n{text}\n\n")
        kept += 1
print(kept, "kept")
