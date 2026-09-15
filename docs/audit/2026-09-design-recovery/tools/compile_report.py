"""Compile the audit's section files into the single final report.

Read-only on the sections; writes one file beside them.

    python compile_report.py

Order, as the operator asked on 15 Sep ("your Executive Summary and detailed
report analysis reflective of the order of development"):
  R1 (the executive summary), Part I (the chronology), R2-R24 (the brief's
  sections), Annex A (anomalies), Annex B (evidence), Annex C (the error-log
  back-fill register).

The section files stay the source. Re-run after any change to them; the
compiled file is never edited by hand.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
OUT = HERE / "QAT-Design-Recovery-Audit-Final-Report.md"
ORDER = (
    ["01-executive-summary.md", "P-development-chronology.md"]
    + sorted(p.name for p in HERE.glob("[0-2][0-9]-*.md") if p.name[:2] not in ("00", "01"))
    + ["A-anomalies-register.md", "B-evidence-index.md", "backfill/00-backfill-register.md"]
)
ANNEX_C_TITLE = "# QAT Design Recovery & Design Intent Audit, Annex C: Error-Log Back-fill Register"


def title(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].split(", ", 1)[-1].strip()
    raise ValueError("no title")


def anchor(heading: str) -> str:
    keep = "".join(c for c in heading.lower() if c.isalnum() or c in " -")
    return keep.replace(" ", "-")


def main() -> None:
    head = subprocess.run(
        ["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(HERE), "status", "--porcelain", "--", *ORDER],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if dirty:
        head += " plus uncommitted changes to the sections"
    parts: list[tuple[str, str, str, str]] = []
    for name in ORDER:
        text = (HERE / name).read_text(encoding="utf-8").rstrip() + "\n"
        if name.startswith("backfill/"):
            text = ANNEX_C_TITLE + "\n" + text.split("\n", 1)[1]
        full = next(line[2:] for line in text.splitlines() if line.startswith("# "))
        parts.append((name, title(text), anchor(full), text))
    assert len(parts) == 28, len(parts)

    lines = [
        "# QAT Design Recovery & Design Intent Audit: Final Report",
        "",
        "**Issued 15 September 2026, for the operator's review at Checkpoint B.**",
        "",
        "Compiled from the section files in `docs/audit/2026-09-design-recovery/`",
        f"at commit `{head}` by `tools/compile_report.py`. The section files are",
        "the source; this file is regenerated, never edited.",
        "",
        "**Classification (R24): 🔴 RED: DESIGN COMPROMISED.**",
        "",
        "Nothing in QAT was changed during the audit. Development is frozen and",
        "trading suspended until the operator's review.",
        "",
        "## Contents",
        "",
    ]
    for name, short, link, _text in parts:
        lines.append(f"* [{short}](#{link}) (`{name}`)")
    lines.append("")
    body = "\n".join(lines)
    for _name, _short, _link, text in parts:
        body += "\n---\n\n" + text
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(body, encoding="utf-8", newline="\n")
    os.replace(tmp, OUT)
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    print(f"{OUT.name}: {len(parts)} parts, {body.count(chr(10)):,} lines, ")
    print(f"{OUT.stat().st_size:,} bytes, sha256 {digest}")


if __name__ == "__main__":
    main()
