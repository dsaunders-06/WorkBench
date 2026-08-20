"""Derive the current-state figures the handoff quotes, instead of remembering them.

Every number in `docs/HANDOFF.md` that describes *now* rather than *what
happened* is a hand-maintained copy, and this session demonstrated three times
over what that costs:

* the deploy gap was quoted as five, eight, nine and twelve before anyone counted
  it (the real figure was fourteen);
* "the brief has been wrong in detail" was recorded as third, fifth and sixth in
  three places and FIVE in two more;
* the test count sat at 1,690 in three separate paragraphs while the suite had
  moved to 1,709.

M80 fixed the first two by writing a register and counting rows. This fixes the
third class - the figures that change every time work lands - by computing them.

Run it before editing the handoff:

    .\\.venv\\Scripts\\python.exe scripts/handoff_state.py

It reads the repository and the deployed build. It changes nothing.
"""

from __future__ import annotations

import re
import subprocess  # nosec B404 - local git/pytest introspection, no external input
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# The one figure this tool cannot derive, because only the operator knows what
# is actually installed. Everything else derives FROM it, so a stale value here
# makes every other number confidently wrong.
#
# Updated on deploy. M118 was deployed 21 August 08:57 local, before the open,
# with the app stopped and the broker flat, and this line was changed in the
# same minute as the copy.
#
# BACK ON MASTER. M111 was packaged from the `deploy/m111` branch to exclude an
# unmeasured M112. That measurement was taken on 21 August - breadth dead and
# breadth live both give label low_vol and exposure scalar 1.0, no size change -
# so M112 shipped and the branch is spent. The milestone constant came back to
# master with it; it had been reading M109 against an M118 tree.
#
# What is verified: `invoke package` stamped the artefact
#   Build stamp: M118 (c53fb59, built 20/08/2026 22:36 UTC)
# and that exe is the one now at C:\QuantAdvisoryTerminal. What is NOT verified
# is the running build's own log line - nothing has been launched since the
# copy, and M111 was never read back either. Read it at the next launch: it
# should say M118.
#
# It read f537a9e (M94) for a full day AFTER M104 was deployed, which made the
# deploy gap it reports confidently wrong in the one script whose purpose is
# that nothing here is hand-maintained. This is the figure that cannot be
# derived - only the operator knows what is installed - so it is the one that
# has to be changed BY HAND at the moment of deploying, not afterwards.
DEPLOYED = "c53fb59"
HANDOFF = REPO / "docs" / "HANDOFF.md"


def _git(*args: str) -> str:
    return subprocess.run(  # nosec B603 B607 - fixed argv, no shell
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.strip()


def deployed_milestone() -> str:
    """The deployed build's own milestone label, read out of that commit.

    Was written next to `DEPLOYED` by hand as "(M63+M62)" - a second figure to
    keep in step with the first, in the one script whose whole purpose is that
    nothing here is hand-maintained. `version.py` at that commit already knows.
    """
    source = _git("show", f"{DEPLOYED}:src/qat/version.py")
    found = re.search(r'^MILESTONE = "([^"]+)"', source, re.MULTILINE)
    return found.group(1) if found else "unknown"


def milestones_since_deploy() -> tuple[list[str], int]:
    """Milestones in `src/` since the deployed build, and the commit count.

    **Counted from the DIFF, not from commit subjects.** Three of these commits
    do not carry their milestone number in the subject line - M64, M67 and M68
    are titled by what they do - so `git log | grep M[0-9]` under-reports by
    three, which is how the figure came to be wrong four separate times.
    """
    log = _git("log", "--format=%s", f"{DEPLOYED}..HEAD", "--", "src/")
    commits = [line for line in log.splitlines() if line]
    found: set[str] = set()
    for subject in commits:
        found.update(re.findall(r"\bM(\d+)\b", subject))
    # The three that name themselves by behaviour rather than by number.
    for subject, milestone in (
        ("Regime Monitor", "64"),
        ("Risk Console answer the question", "67"),
        ("correlation the rail enforces", "68"),
    ):
        if any(subject in c for c in commits):
            found.add(milestone)
    return sorted(found, key=int), len(commits)


def test_totals() -> str:
    result = subprocess.run(  # nosec B603 - fixed argv, no shell
        [sys.executable, "-m", "pytest", "-q", "--collect-only"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    match = re.search(r"(\d+) tests? collected", result.stdout)
    return f"{int(match.group(1)):,} collected" if match else "could not collect"


def stale_figures_in_handoff(collected: str) -> list[str]:
    """Any test count written in the handoff that no longer matches."""
    if not HANDOFF.exists() or "collected" not in collected:
        return []
    actual = collected.split()[0]
    return [
        f"line {n}: says {m.group(0)}, suite collects {actual}"
        for n, line in enumerate(HANDOFF.read_text(encoding="utf-8").splitlines(), 1)
        if (m := re.search(r"[\d,]+ tests", line)) and m.group(0).split()[0] != actual
    ]


def main() -> None:
    milestones, commits = milestones_since_deploy()
    collected = test_totals()

    print("Repository")
    print(f"  HEAD            {_git('log', '--oneline', '-1')}")
    print(f"  working tree    {'clean' if not _git('status', '--porcelain') else 'DIRTY'}")
    print(f"  vs origin       {_git('status', '-sb').splitlines()[0]}")
    print()
    print("Deploy gap")
    print(f"  deployed build  {DEPLOYED} ({deployed_milestone()})")
    print(f"  milestones      {len(milestones)} across {commits} commits")
    print(f"  which           {', '.join('M' + m for m in milestones)}")
    print()
    print("Tests")
    print(f"  suite           {collected}")

    stale = stale_figures_in_handoff(collected)
    if stale:
        print()
        print("STALE FIGURES IN docs/HANDOFF.md")
        for line in stale:
            print(f"  {line}")


if __name__ == "__main__":
    main()
