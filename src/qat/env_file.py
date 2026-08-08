"""Reads and merges KEY=VALUE updates into a .env file (spec M10), preserving
comments and every untouched line - the Settings screen's Save button writes
non-secret configuration here so pydantic-settings' normal env_file loading
picks it up on the next launch (Settings changes are restart-required, not
live-applied - see presentation/settings.py). Secrets never go through this;
qat.security's keyring-backed store is the only place those are written.
"""

from __future__ import annotations

from pathlib import Path

from qat.paths import env_path


def has_key(key: str, path: str | Path | None = None) -> bool:
    """Whether this setting has ever been written down (M58a).

    Distinct from "does Settings have a value for it", which is always true -
    every field has a default. The difference matters for anything that should
    be asked once: `ui_level` defaults to "standard", so an operator who
    deliberately chose Standard and one who has never been asked are
    indistinguishable by value, and only the file can tell them apart.

    A missing or unreadable file reads as "never written", which is the safe
    direction: the cost is asking a question once more than necessary.
    """
    path = Path(path) if path is not None else env_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.split("=", 1)[0].strip() == key:
            return True
    return False


def update_env_file(updates: dict[str, str], path: str | Path | None = None) -> None:
    # Defaults to the app directory rather than a working-directory-relative
    # ".env" (M22): the previous default wrote wherever the process happened to
    # be started, which the next launch might never read.
    path = Path(path) if path is not None else env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    remaining = dict(updates)
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped else None
        if key and not stripped.startswith("#") and key in remaining:
            new_lines.append(f"{key}={remaining.pop(key)}")
        else:
            new_lines.append(line)

    if remaining:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.extend(f"{key}={value}" for key, value in remaining.items())

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
