"""Five read-only minutes before a session, instead of a defect during one.

    .\\.venv\\Scripts\\python.exe scripts/preflight.py

Walks the whole chain a session depends on and reports each link with its
reason: configuration, the Gateway, the account, the book, contract
resolution, the price feed and the market session. **Reads only** - it places
nothing, cancels nothing and modifies nothing.

**A check that could not be performed is not a check that passed.** UNKNOWN
blocks READY exactly as FAIL does, so this cannot green-light a session by
quietly skipping half of itself. Exits non-zero when blocked, so it can gate a
launch script.

Written because four live runs against the paper Gateway on 19 August found
four defects a green test suite could not - the capability probe was a rubber
stamp, the bracket run found M96, the protection scan found M99 and the wiring
run found M102. The fakes and the broker disagreed, and only one of them is
real.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.config import Settings  # noqa: E402
from qat.data import universe  # noqa: E402
from qat.preflight import (  # noqa: E402
    Check,
    Status,
    Verdict,
    book_checks,
    contract_checks,
    feed_checks,
    gateway_checks,
    probe_plan,
    render,
    session_checks,
    settings_checks,
    verdict_for,
)
from qat.presentation.runtime import resolve_broker, resolve_market_data_source  # noqa: E402


def _settings() -> Settings:
    """The operator's real configuration, with `data_dir` pointed elsewhere.

    `Settings(_env_file=None).data_dir` is the LIVE data directory and this
    script runs outside pytest, where nothing protects it. Nothing here writes,
    and passing its own directory keeps that structural rather than incidental.
    """
    return Settings(data_dir=tempfile.mkdtemp(prefix="qat-preflight-"))


async def _run(sample: int | None) -> int:
    settings = _settings()
    checks: list[Check] = list(settings_checks(settings))
    checks += session_checks(settings.market)

    watchlist = list(universe.resolve_watchlist(settings))
    checks.append(
        Check(
            "watchlist",
            Status.OK if watchlist else Status.FAIL,
            (
                (
                    f"{len(watchlist)} symbol(s) from category "
                    f"{settings.watchlist_category!r}: {', '.join(watchlist[:6])}"
                    f"{' ...' if len(watchlist) > 6 else ''}"
                )
                if watchlist
                else "empty - the session would have nothing to trade"
            ),
        )
    )

    probe, coverage = probe_plan(watchlist, sample)
    checks.append(coverage)

    # --- the feed, which needs no broker -----------------------------------
    if probe:
        try:
            source = resolve_market_data_source(settings)
        except Exception as exc:  # noqa: BLE001
            checks.append(Check("feed", Status.UNKNOWN, f"{type(exc).__name__}: {exc}"))
        else:
            checks += await feed_checks(probe, source)

    # --- the broker half ----------------------------------------------------
    if settings.broker != "ibkr":
        checks.append(
            Check(
                "gateway",
                Status.WARN,
                f"broker={settings.broker}, so no Gateway checks were run. This pre-flight "
                f"is written for the IBKR path.",
            )
        )
        return _report(checks)

    from qat.domain.bus import EventBus

    bus = EventBus()
    try:
        broker = resolve_broker(settings, bus)
    except Exception as exc:  # noqa: BLE001 - a refusal here IS the finding
        checks.append(Check("broker", Status.FAIL, f"{type(exc).__name__}: {exc}"))
        return _report(checks)

    checks.append(Check("broker", Status.OK, f"{type(broker).__name__} built"))

    client = broker.ib_client
    try:
        await client.connectAsync(
            settings.ibkr_host,
            settings.ibkr_port,
            clientId=settings.ibkr_client_id + 90,
            readonly=True,
            timeout=15,
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            Check(
                "gateway",
                Status.UNKNOWN,
                f"could not connect ({type(exc).__name__}: {exc}). Is IB Gateway running and "
                f"logged into the PAPER session?",
            )
        )
        return _report(checks)

    try:
        checks += await gateway_checks(settings, client)
        checks += await book_checks(broker)
        if probe:
            checks += await contract_checks(probe, settings.market, client)
    finally:
        client.disconnect()

    return _report(checks)


def _report(checks: list[Check]) -> int:
    print()
    print(render(checks))
    print()
    return 0 if verdict_for(checks) is Verdict.READY else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help="how many watchlist symbols to resolve and price. Default covers the "
        "whole watchlist, capped for a large one; the report always states the "
        "coverage. Contract resolution is one request each and IBKR paces them.",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.sample))


if __name__ == "__main__":
    raise SystemExit(main())
