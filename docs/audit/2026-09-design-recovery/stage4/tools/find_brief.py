"""Print user messages from a transcript that contain a phrase (read-only)."""

import json
import sys

path, phrase = sys.argv[1], sys.argv[2].lower()
with open(path, encoding="utf-8") as fh:
    for n, line in enumerate(fh, 1):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") != "user":
            continue
        content = rec.get("message", {}).get("content")
        if isinstance(content, list):
            text = "\n".join(
                c.get("text", "")
                for c in content
                if isinstance(c, dict) and c.get("type") == "text"
            )
        else:
            text = content or ""
        if phrase in text.lower():
            print(f"=== line {n}  {rec.get('timestamp')}  len={len(text)}")
            print(text)
            print()
