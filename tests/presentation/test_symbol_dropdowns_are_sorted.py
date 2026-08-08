"""Every dropdown listing tickers is alphabetical (M76).

`universe.resolve_watchlist` returns the universe's own order, which is roughly
by market capitalisation. That is meaningful to the universe and useless to
someone hunting for WFC in a list of a hundred, and it is the order both symbol
pickers used.

**Sorted at the dropdown, never in `runtime.watchlist` itself.** The Risk
Console builds its correlation matrix by indexing that tuple positionally -
`index_by_symbol = {symbol: i for i, symbol in enumerate(...)}` against headers
set from the same order - so reordering the watchlist would move a rail's data
rather than a control's labels.

One test per screen rather than a loop over a registry, because a screen that is
added later and forgets is caught by the absence of its own test here, not by a
passing loop that never knew about it.
"""

from __future__ import annotations

from qat.config import Settings
from qat.presentation.ai_advisor import AiAdvisorScreen
from qat.presentation.runtime import Runtime
from qat.presentation.workbench import WorkbenchScreen


def _items(combo) -> list[str]:
    return [combo.itemText(i) for i in range(combo.count())]


def _runtime() -> Runtime:
    return Runtime.build_demo(settings=Settings(_env_file=None))


def test_the_ai_advisor_symbol_picker_is_alphabetical(qtbot):
    screen = AiAdvisorScreen(_runtime())
    qtbot.addWidget(screen)

    items = _items(screen.symbol_picker)

    assert items == sorted(items)


def test_the_workbench_symbol_picker_is_alphabetical(qtbot):
    screen = WorkbenchScreen(_runtime())
    qtbot.addWidget(screen)

    items = _items(screen.symbol_picker)

    assert items == sorted(items)


def test_sorting_the_dropdown_loses_no_symbols(qtbot):
    """Sorted, not filtered or deduplicated - every tradable symbol must still
    be reachable."""
    runtime = _runtime()
    screen = WorkbenchScreen(runtime)
    qtbot.addWidget(screen)

    assert set(_items(screen.symbol_picker)) == set(runtime.watchlist)
    assert len(_items(screen.symbol_picker)) == len(runtime.watchlist)


def test_building_a_screen_does_not_reorder_the_watchlist(qtbot):
    """The Risk Console indexes this tuple positionally against its correlation
    matrix headers, so sorting it in place would move a rail's data rather than
    a control's labels. Sorting must happen at the dropdown and stop there."""
    runtime = _runtime()
    before = tuple(runtime.watchlist)

    for screen in (WorkbenchScreen(runtime), AiAdvisorScreen(runtime)):
        qtbot.addWidget(screen)

    assert tuple(runtime.watchlist) == before
