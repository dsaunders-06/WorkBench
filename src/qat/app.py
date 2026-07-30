"""Application entrypoint.

Wires config -> logging -> Runtime (EventBus/Orchestrator/full engine graph)
-> Qt window, running the asyncio loop under Qt via qasync so the UI never
blocks on I/O (spec §K).
"""

from __future__ import annotations

import asyncio
import logging
import sys

import qasync
from PySide6.QtWidgets import QApplication

from qat.config import Settings
from qat.logging import configure_logging
from qat.migration import migrate_legacy_layout
from qat.paths import ensure_app_dir
from qat.presentation.main_window import MainWindow
from qat.presentation.runtime import Runtime
from qat.version import build_info

logger = logging.getLogger(__name__)


def main() -> None:
    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    # Settings first, then logging, then the runtime. build_demo resolves the
    # broker, the market data source and the fundamentals source, and warns
    # loudly when any of them degrades - logging afterwards discarded exactly
    # the messages most worth having.
    # Before Settings is constructed: migration may supply the very .env that
    # Settings is about to read.
    ensure_app_dir()
    migration = migrate_legacy_layout()

    settings = Settings()
    configure_logging(settings.log_level, settings.data_dir)
    logger.info("%s", migration.summary_line())
    # First line after migration, because every question asked of a session log
    # afterwards starts with "which build produced this?" - and until M27b
    # nothing recorded it, so answering it meant inferring from which messages
    # happened to be present.
    logger.info("Build: %s", build_info().one_line())
    logger.info(
        "Starting Quant Advisory Terminal in %s mode (%s market, %s broker)",
        settings.trading_mode,
        settings.market,
        settings.broker,
    )

    runtime = Runtime.build_demo(settings=settings)

    window = MainWindow(runtime)
    window.show()

    with loop:
        loop.run_until_complete(runtime.orchestrator.start_all())
        loop.run_forever()


if __name__ == "__main__":
    main()
