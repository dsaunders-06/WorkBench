"""Per transcript file: mtime, size, first/last record timestamp, record count (read-only)."""

import datetime as dt
import glob
import json
import os
import sys

src = sys.argv[1]
rows = []
for path in glob.glob(os.path.join(src, "*.jsonl")):
    first = last = None
    n = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                ts = json.loads(line).get("timestamp")
            except json.JSONDecodeError:
                continue
            if not ts:
                continue
            n += 1
            first = ts if first is None or ts < first else first
            last = ts if last is None or ts > last else last
    st = os.stat(path)
    mtime = dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
    rows.append((first or "", last or "", mtime, st.st_size, n, os.path.basename(path)[:8]))

rows.sort()
print(f"{'first (UTC)':20} {'last (UTC)':20} {'mtime (local)':17} {'MB':>7} {'recs':>6} file")
for first, last, mtime, size, n, name in rows:
    print(f"{first[:16]:20} {last[:16]:20} {mtime:17} {size/1e6:7.1f} {n:6} {name}")
print(len(rows), "files")
