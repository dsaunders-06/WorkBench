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
# It has to be changed BY HAND at the moment of the copy, not afterwards, and
# this is the second time in the record that it was not. It read f537a9e (M94)
# for a full day after M104 was deployed. Then it sat at c53fb59 (M118) across
# the M130 deploy on 21 August at 17:49 and was still reading M118 the same
# evening - reporting a deploy gap of 14 milestones against a real gap of two.
# The prose in HANDOFF.md was right and this constant was wrong, which is the
# inversion this script exists to prevent.
#
# M134 was deployed 21 August at 20:05 local, market shut, app stopped, broker
# flat, ledgers empty, and this line was changed in the same minute as the copy.
#
# M138 was deployed 24 August at 13:03, read back at 13:04:30: Build: M138
# (77b7238, built 24/08/2026 02:59 UTC, packaged). Installed exe
# SHA256-identical to the signed artefact, signature Valid. ⚠️ THIS ONE CHANGES
# A TRADING-DECISION INPUT - the per-order cap trims instead of refusing, so
# entries that were declined will now be placed smaller.
#
# M137 was deployed 24 August at 11:20, after standing the session down. Read
# back off its own log at 11:21:43: Build: M137 (8387a6b, built 24/08/2026
# 01:16 UTC, packaged). Installed exe SHA256-identical to the signed artefact,
# signature Valid, rollback M134 still in dist/.
#
# What is verified for M134: the tree was clean at 2d7777c, `invoke build`
# stamped the artefact
#   Build stamp: M134 (2d7777c, built 21/08/2026 10:00 UTC)
# with no `-dirty` marker, `invoke sign` signed and timestamp-verified it, and
# the exe now at C:\QuantAdvisoryTerminal is SHA256-identical to the one signed
# in dist\. What is NOT yet verified is the read-back: the app has not been
# launched since the copy, so no `Build:` line has come off its own log. Until
# it has, this constant is an intention, not an observation - which is exactly
# what it was during the M130 deploy.
DEPLOYED = "77b7238"
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
