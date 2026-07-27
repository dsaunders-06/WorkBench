"""Bundle a session's artefacts into one zip for a post-mortem (spec M20).

Everything here already exists on disk; the value is not the data but the
gathering. After a session the evidence is spread across six files and a log
directory, and the moment you most want it is the moment you are least
inclined to go looking - the day after something behaved oddly.

Deliberately a copy, never a move. The application keeps appending to these
files, and an export that took them away would break the running session it
was trying to explain.
"""

from __future__ import annotations

import logging
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from qat.logging import LOG_DIRNAME

logger = logging.getLogger(__name__)

EXPORT_DIRNAME = "exports"

# Every artefact worth having, and what it answers. A missing file is normal -
# no autonomous decisions means no journal - so absence is reported rather
# than treated as an error.
BUNDLED_FILES = (
    ("closed_trades.csv", "what was traded and what it made"),
    ("equity_curve.csv", "how the account value moved"),
    ("decision_journal.csv", "every order decision and its reason"),
    ("risk_decisions.csv", "how the risk engine sized or refused each order"),
    ("daily_reports.md", "the end-of-day reports"),
    ("weekly_reports.md", "the end-of-week reports"),
    ("equity_state.json", "the day-start equity the rails measure against"),
    ("report_state.json", "which reports have already been written"),
)


@dataclass(frozen=True, slots=True)
class ExportResult:
    path: Path
    included: tuple[str, ...]
    missing: tuple[str, ...]
    log_files: int

    def summary_line(self) -> str:
        parts = [f"{len(self.included)} file(s)"]
        if self.log_files:
            parts.append(f"{self.log_files} log file(s)")
        if self.missing:
            parts.append(f"{len(self.missing)} not present")
        return f"Exported {', '.join(parts)} to {self.path.name}"


def export_session(
    data_dir: str | Path,
    destination: str | Path | None = None,
    now: datetime | None = None,
) -> ExportResult:
    """Zip the session artefacts. Returns what went in and what was absent."""
    source = Path(data_dir)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    out_dir = Path(destination) if destination is not None else source / EXPORT_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"qat-session-{stamp}.zip"

    included: list[str] = []
    missing: list[str] = []
    log_files = 0

    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, _purpose in BUNDLED_FILES:
            path = source / name
            if path.is_file():
                bundle.write(path, arcname=name)
                included.append(name)
            else:
                missing.append(name)

        log_dir = source / LOG_DIRNAME
        if log_dir.is_dir():
            for log_path in sorted(log_dir.glob("qat.log*")):
                bundle.write(log_path, arcname=f"{LOG_DIRNAME}/{log_path.name}")
                log_files += 1

        bundle.writestr("MANIFEST.txt", _manifest(stamp, included, missing, log_files))

    logger.info("Session exported to %s", archive)
    return ExportResult(
        path=archive,
        included=tuple(included),
        missing=tuple(missing),
        log_files=log_files,
    )


def _manifest(stamp: str, included: list[str], missing: list[str], log_files: int) -> str:
    """A plain-text index, so the zip explains itself months later."""
    purposes = dict(BUNDLED_FILES)
    lines = [
        "Quant Advisory Terminal - session export",
        f"Created: {stamp} UTC",
        "",
        "Included:",
    ]
    lines += [f"  {name} - {purposes.get(name, '')}" for name in included]
    lines += [f"  {LOG_DIRNAME}/ - {log_files} application log file(s)"] if log_files else []
    if missing:
        lines += [
            "",
            "Not present (normal when a feature was unused this session):",
            *[f"  {name} - {purposes.get(name, '')}" for name in missing],
        ]
    return "\n".join(lines) + "\n"
