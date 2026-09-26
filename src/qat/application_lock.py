"""Process ownership of QAT's operational data, independent of stale files."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import TracebackType
from typing import BinaryIO

from qat.paths import app_dir


class ApplicationLockUnavailable(RuntimeError):
    """Another process owns the application lock, or OS locking failed."""


def _lock_one_byte(handle: BinaryIO) -> None:
    handle.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_one_byte(handle: BinaryIO) -> None:
    handle.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class ApplicationLock:
    """Hold an OS lock until release, close, or process death.

    acquire/release are idempotent; use a single, non-nested critical section
    per instance. The file persists: deleting it can split ownership on POSIX.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else app_dir() / "application.lock"
        self._handle: BinaryIO | None = None

    def acquire(self) -> None:
        if self._handle is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            # Do not read byte zero: a Windows owner's byte-range lock denies
            # that read before the contender can attempt nonblocking locking.
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"0")
                handle.flush()
            try:
                _lock_one_byte(handle)
            except OSError as exc:
                raise ApplicationLockUnavailable(str(self.path)) from exc
        except BaseException:
            handle.close()
            raise
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        try:
            _unlock_one_byte(handle)
        finally:
            handle.close()

    def __enter__(self) -> ApplicationLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()
