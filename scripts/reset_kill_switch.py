r"""Clear a tripped kill switch through the app's OWN reset, with a dry run.

    .\.venv\Scripts\python.exe scripts\reset_kill_switch.py            # dry run
    .\.venv\Scripts\python.exe scripts\reset_kill_switch.py --apply    # resets

⚠️ RUN THIS FROM POWERSHELL. It builds `Settings()`, which loads the live data
directory's .env whether or not this script mentions it.

Uses `KillSwitch.reset()` rather than editing `kill_switch.json`, for three
reasons: it is the code path the Risk Console uses, it emits the attributed
WARNING that makes the reset auditable, and it cannot get the on-disk schema
wrong. Hand-editing a safety file to clear a safety state is exactly the shape
this application exists to avoid.

⚠️ **A reset is a judgement, not a chore.** The 26 August rule stands: do not
clear the halt until the discrepancy is absorbed or the ledger is repaired
deliberately. This script prints what it is about to clear so that judgement is
made against the reason rather than against a habit.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.config import Settings  # noqa: E402
from qat.domain.risk_engine.kill_switch import KillSwitch  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="actually reset")
    parser.add_argument("--operator", help="named operator; defaults to QAT_OPERATOR_NAME")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = Settings()
    switch = KillSwitch(settings.data_dir)

    print(f"data dir : {settings.data_dir}")
    print(f"tripped  : {switch.tripped}")
    print(f"reason   : {switch.reason}")

    if not switch.tripped:
        print("\nNothing to do - the switch is already clear.")
        return 0

    if not args.apply:
        print("\nDRY RUN - nothing was changed. Re-run with --apply to clear it.")
        return 0

    operator = (args.operator or getattr(settings, "operator_name", "")).strip()
    if not operator:
        print("\nRESET FAILED: configure an operator name or pass --operator")
        return 1

    try:
        switch.reset(operator=operator)
        persisted = json.loads(
            (Path(settings.data_dir) / "kill_switch.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError, TypeError) as exc:
        print(f"\nRESET FAILED: persisted switch could not be verified: {exc}")
        return 1
    if persisted != {"tripped": False, "reason": None} or KillSwitch(settings.data_dir).tripped:
        print("\nRESET FAILED: persisted switch is not clear")
        return 1
    print(f"\nRESET. tripped now: {switch.tripped}")
    print("⚠️ Order flow resumes at the next launch. The position cap and every")
    print("   other rail are unaffected - this clears the HALT and nothing else.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
