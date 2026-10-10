"""Log-only Yahoo close cross-check for the five IBKR daily-history probe symbols.

Reads only hashed IBKR raw files outside Git, requests a small independent
sample, and writes the Yahoo response and comparisons outside Git. It never
feeds an operational store or substitutes for an IBKR bar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from phase3_daily_history_probe import _safe_output_dir, _write_raw

_DATE_RE = re.compile(r"datetime\.date\((\d+), (\d+), (\d+)\)")


def _read_ibkr(paths: list[Path]) -> dict[str, dict[date, tuple[Decimal, Decimal]]]:
    history: dict[str, dict[date, tuple[Decimal, Decimal]]] = {}
    for path in paths:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        sidecar = path.with_suffix(".sha256").read_text(encoding="ascii").split()[0]
        if digest != sidecar:
            raise ValueError(f"IBKR response hash mismatch: {path}")
        payload = json.loads(raw)
        if payload.get("probe") != "history":
            raise ValueError(f"not a historical IBKR response: {path}")
        for request in payload["requests"]:
            if request["series"] != "TRADES":
                continue
            symbol = request["symbol"]
            target = history.setdefault(symbol, {})
            for bar in request["bars"]:
                match = _DATE_RE.fullmatch(bar["fields"]["date"]["repr"])
                if match is None:
                    raise ValueError(f"unrecognised IBKR session in {path}")
                session = date(*(int(part) for part in match.groups()))
                values = (
                    Decimal(bar["fields"]["close"]["repr"]),
                    Decimal(bar["fields"]["volume"]["repr"]),
                )
                prior = target.get(session)
                if prior is not None and prior != values:
                    raise ValueError(f"conflicting IBKR bars for {symbol} {session}")
                target[session] = values
    return history


def _fetch(symbol: str, start: date, end: date) -> dict[str, Any]:
    import yfinance as yf

    try:
        frame = yf.Ticker(symbol).history(
            start=start.isoformat(), end=end.isoformat(), auto_adjust=False, actions=False
        )
        rows = [
            {
                "date": timestamp.date().isoformat(),
                "close_repr": repr(float(row["Close"])),
                "volume": str(int(row["Volume"])),
                "adjusted_close_repr": (
                    repr(float(row["Adj Close"])) if "Adj Close" in row else None
                ),
            }
            for timestamp, row in frame.iterrows()
        ]
        return {"symbol": symbol, "start": str(start), "end": str(end), "rows": rows}
    except Exception as exc:  # noqa: BLE001 - source refusal is probe evidence
        return {
            "symbol": symbol,
            "start": str(start),
            "end": str(end),
            "rows": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def _run(paths: list[Path], out_dir: Path) -> int:
    ibkr = _read_ibkr(paths)
    responses: list[dict[str, Any]] = []
    comparisons: list[dict[str, str]] = []
    for symbol, closes in sorted(ibkr.items()):
        recent = sorted(closes)[-3:]
        if not recent:
            continue
        windows = [(recent[0], recent[-1] + timedelta(days=1))]
        if symbol == "SUN.AX" and date(2025, 2, 14) in closes:
            windows.append((date(2025, 2, 14), date(2025, 2, 18)))
        for start, end in windows:
            response = _fetch(symbol, start, end)
            responses.append(response)
            for row in response["rows"]:
                session = date.fromisoformat(row["date"])
                if session not in closes:
                    continue
                ibkr_close, ibkr_volume = closes[session]
                yahoo_close = Decimal(row["close_repr"])
                difference = ibkr_close - yahoo_close
                comparisons.append(
                    {
                        "symbol": symbol,
                        "session": str(session),
                        "ibkr_trades_close": str(ibkr_close),
                        "yahoo_close": str(yahoo_close),
                        "ibkr_trades_volume": str(ibkr_volume),
                        "yahoo_volume": row["volume"],
                        "volume_difference": str(ibkr_volume - Decimal(row["volume"])),
                        "difference": str(difference),
                        "at_least_half_cent": str(abs(difference) >= Decimal("0.005")),
                    }
                )
    payload = {
        "probe": "log_only_close_crosscheck",
        "retrieved_utc": datetime.now(UTC).isoformat(),
        "independent_source": "Yahoo via yfinance; never a replacement source",
        "responses": responses,
        "comparisons": comparisons,
    }
    path, digest = _write_raw(out_dir, "close-crosscheck", payload)
    print(f"cross-check response: {path}\nSHA-256: {digest}")
    print(f"compared closes: {len(comparisons)}")
    material = sum(c["at_least_half_cent"] == "True" for c in comparisons)
    print(f"differences >= half cent: {material}")
    return 0 if comparisons else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ibkr-raw", type=Path, action="append", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    return _run(args.ibkr_raw, _safe_output_dir(args.out_dir))


if __name__ == "__main__":
    raise SystemExit(main())
