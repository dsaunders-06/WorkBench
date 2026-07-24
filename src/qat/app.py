"""Application entrypoint.

Wires config -> logging -> EventBus/Orchestrator -> Qt window, running the
asyncio loop under Qt via qasync so the UI never blocks on I/O (spec §K).
"""

from __future__ import annotations

import asyncio
import logging
import sys

import qasync
from PySide6.QtWidgets import QApplication

from qat.config import Settings
from qat.domain.bus import EventBus
from qat.domain.orchestrator import Orchestrator
from qat.logging import configure_logging
from qat.presentation.main_window import MainWindow

logger = logging.getLogger(__name__)


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    logger.info("Starting Quant Advisory Terminal in %s mode", settings.trading_mode)

    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    bus = EventBus()
    orchestrator = Orchestrator(bus)

    window = MainWindow(settings)
    window.show()

    with loop:
        loop.run_until_complete(orchestrator.start_all())
        loop.run_forever()


if __name__ == "__main__":
    main()
