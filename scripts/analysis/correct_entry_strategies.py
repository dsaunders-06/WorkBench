r"""One-off record correction: store the strategy on the pre-M49 entries (M86).

`open_position_entries.json` carries `"strategy": null` for the nine positions
whose records were written before M49 added the field on 5 August. Those nine
restore attributed to swing anyway, because `restore_open_lots` falls back to
`_sole_deployed_strategy()` and swing is the only deployed strategy - so nothing
is lost today. The problem is that the attribution is re-derived at every launch
instead of stored, and the fallback returns None as soon as a second strategy is
deployed. Activating M84 or M85 would retroactively unattribute all nine.

M86 makes the app heal this at startup, but that build is not deployed. This
script does the same correction to the live record now, for the build that is.

**Why swing is a fact here, not a guess.** `decision_journal.csv` records
`strategy=swing` for all nine, with `signed_off`/`auto_signed` transmit
timestamps matching each record's `opened_at` to the second - e.g. JNJ at
2026-07-31T15:08:21+00:00 and MS at 2026-08-04T14:01:24+00:00. They were opened
autonomously by swing; the record simply had nowhere to say so.

Deliberately a TEXT substitution, not a JSON round-trip. Re-serialising would
reformat every float, and `stop_price` values like 240.5880357142857 are the
denominator of every R-multiple the promotion gate reads. Nothing but the
strategy fields is touched, and the script proves that by diffing every other
line.

Run with the app CLOSED - a running app holds the record in memory and its next
save would overwrite this. Under the PowerShell tool, not Bash: the live data
directory is only visible there.

    .\.venv\Scripts\python.exe scripts\analysis\correct_entry_strategies.py --apply

Without --apply it reports what it would do and writes nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

NULL_FIELD = '"strategy": null'
FIXED_FIELD = '"strategy": "swing"'
EXPECTED_NULLS = 9
EXPECTED_SYMBOLS = {"AMAT", "AMD", "CRWD", "CSCO", "GS", "JNJ", "MS", "UNP", "WFC"}

ENTRIES = (
    Path(os.environ["LOCALAPPDATA"])
    / "QuantAdvisoryTerminal"
    / "data"
    / "open_position_entries.json"
)


def _fail(message: str) -> None:
    print(f"ABORT - {message}")
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write the correction")
    args = parser.parse_args()

    raw = ENTRIES.read_text(encoding="utf-8")
    before = json.loads(raw)

    nulls = {s for s, row in before.items() if row.get("strategy") is None}
    named = {s: row["strategy"] for s, row in before.items() if row.get("strategy")}
    print(f"Record: {ENTRIES}  ({len(raw)} bytes, {len(before)} positions)")
    print(f"  null  : {len(nulls)} - {', '.join(sorted(nulls))}")
    print(f"  named : {named}")

    # Preconditions. The correction is only correct for the record it was
    # verified against, so a record that has moved on stops it.
    if nulls != EXPECTED_SYMBOLS:
        _fail(f"expected exactly {sorted(EXPECTED_SYMBOLS)} to be null, found {sorted(nulls)}")
    if raw.count(NULL_FIELD) != EXPECTED_NULLS:
        _fail(f"expected {EXPECTED_NULLS} '{NULL_FIELD}' fields, found {raw.count(NULL_FIELD)}")

    corrected = raw.replace(NULL_FIELD, FIXED_FIELD)
    after = json.loads(corrected)

    # Nothing but the strategy moved. Compared field by field on the PARSED
    # objects, so a float that changed representation would still be caught.
    if set(after) != set(before):
        _fail("the symbol set changed")
    for symbol, row in before.items():
        for field, value in row.items():
            if field == "strategy":
                continue
            if after[symbol][field] != value:
                _fail(f"{symbol}.{field} changed: {value!r} -> {after[symbol][field]!r}")
        if after[symbol]["strategy"] != (row["strategy"] or "swing"):
            _fail(f"{symbol}.strategy resolved wrongly: {after[symbol]['strategy']!r}")
    print("  verified: every non-strategy field byte-identical after the substitution")

    if not args.apply:
        print("\nDry run. Nothing written. Re-run with --apply.")
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = ENTRIES.with_name(f"{ENTRIES.name}.bak-{stamp}-PRE-M86-strategy-backfill")
    shutil.copy2(ENTRIES, backup)
    print(f"\n  backup : {backup.name}")

    ENTRIES.write_text(corrected, encoding="utf-8")

    # Read back from disk rather than trusting the write.
    reread = json.loads(ENTRIES.read_text(encoding="utf-8"))
    still_null = [s for s, row in reread.items() if not row.get("strategy")]
    print(f"  written: {len(reread)} positions, {len(still_null)} still unattributed")
    if still_null:
        _fail(f"still null after the write: {still_null}")
    print("  all positions now carry a stored strategy")


if __name__ == "__main__":
    main()
