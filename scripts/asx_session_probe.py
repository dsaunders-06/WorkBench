"""Ask a live IB Gateway what the ASX session actually is - read-only.

    .\.venv\Scripts\python.exe scripts/asx_session_probe.py

Stage 3 needs the opening and closing auctions modelled, and the one thing a
model like that must not be built on is recollection of exchange rules. IBKR
already knows: `ContractDetails` carries `timeZoneId`, `tradingHours` and
`liquidHours`, per contract and per day, holidays and half-days included.

**`liquidHours` is continuous trading and `tradingHours` spans the auctions**,
so the difference between the two is the auction windows as the exchange
states them. This script prints both and interprets neither.

The question it exists to settle: **does IBKR report the ASX's staggered
opening auction per symbol?** The ASX opens in alphabetical groups across
roughly the first ten minutes, so a symbol late in the alphabet is still in
its auction while an early one is trading. If that shows up here as different
`tradingHours` per contract, the model can be per-symbol and derived. If every
contract answers with the same flat window, it cannot be, and the model has to
be a conservative blanket instead - which is a different design, and better
known now than after it is written.

Symbols are chosen to SPAN THE ALPHABET for exactly that reason; a probe of
five banks would answer nothing about grouping.

Reads only. `reqContractDetailsAsync` is the sole request made, the connection
is opened with ib_async's `readonly=True`, and the port and account guards are
imported from `ib_probe` rather than restated - a second copy of a safety rule
is a second place for it to drift.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.config import Settings  # noqa: E402
from qat.data.broker.ib_probe import (  # noqa: E402
    check_paper_account,
    connection_target,
)
from qat.data.broker.ib_translate import to_ib_contract  # noqa: E402
from qat.data.universe import MARKET_WATCHLISTS  # noqa: E402

DEFAULT_OUT = Path("docs/superpowers/specs/2026-08-21-asx-session-hours-raw.md")


def _settings() -> Settings:
    """The operator's real IBKR host/port, with `data_dir` pointed elsewhere.

    Same reasoning as `ibkr_probe._settings`: `Settings(_env_file=None).data_dir`
    is the LIVE data directory, this script writes nothing there, and passing
    its own directory keeps that structural rather than incidental.
    """
    return Settings(data_dir=tempfile.mkdtemp(prefix="qat-session-probe-"))


def alphabet_span(limit: int = 14) -> list[str]:
    """Watchlist symbols spanning as many distinct first letters as possible.

    The staggered open is keyed on the alphabet, so a sample that clusters is
    a sample that cannot see the thing being measured. One symbol per first
    letter, in letter order, then truncated - truncation therefore drops the
    END of the alphabet only if the list is short, and the end is the half
    that opens last.
    """
    megacaps = MARKET_WATCHLISTS["ASX"]["megacap"]
    by_letter: dict[str, str] = {}
    for symbol in sorted(megacaps):
        by_letter.setdefault(symbol[0].upper(), symbol)
    chosen = [by_letter[letter] for letter in sorted(by_letter)]
    if len(chosen) <= limit:
        return chosen
    # Keep both ends and thin the middle: the first and last groups are the
    # ones whose auction times differ most if they differ at all.
    step = (len(chosen) - 1) / (limit - 1)
    return [chosen[round(index * step)] for index in range(limit)]


async def _run(out: Path) -> int:
    from ib_async import IB

    settings = _settings()
    host, port, client_id = connection_target(settings)
    symbols = alphabet_span()
    print(f"market={settings.market}  symbols={len(symbols)}: {', '.join(symbols)}")
    print(f"connecting read-only to {host}:{port} as clientId={client_id} ...")

    ib = IB()
    await ib.connectAsync(host, port, clientId=client_id, readonly=True, timeout=15)
    try:
        accounts = list(ib.managedAccounts())
        check_paper_account(accounts)
        print(f"connected. accounts={', '.join(accounts)}\n")

        rows: list[dict[str, str]] = []
        for symbol in symbols:
            contract = to_ib_contract(symbol, settings.market)
            try:
                details = await ib.reqContractDetailsAsync(contract)
            except Exception as error:  # noqa: BLE001 - a probe reports, never raises
                rows.append({"symbol": symbol, "error": f"{type(error).__name__}: {error}"})
                continue
            if not details:
                rows.append({"symbol": symbol, "error": "no contract details returned"})
                continue
            detail = details[0]
            rows.append(
                {
                    "symbol": symbol,
                    "conId": str(detail.contract.conId),
                    "exchange": str(detail.contract.exchange),
                    "primary": str(detail.contract.primaryExchange),
                    "currency": str(detail.contract.currency),
                    "timeZoneId": str(detail.timeZoneId),
                    "minTick": str(detail.minTick),
                    "tradingHours": str(detail.tradingHours),
                    "liquidHours": str(detail.liquidHours),
                }
            )
    finally:
        ib.disconnect()

    _render(rows, out, accounts=", ".join(accounts))
    return 0


def _render(rows: list[dict[str, str]], out: Path, accounts: str) -> None:
    now = datetime.now(UTC)
    lines = [
        "# ASX session hours as IBKR reports them - RAW",
        "",
        f"Probed {now:%Y-%m-%d %H:%M} UTC, read-only, account(s) {accounts}.",
        "",
        "Machine-written. Do not edit; re-run the probe. Interpretation belongs",
        "in the design document that cites this file.",
        "",
    ]
    for row in rows:
        lines.append(f"## {row['symbol']}")
        lines.append("")
        if "error" in row:
            lines.append(f"    ERROR  {row['error']}")
            lines.append("")
            print(f"{row['symbol']:<10} ERROR  {row['error']}")
            continue
        for key in ("conId", "exchange", "primary", "currency", "timeZoneId", "minTick"):
            lines.append(f"    {key:<13} {row[key]}")
        for key in ("tradingHours", "liquidHours"):
            lines.append(f"    {key:<13} {row[key]}")
        lines.append("")
        print(f"{row['symbol']:<10} tz={row['timeZoneId']}")
        print(f"           trading  {row['tradingHours']}")
        print(f"           liquid   {row['liquidHours']}")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nraw report written to {out}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    return asyncio.run(_run(args.out))


if __name__ == "__main__":
    raise SystemExit(main())
