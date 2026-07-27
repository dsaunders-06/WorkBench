"""Where the application keeps its settings and its records (spec M22).

Until M22 both were resolved relative to the process working directory: the
Settings screen wrote ".env" and the data directory defaulted to "./data". Run
from a source checkout that meant the repository; run from the packaged build
it meant wherever the zip happened to be unpacked. Three consequences, all of
them found the hard way:

  * The same installation could read two different configurations depending on
    how it was started, and neither was discoverable from the other.
  * Every new build shipped as a fresh folder started with no settings, and the
    previous ones were stranded where they lay.
  * An edit made to the checkout's .env had no effect on the packaged app the
    operator was actually running - and looked, from the outside, like it had
    worked.

Settings and records now live in one per-user directory that does not move when
the executable does. QAT_HOME overrides it, which is what the test suite uses
and what a genuinely portable install would set.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIRNAME = "QuantAdvisoryTerminal"

# Set this to relocate everything - config, data, logs, journals. Absolute
# paths only; a relative one would reintroduce the very problem this module
# exists to remove.
HOME_ENV_VAR = "QAT_HOME"


def app_dir() -> Path:
    """The per-user directory holding config and data.

    Windows is the target platform, so LOCALAPPDATA leads; the other branches
    keep the module honest on developer machines rather than claiming
    cross-platform support the app has never been tested for.
    """
    override = os.environ.get(HOME_ENV_VAR)
    if override:
        return Path(override).expanduser()

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME")
        root = Path(base) if base else Path.home() / ".local" / "share"

    return root / APP_DIRNAME


def env_path() -> Path:
    """The .env the Settings screen writes and pydantic-settings reads."""
    return app_dir() / ".env"


def data_dir() -> Path:
    """Trade ledger, equity curve, journals, reports, logs and exports."""
    return app_dir() / "data"


def ensure_app_dir() -> Path:
    """Create the directory if it does not exist, and return it.

    A failure here is not fatal and is deliberately not caught: it happens once
    at startup, before anything has been written, and an application that
    cannot create its own storage should say so immediately rather than run and
    silently discard every record it makes.
    """
    directory = app_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory
