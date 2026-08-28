"""Rewrite `handoff_state.DEPLOYED` as part of a deploy (item 29).

    & ".\\.venv\\Scripts\\python.exe" scripts\\record_deploy.py <commit>

Called by `scripts/deploy.ps1` AFTER the installed copy has been verified, so
the record can only change once the thing it records is true.

## Why this is a script and not a reminder

`DEPLOYED` is hand-maintained and its own comment says it must change in the
same minute as the copy. It was wrong for a day after M104, across the whole
M130 deploy, for two hours after M139 - and, found while writing this, through
EVERY deploy of 28 August: it still read `0b1ecd6` (M148) with M155 installed.

⚠️ Exhortation has failed ten times, and the last seven were failures of the
person who wrote the exhortation. The step a human must remember is the step
missed in the rush before a close, which is exactly when a wrong deploy record
costs the most - `handoff_state.py` is what the next session reads to learn
whether the running build matches the tree.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# 7-40 hex characters: what `git rev-parse --short` produces and what
# `deployed_milestone()` can resolve back to a commit.
_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")

# Anchored to the start of a line, so only the CONSTANT is touched. The old
# commit appears elsewhere in that file - in the deploy history prose, and
# sometimes as a literal in another function - and a blind text replace would
# rewrite the record of previous deploys, which is the one thing the file exists
# to preserve.
_ASSIGNMENT = re.compile(r'^DEPLOYED = "([0-9a-f]{7,40})"$', re.MULTILINE)


def rewrite_deployed(path: Path, commit: str) -> bool:
    """Point `DEPLOYED` at `commit`. True if the file changed.

    Raises rather than returning False when the constant is absent: a deploy
    that half-succeeds - installing the build but leaving the record stale - is
    how this became wrong in the first place, so it must fail loudly.
    """
    if not _COMMIT.match(commit or ""):
        raise ValueError(f"{commit!r} is not a short git commit (7-40 hex characters)")

    source = path.read_text(encoding="utf-8")
    match = _ASSIGNMENT.search(source)
    if match is None:
        raise ValueError(
            f'no `DEPLOYED = "..."` assignment in {path.name} - the deploy record cannot '
            f"be updated, and the deploy must not report success while it is stale"
        )
    if match.group(1) == commit:
        return False

    path.write_text(_ASSIGNMENT.sub(f'DEPLOYED = "{commit}"', source, count=1), encoding="utf-8")
    return True


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: record_deploy.py <commit>")
        return 2
    path = Path(__file__).with_name("handoff_state.py")
    try:
        changed = rewrite_deployed(path, sys.argv[1])
    except ValueError as exc:
        print(f"REFUSED: {exc}")
        return 1
    print(f"DEPLOYED {'updated to' if changed else 'already at'} {sys.argv[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
