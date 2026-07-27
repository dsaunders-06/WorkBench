"""Structured JSON logging with secret redaction.

Every log record is emitted as a single JSON line. The value of any secret
previously requested via security.get_secret() is redacted if it appears
in a log message, regardless of which record emits it.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from qat.security import known_secret_names

_REDACTED = "***REDACTED***"

LOG_DIRNAME = "logs"
LOG_FILENAME = "qat.log"
# Ten files of five megabytes: enough to cover several sessions of debate about
# what happened, without letting a chatty loop fill the disk.
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 10


class RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact(str(record.msg))
        if record.args:
            record.args = self._redact_args(record.args)
        return True

    def _redact_args(
        self, args: tuple[object, ...] | Mapping[str, object]
    ) -> tuple[object, ...] | Mapping[str, object]:
        """Redacts string arguments and leaves every other type untouched.

        Coercing all arguments to str looks harmless but silently destroys
        numeric format specifiers: "%.2f" % "100000.0" raises TypeError, the
        record then fails to format, and the line is *dropped* in favour of a
        stderr traceback. Only a str can contain a secret anyway, so there is
        nothing to gain by stringifying the rest.

        Mapping args (the %(name)s style) are preserved as a mapping - the
        previous tuple() comprehension iterated a dict's keys and threw the
        values away.
        """
        if isinstance(args, Mapping):
            return {
                key: self._redact(value) if isinstance(value, str) else value
                for key, value in args.items()
            }
        return tuple(self._redact(a) if isinstance(a, str) else a for a in args)

    def _redact(self, text: str) -> str:
        for secret in known_secret_names():
            value = None
            try:
                from qat.security import get_secret

                value = get_secret(secret)
            except Exception:  # pragma: no cover - defensive
                value = None
            if value:
                text = text.replace(value, _REDACTED)
        return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", data_dir: str | Path | None = None) -> None:
    """Log to stdout and, when a data_dir is given, to a rotating file.

    The file handler is not optional in practice (spec M20). The packaged
    build is --windowed, which means it has no console, so a stdout-only
    configuration discarded every line the moment the application was run the
    way it is actually shipped: session transitions, degraded-feed warnings,
    staleness, kill-switch trips and sign-off rejections all went nowhere. The
    logging was never the problem; nothing was reading it.

    Both handlers carry the redaction filter. A secret must not reach the
    console, and it must certainly not be written to a file that outlives the
    process.
    """
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactSecretsFilter())
    root.addHandler(handler)

    if data_dir is None:
        return

    try:
        log_dir = Path(data_dir) / LOG_DIRNAME
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / LOG_FILENAME,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(JsonFormatter())
        file_handler.addFilter(RedactSecretsFilter())
        root.addHandler(file_handler)
    except OSError:
        # An unwritable log directory must not stop the application starting.
        # stdout still has a handler, so this degrades rather than fails.
        root.warning("Could not open the log file in %s; logging to stdout only", data_dir)
    else:
        root.info("Logging to %s", log_dir / LOG_FILENAME)
