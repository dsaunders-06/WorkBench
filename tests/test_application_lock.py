from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest

from qat import application_lock
from qat.application_lock import ApplicationLock, ApplicationLockUnavailable


def test_second_owner_is_refused_until_first_releases(tmp_path):
    path = tmp_path / "application.lock"
    with ApplicationLock(path):
        with pytest.raises(ApplicationLockUnavailable), ApplicationLock(path):
            pass
    with ApplicationLock(path):
        pass


@pytest.mark.parametrize("content", [b"", b"stale metadata"])
def test_stale_lock_file_without_owner_is_reusable(tmp_path, content):
    path = tmp_path / "application.lock"
    path.write_bytes(content)
    with ApplicationLock(path):
        assert path.exists()
    assert path.read_bytes() == (content or b"0")


def test_acquire_and_release_are_idempotent_and_instance_can_be_reused(tmp_path):
    path = tmp_path / "application.lock"
    owner = ApplicationLock(path)
    owner.release()
    owner.acquire()
    owner.acquire()
    owner.release()
    owner.release()
    with ApplicationLock(path):
        with pytest.raises(ApplicationLockUnavailable):
            owner.acquire()
    with owner:
        with pytest.raises(ApplicationLockUnavailable), ApplicationLock(path):
            pass


def test_exception_releases_ownership(tmp_path):
    path = tmp_path / "application.lock"
    with pytest.raises(ValueError), ApplicationLock(path):
        raise ValueError("critical section failed")
    with ApplicationLock(path):
        pass


def test_unlock_failure_closes_handle_and_allows_reuse(tmp_path, monkeypatch):
    path = tmp_path / "application.lock"
    owner = ApplicationLock(path)
    owner.acquire()

    def fail_unlock(handle):
        raise OSError("unlock failed")

    with monkeypatch.context() as patch:
        patch.setattr(application_lock, "_unlock_one_byte", fail_unlock)
        with pytest.raises(OSError, match="unlock failed"):
            owner.release()
        owner.release()
    with ApplicationLock(path):
        pass


def test_default_path_uses_app_directory_without_accessing_operational_home(tmp_path, monkeypatch):
    monkeypatch.setattr(application_lock, "app_dir", lambda: tmp_path)
    assert ApplicationLock().path == tmp_path / "application.lock"


def test_process_cannot_acquire_until_owner_releases(tmp_path):
    path = tmp_path / "application.lock"
    code = """
import sys
from pathlib import Path
from qat.application_lock import ApplicationLock, ApplicationLockUnavailable
try:
    with ApplicationLock(Path(sys.argv[1])):
        pass
except ApplicationLockUnavailable:
    sys.exit(23)
"""

    def contender():
        return subprocess.run(
            [sys.executable, "-c", code, str(path)],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    with ApplicationLock(path):
        result = contender()
        assert result.returncode == 23, result.stderr
    result = contender()
    assert result.returncode == 0, result.stderr


def test_app_refuses_before_any_operational_setup(tmp_path, monkeypatch):
    from qat import app

    path = tmp_path / "application.lock"
    monkeypatch.setattr(app, "QApplication", lambda args: object())
    monkeypatch.setattr(app.qasync, "QEventLoop", lambda qt: object())
    monkeypatch.setattr(app.asyncio, "set_event_loop", lambda loop: None)
    monkeypatch.setattr(app, "ApplicationLock", lambda: ApplicationLock(path))
    monkeypatch.setattr(app, "ensure_app_dir", lambda: pytest.fail("setup before ownership"))
    with ApplicationLock(path), pytest.raises(SystemExit, match="already running"):
        app.main()


@pytest.mark.parametrize("fail_in_loop", [False, True])
def test_app_holds_lock_through_migration_engines_loop_and_marker(
    tmp_path, monkeypatch, fail_in_loop
):
    from qat import app

    path = tmp_path / "application.lock"
    events = []

    def checkpoint(name):
        with pytest.raises(ApplicationLockUnavailable), ApplicationLock(path):
            pass
        events.append(name)

    class Loop:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            checkpoint("loop closed")

        def run_until_complete(self, operation):
            checkpoint("engines started")

        def run_forever(self):
            checkpoint("event loop")
            if fail_in_loop:
                raise ValueError("loop failed")

    class Marker:
        def __init__(self, directory):
            pass

        def claim(self):
            checkpoint("marker claimed")

        def release(self):
            checkpoint("marker released")

    def migrate():
        checkpoint("migration")
        return SimpleNamespace(summary_line=lambda: "test migration")

    def build(**kwargs):
        checkpoint("runtime built")
        return SimpleNamespace(orchestrator=SimpleNamespace(start_all=lambda: None))

    monkeypatch.setattr(app, "QApplication", lambda args: object())
    monkeypatch.setattr(app.qasync, "QEventLoop", lambda qt: Loop())
    monkeypatch.setattr(app.asyncio, "set_event_loop", lambda loop: None)
    monkeypatch.setattr(app, "ApplicationLock", lambda: ApplicationLock(path))
    monkeypatch.setattr(app, "ensure_app_dir", lambda: checkpoint("directory"))
    monkeypatch.setattr(app, "migrate_legacy_layout", migrate)
    monkeypatch.setattr(app, "configure_logging", lambda *args: None)
    monkeypatch.setattr(app, "RunMarker", Marker)
    monkeypatch.setattr(app, "Runtime", SimpleNamespace(build_demo=build))
    monkeypatch.setattr(app, "MainWindow", lambda runtime: SimpleNamespace(show=lambda: None))
    monkeypatch.setattr(app, "QTimer", SimpleNamespace(singleShot=lambda *args: None))
    if fail_in_loop:
        with pytest.raises(ValueError, match="loop failed"):
            app.main()
    else:
        app.main()
    assert events == [
        "directory",
        "migration",
        "marker claimed",
        "runtime built",
        "engines started",
        "event loop",
        "loop closed",
        "marker released",
    ]
    with ApplicationLock(path):
        pass
