r"""Why does the Balances broker row clip its fifth label?

"Day trades (5d)" renders as "Da" on the Dashboard, cut off at the right edge of
the card and still cut off with the window maximised. Measured, not reasoned
about: the panel ALONE lays out fine at 3086px, so the width is coming from a
sibling on the Dashboard. This finds which one.

    .\.venv\Scripts\python.exe scripts\analysis\probe_balances_layout.py
"""

from __future__ import annotations

import asyncio
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from qat.config import Settings  # noqa: E402
from qat.presentation.balances_panel import BalancesPanel  # noqa: E402
from qat.presentation.dashboard import DashboardScreen  # noqa: E402
from qat.presentation.runtime import Runtime  # noqa: E402
from qat.presentation.ui_level import UiLevel  # noqa: E402

SCREEN = 3072


def panel_alone(width: int) -> None:
    panel = BalancesPanel(min_cash_reserve=1000.0, level=UiLevel.PROFESSIONAL)
    panel.resize(width, 400)
    panel.show()
    QApplication.processEvents()
    body = panel.broker_body
    assert body is not None
    cells = (
        panel.buying_power,
        panel.short_value,
        panel.initial_margin,
        panel.maintenance_margin,
        panel.day_trades,
    )
    xs = [c.mapTo(panel, c.rect().topLeft()).x() for c in cells]
    print(f"  panel alone at {width}: minWidth={panel.minimumSizeHint().width()} " f"cell x = {xs}")


def dashboard(width: int) -> None:
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, ui_level="professional"))
    screen = DashboardScreen(runtime)
    screen.resize(width, 1680)
    screen.show()
    QApplication.processEvents()

    print(f"=== DashboardScreen resized to {width} ===")
    print(f"  screen minimumSizeHint : {screen.minimumSizeHint().width()}")
    print(f"  screen sizeHint        : {screen.sizeHint().width()}")
    print(f"  screen actual width    : {screen.width()}")
    print()
    print("  child                          minW   hintW  actualW")
    layout = screen.layout()
    assert layout is not None
    for i in range(layout.count()):
        item = layout.itemAt(i)
        w = item.widget()
        if w is not None:
            name = type(w).__name__
            extra = f" '{w.text()[:28]}'" if hasattr(w, "text") and w.text() else ""
            print(
                f"  {name + extra:<30} {w.minimumSizeHint().width():>5}"
                f" {w.sizeHint().width():>7} {w.width():>8}"
            )
        else:
            sub = item.layout()
            if sub is not None:
                print(
                    f"  {'(sub-layout ' + type(sub).__name__ + ')':<30}"
                    f" {sub.minimumSize().width():>5} {sub.sizeHint().width():>7}"
                )
    print()
    panel = screen.balances_panel
    body = panel.broker_body
    if body is None:
        print("  broker body hidden at this level")
        return
    cells = (
        panel.buying_power,
        panel.short_value,
        panel.initial_margin,
        panel.maintenance_margin,
        panel.day_trades,
    )
    print(f"  balances panel width   : {panel.width()}")
    print(f"  cell                        x_in_screen    w   past {width}?")
    for cell in cells:
        x = cell.mapTo(screen, cell.rect().topLeft()).x()
        over = "  <-- OFF SCREEN" if x + cell.width() > width else ""
        print(f"  {cell.label_text:<24} {x:>10} {cell.width():>6}{over}")


def main() -> None:
    QApplication(sys.argv)
    panel_alone(SCREEN)
    print()
    dashboard(SCREEN)


if __name__ == "__main__":
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
