"""The Performance tab must show the present, not the launch (M31b).

refresh() ran at construction and on the button, and nowhere else. A session
started at 00:18 still displayed 00:18's figures at 06:04 - with Friday's daily
report on disk and absent from the screen, the promotion table frozen, and the
closed-trades list stale. Read as three separate reporting bugs; it was one
display bug.
"""

from __future__ import annotations

from qat.config import Settings
from qat.presentation.performance import PerformanceScreen
from qat.presentation.runtime import Runtime


def _screen(qtbot) -> PerformanceScreen:
    screen = PerformanceScreen(Runtime.build_demo(settings=Settings(_env_file=None)))
    qtbot.addWidget(screen)
    return screen


def test_showing_the_tab_re_reads_from_disk(qtbot):
    screen = _screen(qtbot)
    calls: list[int] = []
    screen.refresh = lambda: calls.append(1)  # type: ignore[method-assign]

    screen.show()
    qtbot.waitExposed(screen)

    assert calls, "switching to the tab must re-read rather than show the launch snapshot"


def test_the_live_timer_runs_only_while_the_tab_is_visible(qtbot):
    """A session should spend nothing polling a tab nobody is looking at."""
    screen = _screen(qtbot)

    screen.show()
    qtbot.waitExposed(screen)
    assert screen._live_timer.isActive()

    screen.hide()
    assert not screen._live_timer.isActive()
