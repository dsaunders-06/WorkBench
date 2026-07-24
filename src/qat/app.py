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

from qat.logging import configure_logging
from qat.presentation.main_window import MainWindow
from qat.presentation.runtime import Runtime

logger = logging.getLogger(__name__)


def main() -> None:
    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    runtime = Runtime.build_demo()
    configure_logging(runtime.settings.log_level)
    logger.info("Starting Quant Advisory Terminal in %s mode", runtime.settings.trading_mode)

    window = MainWindow(runtime)
    window.show()

    with loop:
        loop.run_until_complete(runtime.orchestrator.start_all())
        loop.run_forever()


if __name__ == "__main__":
    main()
