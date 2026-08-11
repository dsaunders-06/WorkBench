r"""Render the Balances panel to PNG so the fix can be LOOKED at (M87).

Six tests pass on the elision fix. Every test passed through the defect it
fixes, so passing tests are not the evidence that matters here - the screenshot
is. This renders the panel at several widths, including one narrow enough to
force elision, so the degradation can be seen rather than asserted.

    .\.venv\Scripts\python.exe scripts\analysis\render_balances_panel.py
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from qat.data.broker.account_poller import AccountSnapshot  # noqa: E402
from qat.data.broker.adapter import AccountBalances  # noqa: E402
from qat.presentation.balances_panel import BalancesPanel  # noqa: E402
from qat.presentation.ui_level import UiLevel  # noqa: E402

# The live account's own figures, so the widths are the real ones.
LIVE = AccountBalances(
    equity=101_363.38,
    last_equity=101_754.81,
    cash=44_410.93,
    long_market_value=56_952.45,
    short_market_value=0.0,
    buying_power=337_110.59,
    multiplier=4.0,
    initial_margin=28_476.23,
    maintenance_margin=17_085.74,
    currency="USD",
    status="ACTIVE",
    daytrade_count=None,
    pattern_day_trader=None,
)

OUT = "C:/Claude Programming/dist"


def main() -> None:
    app = QApplication(sys.argv)
    for width in (3072, 1214, 700):
        panel = BalancesPanel(1000.0, level=UiLevel.PROFESSIONAL)
        panel.resize(width, 190)
        panel.show()
        panel.update_from(
            AccountSnapshot(
                summary=None,
                balances=LIVE,
                positions=(),
                taken_at=datetime.now(UTC),
                error=None,
            )
        )
        layout = panel.layout()
        if layout is not None:
            layout.activate()
        app.processEvents()

        cells = (
            panel.buying_power,
            panel.short_value,
            panel.initial_margin,
            panel.maintenance_margin,
            panel.day_trades,
        )
        print(f"=== {width}px ===")
        for cell in cells:
            x = cell.mapTo(panel, cell.rect().topLeft()).x()
            right = x + cell.width()
            flag = "  PAST EDGE" if right > panel.width() else ""
            print(
                f"  {cell.label_text:<24} x={x:<5} w={cell.width():<5}"
                f" shows {cell.rendered_label()!r}{flag}"
            )
        path = f"{OUT}/balances-{width}.png"
        panel.grab().save(path)
        print(f"  -> {path}")


if __name__ == "__main__":
    main()
