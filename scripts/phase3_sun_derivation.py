"""Reproduce SUN's pre-consolidation inverse from saved IBKR TRADES JSON.

Offline only. This reads the exact recorded Python float repr strings, converts
each as Decimal(repr(float)), then applies the operational code's 10000/8511
raw-to-analytical price factor. No Gateway, vendor or store is accessed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.data.broker.ticks import tick_size  # noqa: E402
from qat.domain.strategies.authoritative_swing.model import Ohlcv  # noqa: E402
from qat.domain.strategies.authoritative_swing.numeric import SplitFactor  # noqa: E402
from qat.operational.history import (  # noqa: E402
    SYDNEY,
    OperationalAnalyticalOhlcv,
    OperationalBar,
    _bar_reasons,
    derive_pre_split_bar,
    exact_decimal,
    to_engine_adjusted,
)

EVENT_DATE = date(2025, 2, 17)
PRICE_FACTOR = Fraction(10000, 8511)
EXPECTED_RAW_SHA256 = "2916760b6ec64ec6e6e2b0ea120e5aecd36f7a4ca28fb412b4c6100f56e52811"
OHLC = ("open", "high", "low", "close")
DATE_RE = re.compile(r"datetime\.date\((\d{4}), (\d{1,2}), (\d{1,2})\)")


def _recorded_float(field: dict[str, str]) -> Decimal:
    if field["python_type"] != "float":
        raise ValueError("expected a recorded Python float")
    value = float(field["repr"])
    if repr(value) != field["repr"]:
        raise ValueError("recorded repr is not the shortest-round-trip float")
    return Decimal(repr(value))


def _session(field: dict[str, str]) -> date:
    match = DATE_RE.fullmatch(field["repr"])
    if match is None:
        raise ValueError("unexpected IBKR date representation")
    return date(*(int(part) for part in match.groups()))


def analyse(path: Path) -> dict[str, Any]:
    contents = path.read_bytes()
    digest = hashlib.sha256(contents).hexdigest()
    payload = json.loads(contents)
    matches = [
        row
        for row in payload["requests"]
        if row["symbol"] == "SUN.AX"
        and row["series"] == "TRADES"
        and row["use_rth"] is False
        and row["error"] is None
    ]
    if len(matches) != 1:
        raise ValueError("expected exactly one successful all-hours SUN TRADES response")
    rows: list[dict[str, Any]] = []
    build_failures: list[dict[str, str]] = []
    retrieval = datetime.fromisoformat(
        payload.get("retrieved_utc", "2025-02-17T17:30:00+11:00")
    ).astimezone(SYDNEY)
    for recorded in matches[0]["bars"]:
        fields = recorded["fields"]
        session = _session(fields["date"])
        if session >= EVENT_DATE:
            continue
        analytical_ohlc = {name: _recorded_float(fields[name]) for name in OHLC}
        analytical_volume = _recorded_float(fields["volume"])
        adjusted_volume = Fraction(analytical_volume)
        volume = adjusted_volume * PRICE_FACTOR
        raw_ohlc = {
            name: exact_decimal(Fraction(analytical_ohlc[name]) / PRICE_FACTOR) for name in OHLC
        }
        off_grid = [
            name for name, value in raw_ohlc.items() if value % tick_size(value, "ASX") != 0
        ]
        row = {
            "session": session.isoformat(),
            "adjusted_volume": str(adjusted_volume),
            "adjusted_whole_share_volume": adjusted_volume.denominator == 1,
            "derived_raw_volume": str(volume),
            "whole_share_volume": volume.denominator == 1,
            "derived_raw_ohlc": {name: str(value) for name, value in raw_ohlc.items()},
            "off_grid_fields": off_grid,
        }
        try:
            template = OperationalBar(
                "SUN.AX",
                session,
                Ohlcv(*(analytical_ohlc[name] for name in OHLC), 1),
                Ohlcv(*(analytical_ohlc[name] for name in OHLC), 1),
                SplitFactor(1, 1),
                SplitFactor(1, 1),
                Decimal(0),
                True,
                "IBKR",
                retrieval,
                "Australia/Sydney",
                True,
            )
            analytical = OperationalAnalyticalOhlcv(
                *(analytical_ohlc[name] for name in OHLC), analytical_volume
            )
            derived = derive_pre_split_bar(template, analytical, SplitFactor(10000, 8511))
            reasons = _bar_reasons(derived)
            if reasons:
                raise ValueError(",".join(sorted(reasons)))
            engine_adjusted = to_engine_adjusted(derived)
            row["engine_adjusted_volume"] = engine_adjusted.volume
            row["engine_raw_volume"] = derived.raw.volume
            row["operational_build"] = True
        except ValueError as error:
            row["operational_build"] = False
            build_failures.append({"session": session.isoformat(), "reason": str(error)})
        rows.append(row)
    return {
        "probe": "sun_derivation",
        "raw_file": path.name,
        "raw_sha256": digest,
        "price_factor": "10000/8511",
        "bar_count": len(rows),
        "adjusted_fractional_volume_count": sum(
            not row["adjusted_whole_share_volume"] for row in rows
        ),
        "whole_share_count": sum(row["whole_share_volume"] for row in rows),
        "fractional_volume_count": sum(not row["whole_share_volume"] for row in rows),
        "operational_build_count": sum(row["operational_build"] for row in rows),
        "engine_handoff_count": sum("engine_adjusted_volume" in row for row in rows),
        "build_failures": build_failures,
        "off_grid_bar_count": sum(bool(row["off_grid_fields"]) for row in rows),
        "off_grid_field_counts": {
            name: sum(name in row["off_grid_fields"] for row in rows) for name in OHLC
        },
        "bars": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-file", type=Path, required=True)
    parser.add_argument("--details-out", type=Path)
    args = parser.parse_args()
    result = analyse(args.raw_file)
    if result["raw_sha256"] != EXPECTED_RAW_SHA256 or result["bar_count"] != 341:
        raise ValueError("input differs from the 341-bar recorded SUN response")
    details = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.details_out is not None:
        target = args.details_out.resolve()
        if any((parent / ".git").exists() for parent in (target.parent, *target.parents)):
            raise ValueError("derivation details must stay outside Git")
        target.write_bytes(details.encode())
        target.with_suffix(".sha256").write_text(
            f"{hashlib.sha256(details.encode()).hexdigest()}  {target.name}\n", encoding="ascii"
        )
    summary = {key: value for key, value in result.items() if key != "bars"}
    print(json.dumps(summary, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
