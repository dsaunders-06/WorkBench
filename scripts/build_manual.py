"""Regenerate docs/Quant_Advisory_Terminal_User_Manual.docx.

The first edition of this manual was built by a throwaway script that was never
committed, so the document drifted six milestones behind the application with
no way to tell which parts were still true. This script is the fix: the manual
is a build artefact, and its figures are captured from the real widgets rather
than pasted in by hand, so a screen that changes shape shows up here.

Run it with:

    python scripts/build_manual.py

Everything runs against Runtime.build_demo() on synthetic sources - no network,
no broker, no API keys - so the figures are reproducible and contain no real
account data. Every number visible in a figure is therefore demo data, and the
captions say so.

This module captures the figures; scripts/manual_body.py writes the prose.
"""

from __future__ import annotations

import asyncio
import random
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402
from docx import Document  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from qat.config import Settings  # noqa: E402
from qat.data.broker.adapter import Order  # noqa: E402
from qat.domain.events import MarketDataEvent, OrderFilledEvent, RegimeEvent  # noqa: E402
from qat.domain.risk_engine.engine import OrderCandidate  # noqa: E402
from qat.presentation.ai_advisor import AiAdvisorScreen  # noqa: E402
from qat.presentation.blotter import BlotterScreen  # noqa: E402
from qat.presentation.dashboard import DashboardScreen  # noqa: E402
from qat.presentation.main_window import MainWindow  # noqa: E402
from qat.presentation.performance import PerformanceScreen  # noqa: E402
from qat.presentation.regime_monitor import RegimeMonitorScreen  # noqa: E402
from qat.presentation.risk_console import RiskConsoleScreen  # noqa: E402
from qat.presentation.runtime import Runtime  # noqa: E402
from qat.presentation.screener import ScreenerScreen  # noqa: E402
from qat.presentation.settings import SettingsScreen  # noqa: E402
from qat.presentation.workbench import WorkbenchScreen  # noqa: E402
from scripts.manual_body import style_document, title_page, write_body  # noqa: E402

OUTPUT = REPO_ROOT / "docs" / "Quant_Advisory_Terminal_User_Manual.docx"
FIGURE_DIR = REPO_ROOT / "docs" / "_figures"
SCREEN_SIZE = (1280, 820)


@dataclass(frozen=True)
class Figure:
    key: str
    path: Path
    caption: str


class FigureSet:
    """Captured figures, looked up by key when the document is written.

    A missing key raises rather than silently omitting an image: a manual that
    quietly loses a figure is exactly the drift this script exists to prevent.
    """

    def __init__(self) -> None:
        self._figures: dict[str, Figure] = {}

    def add(
        self, key: str, widget: QWidget, caption: str, size: tuple[int, int] | None = None
    ) -> None:
        FIGURE_DIR.mkdir(parents=True, exist_ok=True)
        path = FIGURE_DIR / f"{key}.png"
        # Some screens stack more than fits the default height; grabbing them
        # short squashes the charts into unreadable slivers.
        widget.resize(*(size or SCREEN_SIZE))
        widget.show()
        _pump()
        widget.grab().save(str(path))
        widget.hide()
        self._figures[key] = Figure(key=key, path=path, caption=caption)

    def __getitem__(self, key: str) -> Figure:
        return self._figures[key]


def _pump(times: int = 5) -> None:
    for _ in range(times):
        QApplication.processEvents()


async def _seed_positions(runtime: Runtime) -> None:
    """Fill a few entries at the broker so the portfolio screens are not empty.

    Placed through the broker rather than poked into its dictionaries, so the
    positions, cash and NAV a figure shows are the ones the real accounting
    produces.
    """
    for index, (symbol, quantity) in enumerate((("SPY", 120), ("AAPL", 60), ("MSFT", 25))):
        await runtime.broker.place_order(
            Order(
                symbol=symbol,
                side="buy",
                quantity=quantity,
                order_id=f"demo-entry-{index}",
                strategy="trend_following",
            )
        )


async def _seed_pending_orders(runtime: Runtime) -> None:
    """Put orders in front of the sign-off gate for the Blotter figure.

    Routed through OMS.submit_order so they are sized and gated exactly as a
    live signal would be - a hand-built pending order would show a state the
    application cannot actually reach.
    """
    returns = pd.Series([0.004, -0.006, 0.009, -0.003, 0.007, 0.002, -0.005, 0.006])
    account = await runtime.broker.account()
    for symbol, side in (("GOOGL", "buy"), ("AAPL", "buy"), ("SPY", "sell")):
        await runtime.oms.submit_order(
            OrderCandidate(
                symbol=symbol,
                side=side,  # type: ignore[arg-type]
                price=100.0,
                atr=1.8,
                win_rate=0.55,
                win_loss_ratio=1.4,
                candidate_returns=returns,
                strategy="trend_following",
            ),
            equity=account.net_liquidation,
            existing_weights={},
            existing_returns={},
        )


async def _feed_prices(risk: RiskConsoleScreen, runtime: Runtime, points: int = 40) -> None:
    """Give the Risk Console enough price history for a real correlation table.

    It buffers ticks and recomputes on a timer, so a freshly-built screen has
    nothing to correlate and would render an empty grid. Prices are a seeded
    walk per symbol - deterministic, so the figure is stable between runs.
    """
    rng = random.Random(20260726)
    levels = {symbol: 100.0 + index * 7 for index, symbol in enumerate(runtime.watchlist)}
    for _ in range(points):
        for symbol in runtime.watchlist:
            levels[symbol] *= 1.0 + rng.gauss(0.0, 0.004)
            await risk._on_market_data(
                MarketDataEvent(symbol=symbol, price=levels[symbol], volume=1_000.0)
            )


async def _seed_trade_history(runtime: Runtime) -> None:
    """Publish fills through the bus so the ledger builds real closed trades.

    Injecting rows into TradeLedger._closed directly would produce a figure of
    a code path that does not exist. Going through the bus exercises the same
    lot matching the running app uses.
    """
    # build_demo wires the graph but does not start it, so the ledger has not
    # subscribed to fills yet and would record nothing.
    await runtime.trade_ledger.start()

    start = datetime.now(UTC) - timedelta(days=6)
    script = (
        ("AAPL", "trend_following", 40, 188.40, 194.10),
        ("MSFT", "trend_following", 25, 402.10, 397.55),
        ("SPY", "mean_reversion", 60, 541.20, 546.80),
        ("GOOGL", "mean_reversion", 30, 176.55, 172.90),
        ("AAPL", "trend_following", 35, 190.10, 196.25),
    )
    equity = 100_000.0
    for index, (symbol, strategy, qty, entry, exit_price) in enumerate(script):
        for side, price in (("buy", entry), ("sell", exit_price)):
            await runtime.bus.publish(
                OrderFilledEvent(
                    order_id=f"demo-{side}-{index}",
                    symbol=symbol,
                    side=side,  # type: ignore[arg-type]
                    quantity=qty,
                    price=price,
                    strategy=strategy,
                )
            )
        equity += (exit_price - entry) * qty
        runtime.equity_curve.record(
            equity=equity, cash=equity * 0.4, ts=start + timedelta(days=index)
        )


async def capture_figures() -> FigureSet:
    figures = FigureSet()
    runtime = Runtime.build_demo(settings=Settings(_env_file=None))

    window = MainWindow(runtime)
    figures.add(
        "banner_paper",
        window,
        "Figure 2.1 - Paper mode. The green banner reads MODE: PAPER and cannot be hidden "
        "or dismissed. Every figure in this manual shows demo data.",
    )

    live_window = MainWindow(
        Runtime.build_demo(settings=Settings(_env_file=None, trading_mode="live"))
    )
    figures.add(
        "banner_live",
        live_window,
        "Figure 2.2 - Live mode. The same window with the banner switched to solid red. "
        "Live mode requires a deliberate configuration change; it is never the default.",
    )

    # Pending orders first, while cash is untouched: the same buys submitted after
    # the entries below are correctly rejected by the cash rule, which is right
    # behaviour but makes for a one-row figure of a screen about reviewing many.
    await _seed_pending_orders(runtime)
    await _seed_positions(runtime)

    dashboard = DashboardScreen(runtime)
    for _ in range(25):
        await dashboard._refresh()
    await dashboard._on_regime(
        RegimeEvent(
            label="high_vol",
            probs={"high_vol": 0.52, "bear": 0.21, "bull": 0.14, "low_vol": 0.13},
            exposure_scalar=0.6,
        )
    )
    figures.add(
        "dashboard",
        dashboard,
        "Figure 3.1 - The Dashboard: NAV and risk tiles, the live equity curve, open "
        "positions, and an AI regime note awaiting acknowledgement.",
    )

    workbench = WorkbenchScreen(runtime)
    await workbench._run_backtest()
    await workbench._run_walk_forward()
    figures.add(
        "workbench",
        workbench,
        "Figure 4.1 - A completed backtest and walk-forward: equity versus benchmark, the "
        "ten-metric panel, the Monte Carlo cone, and the per-window out-of-sample table.",
        size=(1280, 1150),
    )

    regime = RegimeMonitorScreen(runtime)
    await regime._on_regime(
        RegimeEvent(
            label="high_vol",
            probs={
                "bull": 0.08,
                "bear": 0.18,
                "high_vol": 0.46,
                "low_vol": 0.10,
                "recession": 0.06,
                "recovery": 0.07,
                "sideways": 0.05,
            },
            exposure_scalar=0.6,
        )
    )
    figures.add(
        "regime",
        regime,
        "Figure 5.1 - The Regime Monitor: the probability distribution across all seven "
        "states, the feature drivers behind it, and the transition history.",
    )

    risk = RiskConsoleScreen(runtime)
    await _feed_prices(risk, runtime)
    risk._on_timer_tick()
    figures.add(
        "risk_console",
        risk,
        "Figure 6.1 - The Risk Console: an inactive (green) kill-switch, live VaR, Expected "
        "Shortfall and concentration tiles, and the correlation table.",
    )

    advisor = AiAdvisorScreen(runtime)
    await advisor._ask("Is the current regime supportive of adding to AAPL?")
    figures.add(
        "ai_advisor",
        advisor,
        "Figure 7.1 - The AI Advisor after a research question, showing the recommendation, "
        "its confidence, and any risk flags.",
    )

    blotter = BlotterScreen(runtime)
    blotter._timer_refresh()
    figures.add(
        "blotter",
        blotter,
        "Figure 8.1 - The Order Blotter, filtered to orders awaiting sign-off. Sign Off and "
        "Reject act on every selected row; the confirmation dialog itemises them.",
    )

    screener = ScreenerScreen(runtime)
    await screener._run_screen()
    figures.add(
        "screener",
        screener,
        "Figure 9.1 - The Screener after a run against the US curated watchlist: sector, "
        "fundamentals and the technical trend read for each candidate.",
    )

    await _seed_trade_history(runtime)
    performance = PerformanceScreen(runtime)
    performance.refresh()
    figures.add(
        "performance",
        performance,
        "Figure 10.1 - The Performance screen: promotion status per strategy, the "
        "closed-trade ledger, and the generated daily and weekly reports.",
    )

    settings_screen = SettingsScreen(runtime)
    figures.add(
        "settings",
        settings_screen,
        "Figure 11.1 - Settings: AI provider selection, market and watchlist, broker and "
        "cash reserve, market data source, and execution mode.",
    )

    return figures


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    figures = asyncio.run(capture_figures())

    doc = Document()
    style_document(doc)
    title_page(doc)
    write_body(doc, figures)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(OUTPUT))
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)}")
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
