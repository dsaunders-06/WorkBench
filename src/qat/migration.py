"""One-time move of settings and records into the app directory (spec M22).

Three rules, and the reasoning matters more than the code.

**Copy, never move.** The source may be a repository checkout, or the folder a
build was unzipped into, and this runs automatically at startup without asking.
Removing a file the operator did not know was about to be touched is not a
migration, it is data loss with a helpful name. The originals are left exactly
where they were; a stale copy is a tidiness problem, a deleted ledger is not.

**Never overwrite.** If the destination already has a file, it is the live one
and this is an older stray. Migration must not be able to make a first run
worse than no migration at all.

**Say what happened.** A silent migration and a silent no-op look identical
from the outside, and the whole reason this exists is that the previous
behaviour was invisible.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from qat.paths import app_dir, data_dir, env_path

logger = logging.getLogger(__name__)

LEGACY_ENV_NAME = ".env"
LEGACY_DATA_DIRNAME = "data"


@dataclass
class MigrationResult:
    env_migrated_from: Path | None = None
    files_copied: list[str] = field(default_factory=list)
    skipped_existing: list[str] = field(default_factory=list)

    @property
    def did_anything(self) -> bool:
        return self.env_migrated_from is not None or bool(self.files_copied)

    def summary_line(self) -> str:
        if not self.did_anything:
            return f"No migration needed; using {app_dir()}"
        parts = []
        if self.env_migrated_from is not None:
            parts.append(f"settings from {self.env_migrated_from}")
        if self.files_copied:
            parts.append(f"{len(self.files_copied)} data file(s)")
        note = ""
        if self.skipped_existing:
            note = f" ({len(self.skipped_existing)} already present, left alone)"
        return f"Migrated {' and '.join(parts)} into {app_dir()}{note}"


def migrate_legacy_layout(source: Path | None = None) -> MigrationResult:
    """Bring a working-directory .env and data/ into the app directory.

    `source` defaults to the process working directory, which is the checkout
    when run from source and the unpack folder when run from the packaged
    build - the two places the old layout could have left things.
    """
    origin = Path(source) if source is not None else Path.cwd()
    result = MigrationResult()

    destination = app_dir()
    if origin.resolve() == destination.resolve():
        return result  # already living there; nothing to do

    destination.mkdir(parents=True, exist_ok=True)
    _migrate_env(origin, result)
    _migrate_data(origin, result)

    if result.did_anything:
        logger.info("%s", result.summary_line())
        logger.info(
            "The original files were copied, not moved - %s still holds them, and they are "
            "no longer read.",
            origin,
        )
    return result


def _migrate_env(origin: Path, result: MigrationResult) -> None:
    legacy = origin / LEGACY_ENV_NAME
    target = env_path()
    if not legacy.is_file():
        return
    if target.exists():
        result.skipped_existing.append(LEGACY_ENV_NAME)
        return
    try:
        shutil.copy2(legacy, target)
    except OSError:
        logger.warning("Could not copy %s to %s", legacy, target, exc_info=True)
        return
    result.env_migrated_from = legacy


def _migrate_data(origin: Path, result: MigrationResult) -> None:
    legacy = origin / LEGACY_DATA_DIRNAME
    target = data_dir()
    if not legacy.is_dir():
        return

    for path in sorted(legacy.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(legacy)
        destination = target / relative
        if destination.exists():
            result.skipped_existing.append(str(relative))
            continue
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        except OSError:
            logger.warning("Could not copy %s to %s", path, destination, exc_info=True)
            continue
        result.files_copied.append(str(relative))
