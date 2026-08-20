"""What build is this, exactly (M27b tooling).

The install was on M26 while the repository was four milestones ahead, and
nothing in the running application could have told you so - the Settings
screen showed configuration, never provenance. `pyproject`'s `0.1.0` is no
help either: it has never been bumped, so it reads identically on every build
ever made.

Three facts identify a build, and they are deliberately shown together:

* **the milestone** - what a human calls it, and the only part that can go
  stale, because it is maintained by hand;
* **the commit** - what it was actually built from, which cannot;
* **when it was packaged** - which catches the case where the milestone label
  and the commit are both right but the executable is old.

A frozen build has no git and no repository, so the stamp is captured at
package time into a generated module (see `invoke package`). Running from a
checkout there is no stamp, so git is asked directly and the answer is always
current. Neither path can silently report the other's answer: `source` says
which one produced the numbers.
"""

from __future__ import annotations

import subprocess  # nosec B404 - git metadata for display, no untrusted input
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from qat.domain.display_dates import format_display_date

# Bump when a milestone ships. Its accuracy is not load-bearing - the commit
# and the build time beside it are the ground truth, and a stale label is
# visible precisely because they disagree with it.
#
# Compound, because the numbering is a naming scheme rather than a sequence:
# M39-M44 were enumerated as future gaps on 4 August, before M45-M50 existed, so
# M40 shipping after M50 is not a regression. "M40" alone would read to an
# operator as the application having gone backwards.
# Compound, and this build is exactly the case the note above describes: M39 was
# enumerated as a future gap on 4 August, so "M39" alone would read to an
# operator as the application having gone backwards from M86. Two milestones
# ship here and both are named.
#
# M88 ships alone: it is the next number in sequence and reads forwards from
# M87 without ambiguity, so it needs no compounding.
#
# M89 ships alone for the same reason. It is a RECORD-CORRECTNESS build and
# changes no trading decision: a stop-out was being recorded as `target`, and
# seven of the twenty-three refusal messages the rails can emit were classified
# as "not recognised" on the Blotter and in the daily report. The OMS gained an
# injectable clock, which defaults to the wall clock and is inert in live.
# M90 is the first build since 3 August that CHANGES A TRADING-DECISION INPUT,
# and it ships under a recorded freeze lift rather than despite the freeze. The
# aggregate risk cap now measures positions on the broker's mark instead of the
# price they were opened at.
#
# THE REPORTED FIGURE WILL JUMP, and that is the fix rather than a fault:
# 5.01% -> about 6.34% on the book as it stands. Nothing is forced to sell -
# QAT_DELEVER_SWEEP_ENABLED=false in the live config - and entries were already
# refused at 5.01%, so no trade that would have happened now will not.
#
# M104 is the first build of the IBKR/ASX path, and it ships TWELVE milestones
# at once because M94 was the last thing packaged - the repository ran ten
# milestones ahead of any build, which is the state this constant exists to
# make visible rather than to hide.
#
# What an operator will see that is new: broker=ibkr now RESOLVES rather than
# refusing (M101), so the application can run against an IB Gateway; ASX
# symbols reach the ASX listing rather than failing to resolve (M96);
# corporate-action detection reports UNAVAILABLE as a standing condition
# instead of a per-symbol query failure every sweep (M100).
#
# THE ALPACA PATH IS TOUCHED, and not only added to. M100 changed the
# corporate-action monitor and both screens, M101 put a BrokerConnection engine
# first in the startup order for EVERY broker, and M98 added two optional
# fields to RestingStopOrder. All are no-ops on Alpaca by construction and none
# has run a session there.
#
# NO TRADING-DECISION INPUT CHANGES on the US path. The IBKR order translation
# changed profoundly - protective stops transmit as STP rather than as MARKET
# orders (M95), which on IBKR was a stop that liquidated the position it was
# meant to protect - but none of that path has ever executed in production.
#
# M109 ships FIVE milestones, all of them observability, and every one of them
# was written because the first two live ASX sessions on 19-20 August produced
# a true statement that answered the wrong question.
#
# What an operator will see that is new: a session announces itself at startup
# even when it was BORN healthy rather than transitioning into it (M108) -
# without that line every tool anchored on "Trading session started" fell back
# to the previous run, and on 20 August session_check reported a finished
# session's start time, its 1,056 errors and its adopted Alpaca positions
# against a session that had begun ninety minutes later. The entry allow list
# now announces itself too (M109), naming how many watched symbols may be
# entered and how many will signal and be refused; on 20 August it silently
# discarded six correct pre-open signals and was found four minutes after the
# setups had expired. "Test Broker Connection" now actually tests the
# connection instead of returning a tick regardless (M105).
#
# The pre-flight gained a tradable-universe check (M106) and then had it
# widened (M109), because the first version only asserted that the watchlist
# and the allow list OVERLAP - which was true on 20 August, and useless. It
# now warns when the allow list excludes part of the watchlist and names what
# it is refusing.
#
# THE ALPACA PATH IS TOUCHED. M108 changes SessionController for every market,
# so a US session will now emit a started line it did not emit before. M109's
# allow-list banner fires only when QAT_ENTRY_ALLOW_LIST is set, which is a
# machinery-test setting and empty on the US path.
#
# NO TRADING-DECISION INPUT CHANGES on any path. Nothing here touches sizing,
# gating, risk limits or order translation. M109's pre-flight WARN does not
# block a launch - the pre-flight is a hand-run script and has never been a
# startup gate - and the two new startup lines are log output.
#
# M118 ships M110-M118. The label sat at M109 on master this whole time because
# M111's bump was made on the `deploy/m111` branch, to exclude an unmeasured
# M112, and never came back - so `invoke package` on master would have stamped
# an M118 tree "M109". That is the exact staleness M109 was raised to fix,
# recurring by a different route, and it is why this constant is read back off
# a RUNNING build rather than trusted from the packager.
#
# CHANGES A TRADING-DECISION INPUT, twice.
#
# M111: the ASX daily bar boundary was UTC midnight, so a vendor bar stamped
# `2026-08-20 00:00:00+10:00` floored to the 19th. Every seeded ASX bar carried
# the day BEFORE the one it traded on, and today's half-finished session was
# admitted as a COMPLETED bar - so the swing entry's "previous bar" contained
# today's prices. It now reads yesterday's completed close. The daily-loss
# baseline also keys on the exchange trading date, so it will not re-arm an hour
# into the session when AEDT starts on 5 October.
#
# M112: the regime engine's breadth feature has been constant-zero for the whole
# ASX period - `_aligned_breadth` required TOTAL coverage of the benchmark's
# dates and kept 0 of 7 symbols on live data. It now carries a close across a
# gap. MEASURED before shipping, on 301 seeded bars: label low_vol either way,
# exposure scalar 1.0 either way, NO SIZE CHANGE on that day's data. The
# probability distribution does move, so that is evidence and not a proof.
#
# What else an operator will see: the entry allow list announces itself at
# startup (M109); the pre-flight states its feed coverage instead of implying it
# checked everything, and a total feed failure now names the SOURCE rather than
# the symbols (M110, M118); six dead ASX tickers are gone; the AI Advisor is
# given the next results date and, if QAT_NEWS_SOURCE says so, company news that
# two independent outlets carried (M115-M117, off by default).
MILESTONE = "M118"

_UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class BuildInfo:
    milestone: str
    commit: str
    built_at: str
    source: str

    @property
    def is_packaged(self) -> bool:
        return self.source == "packaged"

    def one_line(self) -> str:
        return f"{self.milestone} ({self.commit}, built {self.built_at}, {self.source})"


def _frozen() -> bool:
    return getattr(sys, "frozen", False)


def _git(*args: str) -> str | None:
    """Repository metadata, or None anywhere that is not a checkout.

    Every failure mode lands here as None rather than as an exception: no git
    on PATH, not a repository, a git that hangs. A version display is not worth
    delaying startup for, let alone failing it.
    """
    try:
        result = subprocess.run(  # nosec B603 B607 - fixed argv, no shell, no user input
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _git_describe() -> str:
    """A tag when one exists, the short SHA otherwise.

    There are no release tags today, so this is the short SHA in practice. It
    is written this way so that starting to tag releases upgrades the display
    on its own, rather than needing this file changed to notice.
    """
    described = _git("describe", "--tags", "--always", "--dirty")
    return described or _UNKNOWN


def build_info() -> BuildInfo:
    """The running build, from the packaged stamp or from git."""
    try:
        from qat import _build_stamp  # type: ignore[attr-defined]
    except ImportError:
        pass
    else:
        return BuildInfo(
            milestone=_build_stamp.MILESTONE,
            commit=_build_stamp.COMMIT,
            built_at=_build_stamp.BUILT_AT,
            source="packaged",
        )

    if _frozen():
        # Packaged, but the stamp is missing - built by something other than
        # `invoke package`. Say so rather than falling through to git, which
        # in a frozen app would report whatever checkout happens to be beside
        # the executable, or nothing at all.
        return BuildInfo(
            milestone=MILESTONE, commit=_UNKNOWN, built_at=_UNKNOWN, source="packaged, unstamped"
        )

    return BuildInfo(
        milestone=MILESTONE,
        commit=_git_describe(),
        built_at=format_display_date(datetime.now(UTC)),
        source="source checkout",
    )


def stamp_module_source(milestone: str, commit: str, built_at: str) -> str:
    """The generated module `invoke package` writes before freezing.

    A Python module rather than a data file, so PyInstaller's import analysis
    picks it up on its own - an `--add-data` file would need the spec and the
    task to agree forever, and would fail by being silently absent.
    """
    return (
        '"""Generated by `invoke package`. Not tracked; see qat/version.py."""\n\n'
        f'MILESTONE = "{milestone}"\n'
        f'COMMIT = "{commit}"\n'
        f'BUILT_AT = "{built_at}"\n'
    )
