r"""Change QAT_IBKR_PORT in the live .env. Dry-run by default.

    .\.venv\Scripts\python.exe scripts\set_ibkr_port.py 7497
    .\.venv\Scripts\python.exe scripts\set_ibkr_port.py 7497 --apply

⚠️ **RUN FROM POWERSHELL, NEVER BASH.** It writes to
`%LOCALAPPDATA%\QuantAdvisoryTerminal\.env`. The Bash sandbox serves a frozen
snapshot and does NOT error, so a "successful" run from there would leave the
real file untouched and report otherwise.

## Why a script rather than an editor

Because this file decides which IBKR session the application reaches, and an
inline edit is how a wrong port gets in without a backup or a record. The port
is the ONE setting that can put orders somewhere other than where the operator
thinks they are going, which is why `ib_adapter` carries a refusal for it.

## What it refuses

* **A LIVE port while `QAT_TRADING_MODE=paper`** - 4001 (Gateway) and 7496
  (TWS). This is `ib_adapter._LIVE_PORTS` enforced at the point of WRITING as
  well as at the point of connecting, because a config file that has been wrong
  since last night is worse than a connection that fails now.
* **A port that is neither live nor a known paper port**, since a typo that
  reaches nothing looks identical to a Gateway that is simply down.
* **Writing while the application is running.** The app reads `.env` at startup;
  changing it underneath a live session means the file and the running process
  disagree, and the next person to read the file learns the wrong thing about
  what actually connected.

Backs the file up to `.env.bak-<timestamp>` before writing, matching the
existing `.env.bak-*` convention in that directory.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from qat.data.broker.ib_adapter import _LIVE_PORTS, _PAPER_PORTS  # noqa: E402
from qat.paths import env_path  # noqa: E402

_KEY = "QAT_IBKR_PORT"
_MODE_KEY = "QAT_TRADING_MODE"
_APP_PROCESS = "QuantAdvisoryTerminal"


def _app_is_running() -> bool | None:
    """Same refusal `deploy.ps1` opens with, for the same reason.

    ⚠️ RETURNS None FOR "COULD NOT TELL", AND THE CALLER REFUSES ON IT. The
    first version of this imported `psutil` and returned False on ImportError.
    `psutil` is not in this venv, so the guard reported "not running" with the
    app live at PID 33668 - it was decorative, and it would have let the port
    change through under a running session exactly when it mattered.

    That is this project's most-repeated defect in a new place: `probe_halts.py`
    ended with a hardcoded "The market is SHUT" that printed during continuous
    trading, and `session_check.ps1` asserted an aggregate cap breach it never
    measured. An instrument that cannot see must SAY SO, never report all-clear.

    `tasklist` rather than `psutil`: it ships with Windows, so the check cannot
    be disabled by a missing dependency.
    """
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
            ["tasklist", "/FI", f"IMAGENAME eq {_APP_PROCESS}.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return _APP_PROCESS.lower() in out.stdout.lower()


def _read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _value_of(lines: list[str], key: str) -> str | None:
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}="):
            return stripped.split("=", 1)[1].strip()
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("port", type=int)
    parser.add_argument("--apply", action="store_true", help="actually write; default is a report")
    args = parser.parse_args()

    path = env_path()
    if path is None or not path.exists():
        print(f"REFUSED: no .env found at {path}")
        return 1

    lines = _read(path)
    current = _value_of(lines, _KEY)
    mode = _value_of(lines, _MODE_KEY) or "paper"

    print(f".env         : {path}")
    print(f"trading mode : {mode}")
    print(f"{_KEY:<13}: {current} -> {args.port}")
    known = ", ".join(f"{p} (paper {n})" for p, n in _PAPER_PORTS.items())

    if mode != "live" and args.port in _LIVE_PORTS:
        print(
            f"\nREFUSED: {args.port} reaches a LIVE IBKR session while trading mode is "
            f"{mode!r}.\n         Real orders would be within reach while every is_live "
            f"consumer\n         in the app reads 'paper'. Use {known}."
        )
        return 1

    if args.port not in _PAPER_PORTS and args.port not in _LIVE_PORTS:
        print(
            f"\nREFUSED: {args.port} is not a known IBKR port. A typo that reaches "
            f"nothing\n         looks exactly like a Gateway that is down. Known: {known}."
        )
        return 1

    if current == str(args.port):
        print("\nNothing to do - already set.")
        return 0

    running = _app_is_running()
    if running is None:
        print(
            "\nREFUSED: could not determine whether the app is running, so this "
            "refuses\n         rather than assuming it is not. Check by hand and "
            "re-run."
        )
        return 1
    if running:
        print(
            "\nREFUSED: the app is running. It reads .env at startup, so changing it "
            "now\n         would leave the file and the live process disagreeing about "
            "which\n         session is connected. Close the app first."
        )
        return 1

    if not args.apply:
        print("\nDRY RUN - nothing written. Re-run with --apply to make the change.")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f".env.bak-{stamp}")
    shutil.copy2(path, backup)

    out = [f"{_KEY}={args.port}" if line.strip().startswith(f"{_KEY}=") else line for line in lines]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")

    # Read BACK rather than trust the write. Every deploy in this project that
    # went wrong went wrong by reporting an intention as an outcome.
    confirmed = _value_of(_read(path), _KEY)
    print(f"\nbacked up to : {backup.name}")
    print(f"read back    : {_KEY}={confirmed}")
    if confirmed != str(args.port):
        print("⚠️ READ-BACK DISAGREES WITH THE WRITE. Restore from the backup above.")
        return 1
    print("✅ written and verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
