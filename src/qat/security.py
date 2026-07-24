"""Secret access via the OS keyring. Secrets are never logged or echoed.

Falls back to environment variables only for local dev convenience; production
use should rely on the OS keyring exclusively.
"""

from __future__ import annotations

import os

import keyring

_SERVICE_NAME = "qat"
_known_secret_names: set[str] = set()


def get_secret(name: str) -> str | None:
    """Read a secret by name from the OS keyring, falling back to env vars."""
    _known_secret_names.add(name)
    value = keyring.get_password(_SERVICE_NAME, name)
    if value is not None:
        return value
    return os.environ.get(name)


def set_secret(name: str, value: str) -> None:
    keyring.set_password(_SERVICE_NAME, name, value)
    _known_secret_names.add(name)


def known_secret_names() -> frozenset[str]:
    """Secret names that have been requested; used by logging redaction."""
    return frozenset(_known_secret_names)
