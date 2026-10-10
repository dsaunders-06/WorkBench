"""Collect bounded daily IBKR paper history without writing into the repository.

Run ``history`` once after logging into the paper Gateway, then ``finality``
at about 16:15, 17:00, 17:30 and 18:00 Australia/Sydney on one ASX session.
``short`` checks two-day availability without making a finality claim.
Each invocation writes one immutable JSON response and a SHA-256 sidecar to
an explicit directory outside every Git checkout. No application store is read.
"""

from __future__ import annotations

import argparse
import asyncio
import calendar
import hashlib
import json
import sys
import tempfile
import time
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.config import Settings  # noqa: E402
from qat.data.broker.ib_adapter import LivePortInPaperModeError  # noqa: E402
from qat.data.broker.ib_probe import check_paper_account, connection_target  # noqa: E402
from qat.data.broker.ib_translate import to_ib_contract  # noqa: E402

SYDNEY = ZoneInfo("Australia/Sydney")
SYMBOLS = ("SUN.AX", "MFG.AX", "BHP.AX", "CBA.AX", "WGX.AX")
SERIES = ("TRADES", "ADJUSTED_LAST")
MIN_REQUEST_SPACING_SECONDS = 15.0
PAPER_PORTS = frozenset({4002, 7497})
CLOSE_WINDOW = ("15:50", "16:30")


class AccountGateError(ValueError):
    """A malformed account set stops the probe instead of logging and continuing."""


def _safe_output_dir(path: Path) -> Path:
    target = path.expanduser().resolve()
    if any((ancestor / ".git").exists() for ancestor in (target, *target.parents)):
        raise ValueError(f"raw responses must be outside Git: {target}")
    target.mkdir(parents=True, exist_ok=True)
    return target


def _paper_target(settings: Settings) -> tuple[str, int, int]:
    host, port, client_id = connection_target(settings)
    if host not in {"127.0.0.1", "localhost", "::1"} or port not in PAPER_PORTS:
        raise ValueError("probe permits only a local IBKR paper API port (4002 or 7497)")
    if settings.market != "ASX" or settings.is_live:
        raise ValueError("probe requires ASX and paper trading mode")
    return host, port, client_id


def _checked_account(client: Any) -> None:
    accounts = list(client.managedAccounts())
    if len(accounts) != 1:
        raise AccountGateError("probe requires exactly one managed account")
    check_paper_account(accounts)


def _months_earlier(day: date, months: int) -> date:
    year, month_index = divmod(day.year * 12 + day.month - 1 - months, 12)
    month = month_index + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _bar(bar: Any) -> dict[str, Any]:
    fields = ("date", "open", "high", "low", "close", "volume", "average", "barCount")
    return {
        "repr": repr(bar),
        "fields": {
            name: {"repr": repr(value), "python_type": type(value).__name__}
            for name in fields
            if (value := getattr(bar, name, None)) is not None
        },
    }


async def _request(
    client: Any,
    symbol: str,
    series: str,
    end: datetime | None,
    duration: str,
    timeout: float,
    use_rth: bool,
    bar_size: str = "1 day",
) -> dict[str, Any]:
    contract = to_ib_contract(symbol, "ASX")
    started = datetime.now(UTC)
    clock = time.monotonic()
    try:
        _checked_account(client)
        qualified = await client.qualifyContractsAsync(contract)
        if len(qualified) != 1:
            raise ValueError(f"expected one qualified contract, received {len(qualified)}")
        _checked_account(client)
        bars = await client.reqHistoricalDataAsync(
            qualified[0],
            endDateTime=end or "",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow=series,
            useRTH=use_rth,
            formatDate=1,
            keepUpToDate=False,
            timeout=timeout,
        )
        return {
            "symbol": symbol,
            "series": series,
            "end": end.isoformat() if end else None,
            "duration": duration,
            "use_rth": use_rth,
            "bar_size": bar_size,
            "started_utc": started.isoformat(),
            "elapsed_seconds": time.monotonic() - clock,
            "contract_repr": repr(qualified[0]),
            "bars": [_bar(bar) for bar in bars],
            "error": None if bars else "empty historical response",
        }
    except (AccountGateError, LivePortInPaperModeError):
        raise
    except Exception as exc:  # noqa: BLE001 - errors are probe results
        return {
            "symbol": symbol,
            "series": series,
            "end": end.isoformat() if end else None,
            "duration": duration,
            "use_rth": use_rth,
            "bar_size": bar_size,
            "started_utc": started.isoformat(),
            "elapsed_seconds": time.monotonic() - clock,
            "bars": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


async def _tick_request(client: Any, symbol: str, session: date, timeout: float) -> dict[str, Any]:
    """Capture individual all-hours trade ticks near the close, up to IBKR's cap."""
    started = datetime.now(UTC)
    clock = time.monotonic()
    end = min(datetime.now(SYDNEY), datetime.combine(session, clock_time(16, 30), SYDNEY))
    contract = to_ib_contract(symbol, "ASX")
    try:
        _checked_account(client)
        qualified = await client.qualifyContractsAsync(contract)
        if len(qualified) != 1:
            raise ValueError(f"expected one qualified contract, received {len(qualified)}")
        _checked_account(client)
        ticks = await asyncio.wait_for(
            client.reqHistoricalTicksAsync(
                qualified[0],
                startDateTime="",
                endDateTime=end,
                numberOfTicks=1000,
                whatToShow="TRADES",
                useRth=False,
            ),
            timeout=timeout,
        )
        return {
            "symbol": symbol,
            "start_requested": "",
            "desired_start_sydney": datetime.combine(
                session, clock_time(15, 50), SYDNEY
            ).isoformat(),
            "end_requested_sydney": end.isoformat(),
            "number_of_ticks": 1000,
            "what_to_show": "TRADES",
            "use_rth": False,
            "started_utc": started.isoformat(),
            "elapsed_seconds": time.monotonic() - clock,
            "ticks": [
                {
                    name: {"repr": repr(value), "python_type": type(value).__name__}
                    for name in ("time", "price", "size", "exchange", "specialConditions")
                    if (value := getattr(tick, name, None)) is not None
                }
                for tick in ticks
            ],
            "possibly_truncated": len(ticks) >= 1000,
            "error": None if ticks else "empty historical tick response",
        }
    except (AccountGateError, LivePortInPaperModeError):
        raise
    except Exception as exc:  # noqa: BLE001 - failures are probe evidence
        return {
            "symbol": symbol,
            "start_requested": "",
            "desired_start_sydney": datetime.combine(
                session, clock_time(15, 50), SYDNEY
            ).isoformat(),
            "end_requested_sydney": end.isoformat(),
            "number_of_ticks": 1000,
            "what_to_show": "TRADES",
            "use_rth": False,
            "started_utc": started.isoformat(),
            "elapsed_seconds": time.monotonic() - clock,
            "ticks": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def _write_raw(out_dir: Path, mode: str, payload: dict[str, Any]) -> tuple[Path, str]:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = out_dir / f"phase3-{mode}-{stamp}.json"
    data = (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()
    digest = hashlib.sha256(data).hexdigest()
    with path.open("xb") as handle:
        handle.write(data)
    path.with_suffix(".sha256").write_text(f"{digest}  {path.name}\n", encoding="ascii")
    return path, digest


async def _run(
    mode: str,
    out_dir: Path,
    symbols: tuple[str, ...],
    series_to_request: tuple[str, ...],
    timeout: float,
    short_duration: str,
    history_window_months: int,
    short_end_session: date | None,
    history_as_of_now: bool,
    use_rth: bool,
    snapshot_session: date | None = None,
) -> int:
    from ib_async import IB

    settings = Settings(
        data_dir=tempfile.mkdtemp(prefix="qat-phase3-probe-"),
        trading_mode="paper",
        market="ASX",
        ibkr_host="127.0.0.1",
        ibkr_port=4002,
    )
    host, port, client_id = _paper_target(settings)
    client = IB()
    await client.connectAsync(host, port, clientId=client_id, readonly=True, timeout=15)
    try:
        _checked_account(client)
        accounts = list(client.managedAccounts())
        if mode == "preflight":
            print(f"paper Gateway verified: {len(accounts)} DU account(s); no data requested")
            return 0
        now = datetime.now(SYDNEY)
        api_events: list[dict[str, str]] = []

        def record_error(*values: object) -> None:
            api_events.append(
                {"at_utc": datetime.now(UTC).isoformat(), "arguments_repr": repr(values)}
            )

        client.errorEvent += record_error
        rows: list[dict[str, Any]] = []
        tick_rows: list[dict[str, Any]] = []
        if mode == "close_window":
            if snapshot_session is None or snapshot_session != now.date() or now.weekday() >= 5:
                raise ValueError("close-window snapshot requires the current ASX weekday")
            for symbol in SYMBOLS:
                for rth in (False, True):
                    row = await _request(
                        client, symbol, "TRADES", None, "1 D", timeout, rth, "1 min"
                    )
                    rows.append(row)
                    print(
                        f"minute request {len(rows)}: {symbol} useRTH={int(rth)}, "
                        f"bars={len(row['bars'])}, error={row['error'] or 'none'}",
                        flush=True,
                    )
                    await asyncio.sleep(MIN_REQUEST_SPACING_SECONDS)
            for symbol in SYMBOLS:
                tick_row = await _tick_request(client, symbol, snapshot_session, timeout)
                tick_rows.append(tick_row)
                print(
                    f"tick request {len(tick_rows)}: {symbol}, "
                    f"ticks={len(tick_row['ticks'])}, error={tick_row['error'] or 'none'}",
                    flush=True,
                )
                await asyncio.sleep(MIN_REQUEST_SPACING_SECONDS)
        elif mode == "history":
            end_day = now.date()
            consecutive_errors = 0
            for symbol in symbols:
                for series in series_to_request:
                    if history_as_of_now:
                        row = await _request(client, symbol, series, None, "3 Y", timeout, use_rth)
                        rows.append(row)
                        print(
                            f"request {len(rows)}: {symbol} {series}, "
                            f"bars={len(row['bars'])}, error={row['error'] or 'none'}",
                            flush=True,
                        )
                        await asyncio.sleep(MIN_REQUEST_SPACING_SECONDS)
                        continue
                    chunk_end = end_day
                    for _ in range(36 // history_window_months):
                        end = datetime.combine(chunk_end, datetime.min.time(), SYDNEY) + timedelta(
                            hours=23, minutes=59
                        )
                        row = await _request(
                            client,
                            symbol,
                            series,
                            end,
                            f"{history_window_months} M",
                            timeout,
                            use_rth,
                        )
                        rows.append(row)
                        consecutive_errors = consecutive_errors + 1 if row["error"] else 0
                        print(
                            f"request {len(rows)}: {symbol} {series}, "
                            f"bars={len(row['bars'])}, error={row['error'] or 'none'}",
                            flush=True,
                        )
                        if consecutive_errors >= 2:
                            break
                        chunk_end = _months_earlier(chunk_end, history_window_months)
                        await asyncio.sleep(MIN_REQUEST_SPACING_SECONDS)
                    if consecutive_errors >= 2:
                        break
                if consecutive_errors >= 2:
                    break
        else:
            short_end = (
                datetime.combine(short_end_session, datetime.min.time(), SYDNEY)
                + timedelta(hours=23, minutes=59)
                if short_end_session is not None
                else None
            )
            for series in series_to_request:
                rows.append(
                    await _request(
                        client, symbols[0], series, short_end, short_duration, timeout, use_rth
                    )
                )
                await asyncio.sleep(MIN_REQUEST_SPACING_SECONDS)
        payload = {
            "probe": mode,
            "retrieved_utc": datetime.now(UTC).isoformat(),
            "retrieved_sydney": now.isoformat(),
            "account_prefix_verified": "DU",
            "snapshot_session": str(snapshot_session) if snapshot_session else None,
            "close_window_sydney": CLOSE_WINDOW if mode == "close_window" else None,
            "requests": rows,
            "tick_requests": tick_rows,
            "api_error_events": api_events,
        }
    finally:
        client.disconnect()
    path, digest = _write_raw(out_dir, mode, payload)
    print(f"raw response: {path}\nSHA-256: {digest}")
    print(
        f"requests: {len(rows) + len(tick_rows)}, "
        f"errors: {sum(row['error'] is not None for row in rows + tick_rows)}"
    )
    return 0 if all(row["error"] is None for row in rows + tick_rows) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", choices=("preflight", "history", "short", "finality", "close_window")
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--symbol", action="append", choices=SYMBOLS)
    parser.add_argument("--series", action="append", choices=SERIES)
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument(
        "--short-duration", choices=("2 D", "1 M", "3 M", "6 M", "1 Y", "3 Y"), default="2 D"
    )
    parser.add_argument("--history-window-months", type=int, choices=(3, 6, 12), default=12)
    parser.add_argument("--history-as-of-now", action="store_true")
    parser.add_argument("--all-hours", action="store_true")
    parser.add_argument("--short-end-session", type=date.fromisoformat)
    parser.add_argument("--snapshot-session", type=date.fromisoformat)
    args = parser.parse_args()
    if args.timeout <= 0 or args.timeout > 180:
        parser.error("--timeout must be in (0, 180] seconds")
    if args.short_end_session is not None and args.mode != "short":
        parser.error("--short-end-session is available only in short mode")
    if args.history_as_of_now and args.mode != "history":
        parser.error("--history-as-of-now is available only in history mode")
    if args.mode == "close_window" and args.snapshot_session is None:
        parser.error("--snapshot-session is required in close_window mode")
    if args.snapshot_session is not None and args.mode != "close_window":
        parser.error("--snapshot-session is available only in close_window mode")
    return asyncio.run(
        _run(
            args.mode,
            _safe_output_dir(args.out_dir),
            tuple(args.symbol or SYMBOLS),
            tuple(args.series or SERIES),
            args.timeout,
            args.short_duration,
            args.history_window_months,
            args.short_end_session,
            args.history_as_of_now,
            not args.all_hours,
            args.snapshot_session,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
