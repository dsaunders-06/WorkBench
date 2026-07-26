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
from typing import Any

from qat.security import known_secret_names

_REDACTED = "***REDACTED***"


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


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactSecretsFilter())
    root.addHandler(handler)
