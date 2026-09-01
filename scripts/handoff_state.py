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
# M140 was deployed 24 August at 15:54, read back at 15:55:24: Build: M140
# (e432e1f, built 24/08/2026 05:51 UTC, packaged). This line was changed in the
# same minute as the copy, which is the rule and which M139 broke.
#
# M139 was deployed 24 August at 15:17, read back at 15:19:02: Build: M139
# (f2d0278, built 24/08/2026 04:23 UTC, packaged). Verified in production the
# same minute - one signal, ONE transmission, correctly bracketed.
#
# ⚠️ AND THIS CONSTANT WAS LEFT AT M138 FOR TWO HOURS, which is the third time
# in the record. The rule this comment block sets - change it in the same minute
# as the copy - was broken again, this time in the rush to get a session running
# before the close. The lesson is not "remember harder": it is that a figure
# only a human can supply will be missed at exactly the moments that matter
# most. Worth making `invoke deploy` do the copy AND this line together.
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
# What is verified for M141: the tree was clean at 09ab51b, `invoke build`
# stamped the artefact
#   Build stamp: M141 (09ab51b, built 24/08/2026 22:58 UTC)
# with no `-dirty` marker, `invoke sign` signed and timestamp-verified it, and
# the exe now at C:\QuantAdvisoryTerminal is SHA256-identical to the one signed
# in dist\ (7FFE257D...44A528), signature Valid. Rollback is a rename:
# C:\QuantAdvisoryTerminal.bak-M140-20260825-0901 is the M140 install, intact.
#
# M148 DEPLOYED 26 August 19:05, updated in the same minute as the copy.
# Clean tree at 0b1ecd6, stamped "M148 (0b1ecd6, built 26/08/2026 19:02:41
# AEST)", signed and timestamp-verified, installed exe SHA256-identical to the
# signed artefact (2CF98E9F...9706), signature Valid on the INSTALLED copy.
# Rollback: C:\QuantAdvisoryTerminal.bak-M147-20260826-1905.
#
# Carries items 56 and 57. Deployed AFTER the close, unlike the day's earlier
# two.
#
# ⚠️ A KILLED BUILD LEAVES src/qat/_build_stamp.py BEHIND, and it breaks the
# suite. `invoke build` unlinks the stamp in a `finally`, which does not run if
# the process is killed - and a leftover stamp makes the app report itself as a
# PACKAGED build of the last frozen commit while running from source. Four
# version tests failed on the next build until it was deleted by hand. The
# stamp's own comment predicts exactly this; what it does not say is that
# recovery is `rm src/qat/_build_stamp.py`.
#
# M147 DEPLOYED 26 August 15:10, updated in the same minute as the copy.
# Clean tree at 0c81b8b, signed and timestamp-verified, installed exe
# SHA256-identical to the signed artefact (08CB73D6...143B), signature Valid on
# the INSTALLED copy. Rollback: C:\QuantAdvisoryTerminal.bak-M146-20260826-1509.
#
# Carries the absorb fix: BrokerFill.quantity AND price are both the order's
# CUMULATIVE figures, and one exit is ONE ledger row however many executions it
# took. Second mid-session deploy of the day, same justification - the kill
# switch was already tripped, and 18 legs were resting at the broker.
#
# THE LEDGER WAS REPAIRED IN THE SAME STOP/START WINDOW.
# scripts/repair_lov_partial_absorb.py --apply, with the app stopped (it must
# be: _save_fill_state rewrites absorbed_fills.json after every pass). The
# 26 August LOV.AX exit now reads 5 rows / 3,217 shares instead of 4 / 374.
# Backups kept: closed_trades.csv.bak-20260826-150939-PRE-LOV-REPAIR and
# absorbed_fills.json.bak-20260826-150939-PRE-LOV-REPAIR.
#
# ⚠️ The repair row carries EMPTY entry_cost, exit_cost, net_pnl and
# r_multiple. IBKR's commission on the unabsorbed portion is not knowable after
# the fact, and an honestly incomplete row beats a confidently wrong one. Its
# exit_reason says so out loud.
#
# ⚠️ The automatic repair route was CLOSED by the M146 restart, and that was an
# unintended consequence worth recording. Re-adopting from the broker dropped
# LOV from open_position_entries.json, and _symbols_to_watch_for_fills builds
# from tracked quantities, in-flight orders and that file - so recent_fills
# would never have asked about LOV again, no matter how correct the new code
# is. Restarting after an unabsorbed exit forfeits the chance to absorb it.
#
# M146 DEPLOYED 26 August 14:35, updated in the same minute as the copy.
# Clean tree at 6f965fc, stamped "M146 (6f965fc, built 26/08/2026 14:32:08
# AEST)", signed and timestamp-verified, installed exe SHA256-identical to the
# signed artefact (D7718C39...DAAE9), signature Valid on the INSTALLED copy.
# Rollback is a rename: C:\QuantAdvisoryTerminal.bak-M145-20260826-1435.
#
# ⚠️ DEPLOYED MID-SESSION, deliberately and on the operator's instruction. The
# standing rule is to deploy before the open or after the close. The exception
# here is that the KILL SWITCH WAS ALREADY TRIPPED, so no order flow was
# possible in either direction - deploying a sizing-input change into a halted
# system is safer than deploying it into a live one. The book stayed protected
# throughout: 18 legs resting AT THE BROKER, independent of the app.
#
# Carries Milestone A of the macro Phase 2 plan. Its own evidence is why this
# was safe to ship into an open market at all: the label does NOT move,
# label=bull scalar=1.00 before and after, through the real fusion path.
#
# M145 DEPLOYED 26 August 08:41, updated in the same minute as the copy.
# Clean tree at 08e4dc5, stamped "M145 (08e4dc5, built 26/08/2026 08:38:09
# AEST)" - the first stamp to render in AEST rather than UTC (item 50) - signed
# and timestamp-verified, installed exe SHA256-identical to the signed artefact
# (576F9A72...86D65), signature Valid on the INSTALLED copy. Rollback is a
# rename: C:\QuantAdvisoryTerminal.bak-M144-20260826-0841.
# Carries item 34's ROOT CAUSE fix, which has NOT been read back or exercised
# live yet - the next launch is its first test.
#
# M144 DEPLOYED 25 August 22:04, updated in the same minute as the copy.
# Clean tree at 9e168dd, stamped "M144 (9e168dd, built 25/08/2026 12:01 UTC)",
# signed and timestamp-verified, installed exe SHA256-identical to the signed
# artefact (AC0E87CE...), signature Valid on the INSTALLED copy. Rollback is a
# rename: C:\QuantAdvisoryTerminal.bak-M143-20260825-2204.
#
# READ BACK by the operator on 25 August: M144 confirmed running. So this
# constant is an OBSERVATION, not an intention - the distinction that made
# it wrong for a day after M104, across the whole M130 deploy, and for two
# hours after M139.
#
# Carries company reported results (item 48), an earnings calendar that finally
# answers for ASX (item 49), and ASX announcement dates read in AEST rather
# than New York - which was a sizing error waiting to happen, since that date
# sets the earnings blackout.
#
# M143 DEPLOYED 25 August 21:33, updated in the same minute as the copy.
# Clean tree at f81d2d4, stamped "M143 (f81d2d4, built 25/08/2026 11:30 UTC)",
# signed and timestamp-verified. Installed exe SHA256-identical to the signed
# artefact (192A9E9A...), signature Valid on the INSTALLED copy. Rollback is a
# rename: C:\QuantAdvisoryTerminal.bak-M142-20260825-2133.
#
# NOT YET READ BACK - not launched since the copy.
#
# Carries item 47: the AI symbol verdict could never render on IBKR because it
# required day_pnl_pct, derived from last_equity, which this broker never
# supplies. Two live sessions ran with item 16's centrepiece silently absent.
# Tomorrow is its FIRST real test, not a re-check.
#
# M142 DEPLOYED 25 August 17:52, updated in the same minute as the copy.
# Built from a clean tree at 543a978, stamped "M142 (543a978, built 25/08/2026
# 07:49 UTC)" with no -dirty marker, signed and timestamp-verified. Installed
# exe SHA256-identical to the signed artefact (06B14878...B816), signature
# Valid on the INSTALLED copy. Rollback is a rename:
# C:\QuantAdvisoryTerminal.bak-M141-20260825-1752.
#
# NOT YET READ BACK - the app has not been launched since this copy, so no
# Build: line has come off its own log. This constant is an INTENTION until it
# has, which is the distinction that made it wrong three times before.
#
# The M141 record below is kept for the read-back it does have.
#
# READ BACK OFF ITS OWN LOG at 09:09 on 25 August, so this is an OBSERVATION
# and not an intention:
#   Build: M141 (09ab51b, built 24/08/2026 22:58 UTC, packaged)
#
# And the rail it carries was verified in the same run, which matters more:
#   RESTING ORDER SCAN: 2 working leg(s) across 1 symbol(s), nothing unjustified
# TWO legs, not one. It saw both halves of TNE.AX's live bracket - stop 30.69
# AND target 36.86 - netted them as one-cancels-all, and correctly declined to
# flag 6,102 resting sell against a 3,051 long. `from_ib_resting_stop` can only
# ever see ONE of those, because it drops LIMIT orders by type; the take-profit
# leg was invisible to this application until this run, and eight of the sixteen
# orphans on 24 August were exactly that kind.
#
# The leg COUNT is why this is evidence. "0 divergences" is what a blind scan
# prints too.
#
# Updated in the same minute as the copy, which is the whole of item 29. This
# line was wrong for a day after M104, across the whole M130 deploy, and for
# two hours after M139.
DEPLOYED = "04053ba"
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


# ⚠️ A COLLECTED count, because that is the only figure this script has.
#
# The pattern was `[\d,]+ tests`, and on 28 August its ONLY output was a false
# positive: item 22's note that a change "broke 134 tests" - a historical count
# of what FAILED, and still true. A checker whose entire output is a line you
# have to know to ignore is a checker that gets ignored, and the real stale
# figure goes past with it. Same argument as item 20's allowlist: a guard that
# flags things which are fine earns an exemption list, and an exemption list is
# not read.
#
# ⚠️ THE "N passed" FIGURE IS DELIBERATELY NOT CHECKED. `test_totals` only
# COLLECTS - three seconds against three and a half minutes - so there is no
# passed count to compare against, and checking "2,903 passed" against the
# collected total would be wrong by exactly the skip count, every single run.
# A number this cannot verify is left alone rather than verified against the
# nearest number to hand.
_COLLECTED_CLAIM = re.compile(r"([\d,]+)\s+(?:tests?\s+)?collected")


def stale_figures_in_handoff(collected: str) -> list[str]:
    """Any COLLECTED total written in the handoff that no longer matches."""
    if not HANDOFF.exists() or "collected" not in collected:
        return []
    actual = collected.split()[0]
    return [
        f"line {n}: says {m.group(0)}, suite collects {actual}"
        for n, line in enumerate(HANDOFF.read_text(encoding="utf-8").splitlines(), 1)
        if (m := _COLLECTED_CLAIM.search(line)) and m.group(1) != actual
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
