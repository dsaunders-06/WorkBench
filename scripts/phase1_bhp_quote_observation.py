"""One read-only BHP quote through IBAdapter.connect and price_observation.

The API connection is restricted to localhost paper Gateway. Every request
after connection checks the single DU account. Orders are unavailable through
the guarded client, and the raw response is stored outside Git.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ib_async import IB

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from phase1_exit_readiness_du_check import GuardedReadOnlyClient  # noqa: E402
from phase3_daily_history_probe import (  # noqa: E402
    _checked_account,
    _paper_target,
    _safe_output_dir,
    _write_raw,
)

from qat.config import Settings  # noqa: E402
from qat.data.broker.ib_adapter import IBAdapter  # noqa: E402
from qat.domain.bus import EventBus  # noqa: E402

SYDNEY = ZoneInfo("Australia/Sydney")
EXPECTED_ACCOUNT = "DUQ200898"


def _check_window(session: date, now: datetime) -> None:
    local = now.astimezone(SYDNEY)
    if local.date() != session or session.weekday() >= 5 or not 11 <= local.hour < 15:
        raise ValueError("BHP quote probe requires its ASX session from 11:00 to 15:00 Sydney")


def _account(client: Any) -> str:
    _checked_account(client)
    account = str(client.managedAccounts()[0])
    if account != EXPECTED_ACCOUNT:
        raise ValueError(f"unexpected DU account {account}")
    return account


async def _observe(adapter: IBAdapter, client: IB) -> dict[str, Any]:
    await adapter.connect()
    account = _account(client)
    observation = await adapter.price_observation("BHP.AX")
    ticker = getattr(adapter.ib_client, "market_data_ticker", None)
    age = (
        (
            observation.observed_timestamp.astimezone(UTC)
            - observation.source_timestamp.astimezone(UTC)
        ).total_seconds()
        if observation.source_timestamp is not None and observation.source_timestamp.tzinfo
        else None
    )
    return {
        "account": account,
        "symbol": "BHP.AX",
        "raw_ticker": {
            "repr": repr(ticker),
            "last_repr": repr(getattr(ticker, "last", None)),
            "market_data_type_repr": repr(getattr(ticker, "marketDataType", None)),
            "delayed_last_timestamp_repr": repr(getattr(ticker, "delayedLastTimestamp", None)),
        },
        "price_observation_repr": repr(observation),
        "value": repr(observation.value),
        "field": observation.field,
        "market_data_type": observation.market_data_type,
        "source_timestamp": (
            observation.source_timestamp.isoformat() if observation.source_timestamp else None
        ),
        "observed_timestamp": observation.observed_timestamp.isoformat(),
        "age_seconds": age,
        "refusal_30_minutes": observation.refusal(max_age=timedelta(minutes=30)),
    }


async def _run(session: date, out_dir: Path) -> int:
    _check_window(session, datetime.now(UTC))
    safe_dir = _safe_output_dir(out_dir)
    settings = Settings(
        _env_file=None,
        market="ASX",
        trading_mode="paper",
        ibkr_host="127.0.0.1",
        ibkr_port=4002,
        ibkr_account_id=EXPECTED_ACCOUNT,
        current_quote_max_age_seconds=1800,
        data_dir=str(safe_dir / "unused-quote-probe-state"),
    )
    host, port, client_id = _paper_target(settings)
    client = IB()
    guarded = GuardedReadOnlyClient(client, expected_account=EXPECTED_ACCOUNT)
    adapter = IBAdapter(
        guarded,
        EventBus(),
        settings=settings,
        read_only=True,
        heartbeat_interval_seconds=600,
        max_connect_attempts=1,
    )
    payload: dict[str, Any] = {
        "probe": "phase1-bhp-quote-observation",
        "session": session.isoformat(),
        "started_utc": datetime.now(UTC).isoformat(),
        "host": host,
        "port": port,
        "client_id": client_id,
        "read_only": True,
        "requests": guarded.requests,
    }
    try:
        payload["observation"] = await _observe(adapter, client)
    except Exception as exc:  # noqa: BLE001 - retain partial read-only evidence
        payload["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        await adapter.disconnect()
    payload["finished_utc"] = datetime.now(UTC).isoformat()
    path, digest = _write_raw(safe_dir, "bhp-quote-observation", payload)
    print(f"{path} SHA-256 {digest}")
    return 1 if "error" in payload else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=date.fromisoformat, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    return asyncio.run(_run(args.session, args.out_dir))


if __name__ == "__main__":
    raise SystemExit(main())
