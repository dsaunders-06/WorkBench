"""M109: an allow list that silenced six correct signals said nothing at startup.

20 August, the first live ASX session. At 09:51-09:56, pre-open, `swing`
correctly found a pullback-and-reclaim on all six watched names and proposed
six entries. Every one was refused: the entry allow list still named the
PREVIOUS day's symbols (BHP, CBA, STW) against a 100-symbol watchlist (101
symbols were polled - the watchlist plus the STW.AX benchmark, which the feed
always streams and which is not itself tradable).

Nothing said so. The refusals went to the decision journal, which nobody reads
during a session, and the log said nothing at all. The allow list was corrected
at 10:04 - four minutes after the 10:00 open, by which time the daily bar had
rolled and the setup had expired. The session then ran 4h49m and traded nothing,
which afterwards reads exactly like a session where the strategy found nothing.

The check that shipped for this (M106's "tradable universe") would NOT have
caught it: BHP/CBA/STW were all inside the megacap watchlist, so the overlap
was non-empty and the check would have returned OK. It verifies that SOME
symbol is tradable, not that the tradable set is the one the operator meant.

No structural rule can tell a stale allow list from a deliberate narrowing -
three permitted out of a hundred watched looks identical either way. So this
does not try. It makes the gap LOUD, at startup, in the log an operator
actually reads while a session is running.
"""

from __future__ import annotations

from qat.data.universe import allow_list_banner, describe_tradable


def test_no_allow_list_means_no_restriction_and_nothing_to_announce() -> None:
    """None and empty mean opposite things. No allow list is not "nothing
    permitted", and an unrestricted session must not be nagged about a
    restriction it does not have."""
    universe = describe_tradable(["RIO.AX", "APA.AX"], None)

    assert universe.restricted is False
    assert universe.tradable == ("APA.AX", "RIO.AX")
    assert universe.refused == ()
    assert allow_list_banner(universe) is None


def test_an_allow_list_covering_the_whole_watchlist_still_announces_itself() -> None:
    """The correct state announces itself too. A banner that appears only when
    something is wrong teaches the reader that its absence means "fine", and
    silence is not a state - the same argument M108 made for the session line."""
    universe = describe_tradable(["RIO.AX", "APA.AX"], {"RIO.AX", "APA.AX"})

    assert universe.restricted is True
    assert universe.refused == ()
    banner = allow_list_banner(universe)
    assert banner is not None
    assert "2 of 2" in banner


def test_the_20_august_state_names_how_many_signals_will_be_thrown_away() -> None:
    """The regression this milestone exists for. Three permitted names against
    a hundred watched is not an error the app can detect - but it is a number
    an operator would have questioned instantly."""
    watched = [f"SYM{i}.AX" for i in range(97)] + ["BHP.AX", "CBA.AX", "STW.AX"]

    universe = describe_tradable(watched, {"BHP.AX", "CBA.AX", "STW.AX"})
    banner = allow_list_banner(universe)

    assert universe.tradable == ("BHP.AX", "CBA.AX", "STW.AX")
    assert len(universe.refused) == 97
    assert banner is not None
    assert "3 of 100" in banner
    assert "97" in banner
    assert "REFUSED" in banner
    # It must name what CAN trade. The operator's error was about identity,
    # not arithmetic: they would have recognised the wrong three instantly.
    assert "BHP.AX" in banner


def test_allow_list_symbols_that_are_never_watched_are_called_out() -> None:
    """A permitted symbol outside the watchlist can never trade - it is not
    polled, so it never signals. That is a dead setting, and it is the shape
    the allow list takes when a watchlist is changed and it is not."""
    universe = describe_tradable(["RIO.AX"], {"RIO.AX", "MGR.AX", "SGP.AX"})
    banner = allow_list_banner(universe)

    assert universe.unwatched == ("MGR.AX", "SGP.AX")
    assert banner is not None
    assert "MGR.AX" in banner and "SGP.AX" in banner


def test_no_overlap_at_all_leaves_nothing_tradable() -> None:
    universe = describe_tradable(["RIO.AX", "APA.AX"], {"BHP.AX"})

    assert universe.tradable == ()
    assert universe.refused == ("APA.AX", "RIO.AX")
    assert universe.unwatched == ("BHP.AX",)


def test_the_banner_says_exits_are_not_gated() -> None:
    """Entries only - a held position must always be able to leave, and an
    operator reading a restriction notice needs to know their stops still work.
    """
    universe = describe_tradable(["RIO.AX", "APA.AX"], {"RIO.AX"})
    banner = allow_list_banner(universe)

    assert banner is not None
    assert "xit" in banner
