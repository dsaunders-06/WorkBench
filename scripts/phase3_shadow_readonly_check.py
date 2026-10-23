"""Read-only Phase 3 check, raw-only or with four hash-approved authorities.

This entry point contains no broker order adapter, OMS, or approval path.
It writes raw observations or hash-approved unvalidated candidates to an
explicit outside-Git OPERATIONAL root.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.config import Settings  # noqa: E402
from qat.domain.market_calendar import is_trading_day  # noqa: E402
from qat.domain.strategies.authoritative_swing.sizing import (  # noqa: E402
    LiquidityProfile,
    exact_cost_profile,
)
from qat.operational.adapter import EvaluationParameters, OperationalAdapter  # noqa: E402
from qat.operational.history import (  # noqa: E402
    SYDNEY,
    HistoryStore,
    OperationalBar,
    load_actions,
    load_calendar,
    load_halts,
    load_membership,
)
from qat.operational.ibkr_history import (
    IBKRHistoricalBarSource,  # noqa: E402
    IBKRRawBarProbe,  # noqa: E402
    filter_backfill_to_calendar,  # noqa: E402
)
from qat.operational.shadow_record import ShadowRecord  # noqa: E402

AUTHORITY_FILES = ("calendar.json", "membership.json", "halts.jsonl", "actions.json")
SHADOW_SYMBOLS = tuple(
    f"{name}.AX" for name in ("SUN", "MFG", "CBA", "BHP", "CSL", "WES", "WOW", "TLS", "WDS", "TCL")
)
RAW_SYMBOLS = ("SUN.AX", "MFG.AX", "BHP.AX", "CBA.AX", "WGX.AX")


class _NoTradingSurface:
    def __getattr__(self, name: str) -> object:
        raise RuntimeError(f"read-only check cannot access {name}")


def validate_window(
    session: date, now: datetime, authorities: Path, *, approved: bool = False
) -> None:
    local = now.astimezone(SYDNEY)
    if (
        local.date() != session
        or not is_trading_day("ASX", session)
        or not datetime.combine(session, time(17, 30), SYDNEY)
        <= local
        < datetime.combine(session, time(20), SYDNEY)
    ):
        raise ValueError("read-only shadow check requires today's 17:30–20:00 ASX window")
    if not approved and any(
        (authorities / name).exists()
        for name in ("calendar.json", "membership.json", "halts.jsonl", "actions.json")
    ):
        raise ValueError("dated authorities appeared; this raw-only check must be reviewed")


def validate_approved_authorities(
    root: Path, expected_hashes: dict[str, str], session: date
) -> tuple[Any, Any, Any, Any]:
    """Refuse any file outside the exact DS-approved four-file set."""
    if any((parent / ".git").exists() for parent in (root, *root.parents)):
        raise ValueError("approved authorities must remain outside Git")
    if any(parent.is_symlink() or parent.is_junction() for parent in (root, *root.parents)):
        raise ValueError("approved authority directory must not be linked")
    if not root.is_dir() or {item.name for item in root.iterdir()} != set(AUTHORITY_FILES):
        raise ValueError("approved authority directory must contain exactly four files")
    if set(expected_hashes) != set(AUTHORITY_FILES):
        raise ValueError("exactly four approved authority hashes are required")
    for name in AUTHORITY_FILES:
        path = root / name
        if not path.is_file() or path.is_symlink() or path.is_junction():
            raise ValueError(f"{name}: authority must be a regular, unlinked file")
        expected = expected_hashes[name]
        if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
            raise ValueError(f"{name}: invalid approved hash")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"{name}: approved hash mismatch")
    try:
        calendar = load_calendar(root / "calendar.json")
        membership = load_membership(root / "membership.json")
        halts = load_halts(root / "halts.jsonl")
        actions = load_actions(root / "actions.json")
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"approved authority schema invalid: {error}") from error
    for name in AUTHORITY_FILES:
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected_hashes[name]:
            raise ValueError(f"{name}: authority changed while loading")
    for name, authority in zip(
        AUTHORITY_FILES, (calendar, membership, halts, actions), strict=True
    ):
        if (
            authority.fixture
            or authority.valid_through is None
            or authority.valid_through < session
        ):
            raise ValueError(f"{name}: real authority must be valid through the session")
    calendar.next_open(session)
    if set(membership.symbols) != set(SHADOW_SYMBOLS) or membership.managed_symbols:
        raise ValueError("approved membership must be exactly the ten-name shadow universe")
    if not membership.effective_from <= session <= membership.effective_to:
        raise ValueError("approved membership does not cover the session")
    return calendar, membership, halts, actions


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    equity: Decimal
    cash: Decimal
    observed_at: datetime


async def read_account_snapshot(
    settings: Settings,
    *,
    client_factory: Callable[[], Any] | None = None,
    now: Callable[[], datetime] | None = None,
) -> AccountSnapshot:
    """Use one read-only account-summary request, scoped to the one DU account."""
    if (
        settings.market != "ASX"
        or settings.broker != "ibkr"
        or settings.trading_mode != "paper"
        or settings.ibkr_host not in {"127.0.0.1", "localhost", "::1"}
        or settings.ibkr_port != 4002
        or not settings.ibkr_account_id.startswith("DU")
    ):
        raise ValueError("shadow account requires the configured ASX paper Gateway on port 4002")
    if client_factory is None:
        from ib_async import IB

        client_factory = IB
    client = client_factory()
    try:
        await client.connectAsync(
            settings.ibkr_host, settings.ibkr_port, clientId=99, readonly=True, timeout=15
        )
        if tuple(client.managedAccounts()) != (settings.ibkr_account_id,):
            raise ValueError("Gateway must expose exactly the configured DU account")
        values = await client.accountSummaryAsync()
        stamped = (now or (lambda: datetime.now(SYDNEY)))().astimezone(SYDNEY)
        selected: dict[str, set[Decimal]] = {"NetLiquidation": set(), "TotalCashValue": set()}
        for row in values:
            if (
                getattr(row, "account", None) == settings.ibkr_account_id
                and getattr(row, "currency", None) in {"AUD", "BASE"}
                and getattr(row, "tag", None) in selected
            ):
                try:
                    selected[row.tag].add(Decimal(str(row.value)))
                except InvalidOperation as error:
                    raise ValueError("invalid IBKR account summary value") from error
        if any(len(amounts) != 1 for amounts in selected.values()):
            raise ValueError("IBKR account summary lacks one unambiguous equity and cash value")
        equity = next(iter(selected["NetLiquidation"]))
        cash = next(iter(selected["TotalCashValue"]))
        if not equity.is_finite() or equity <= 0 or not cash.is_finite() or cash < 0:
            raise ValueError("IBKR account equity or cash is invalid")
        return AccountSnapshot(equity, cash, stamped)
    finally:
        client.disconnect()


def approved_shadow_record(root: Path) -> ShadowRecord:
    root.mkdir(parents=True, exist_ok=True)
    return ShadowRecord(root / "shadow.jsonl")


def record_approved_result(
    record: ShadowRecord,
    session: date,
    result: Any,
    pending_revisions: tuple[str, ...],
    account: AccountSnapshot,
) -> None:
    """Write immutable candidate evidence only; no approval or order object exists."""
    blocked = set(pending_revisions)
    for abstention in result.abstentions:
        record.append(
            "abstention",
            session,
            {"symbol": abstention.symbol, "reasons": abstention.reasons},
        )
    for symbol in pending_revisions:
        if not any(item.symbol == symbol for item in result.abstentions):
            record.append(
                "abstention",
                session,
                {"symbol": symbol, "reasons": ("bar_revision_pending_ds_review",)},
            )
    for candidate in result.candidates:
        if candidate.symbol in blocked:
            continue
        if candidate.label != "unvalidated strategy, no demonstrated edge":
            raise ValueError("candidate lacks the mandatory unvalidated label")
        record.append(
            "card",
            session,
            {
                "symbol": candidate.symbol,
                "label": candidate.label,
                "entry_limit_raw": str(candidate.entry_limit_raw),
                "structural_stop_raw": str(candidate.structural_stop_raw),
                "quantity": candidate.evidence.quantity,
                "snapshot_hash": getattr(candidate, "snapshot_hash", ""),
                "engine_hash": getattr(candidate, "engine_hash", ""),
                "account_equity": str(account.equity),
                "account_observed_at": account.observed_at.isoformat(),
                "sizing_scope": "Phase 2 candidate only; no OMS or Phase 1 approval",
            },
        )


@dataclass(frozen=True, slots=True)
class _ReadySource:
    bars: tuple[OperationalBar, ...]

    def fetch(self, session: date, symbols: tuple[str, ...]) -> tuple[OperationalBar, ...]:
        return tuple(bar for bar in self.bars if bar.session == session and bar.symbol in symbols)


async def run_approved_once(
    session: date,
    settings: Settings,
    authorities: Path,
    expected_hashes: dict[str, str],
    store: HistoryStore,
    record: ShadowRecord,
    account: AccountSnapshot,
    *,
    now: Callable[[], datetime] | None = None,
    source_factory: Callable[..., IBKRHistoricalBarSource] = IBKRHistoricalBarSource,
) -> bool:
    """Read IBKR history, evaluate Phase 2 candidates, and append only shadow evidence."""
    clock = now or (lambda: datetime.now(SYDNEY))
    calendar, membership, halts, actions = validate_approved_authorities(
        authorities, expected_hashes, session
    )
    symbols = tuple(sorted(SHADOW_SYMBOLS))
    source = source_factory(settings, actions, halts, audit=store.log)
    try:
        bars = await asyncio.to_thread(source.fetch, session, symbols)
    except Exception as error:  # noqa: BLE001 - same-source retry only
        record.append("abstention", session, {"reason": f"ibkr_source_failure:{error}"})
        return False
    receipt = clock()
    backfill = filter_backfill_to_calendar(source.backfill, calendar, audit=store.log)
    if backfill:
        existing = {
            (row.bar.symbol, row.bar.session): row.bar
            for symbol in symbols
            for row in store.decision_bars(symbol, session)
        }
        changed = tuple(
            bar
            for bar in backfill
            if (prior := existing.get((bar.symbol, bar.session))) is None
            or (
                prior.raw,
                prior.analytical,
                prior.factor,
                prior.split_ratio,
                prior.dividend,
                prior.finalised,
            )
            != (bar.raw, bar.analytical, bar.factor, bar.split_ratio, bar.dividend, bar.finalised)
        )
        if changed:
            await asyncio.to_thread(
                store.ingest, changed, calendar, received_at=receipt, shadow_freeze_final=True
            )
    adapter = OperationalAdapter(store, calendar, membership, halts, actions)
    attempt = await asyncio.to_thread(
        adapter.attempt_primary,
        session,
        symbols,
        _ReadySource(bars),
        received_at=receipt,
        shadow_freeze_final=True,
    )
    pending = store.shadow_revision_pending(symbols)
    if attempt.abstained:
        record.append(
            "abstention", session, {"reason": "history_abstained", "reasons": attempt.reasons}
        )
        return False
    liquidity = None
    if settings.phase3_liquidity_max_participation is not None:
        liquidity = LiquidityProfile(
            "operator-configured-v1",
            settings.phase3_liquidity_max_participation,
            settings.phase3_liquidity_entry_impact_bps,
            settings.phase3_liquidity_stop_exit_impact_bps,
        )
    parameters = EvaluationParameters(
        account.equity,
        account.cash,
        exact_cost_profile("ASX", settings.ibkr_pricing_model),
        liquidity,
    )
    snapshot = await asyncio.to_thread(adapter.freeze, session, parameters)
    result = await asyncio.to_thread(adapter.run, snapshot, now=clock())
    record_approved_result(record, session, result, pending, account)
    retryable = {
        "not_final",
        "source_bar_missing",
        "three_year_history",
        "gaps",
        "stale_last_session",
    }
    return (
        len(bars) == len(symbols)
        and all(bar.finalised for bar in (*bars, *backfill))
        and not any(retryable.intersection(item.reasons) for item in result.abstentions)
    )


async def run_raw_once(
    session: date, settings: Settings, store: HistoryStore, record: ShadowRecord
) -> bool:
    probe = IBKRRawBarProbe(settings, audit=store.log)
    try:
        bars = await asyncio.to_thread(probe.fetch, session, RAW_SYMBOLS)
        record.append("abstention", session, {"reason": "authority_unavailable", "raw_bars": bars})
        return len(bars) == len(RAW_SYMBOLS) and all(bar["stable"] is True for bar in bars)
    except Exception as error:  # noqa: BLE001 - read-only retry only
        record.append("abstention", session, {"reason": f"raw_probe_failure:{error}"})
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=date.fromisoformat, required=True)
    parser.add_argument("--operational-root", type=Path, required=True)
    parser.add_argument("--authorities-dir", type=Path, required=True)
    for name in AUTHORITY_FILES:
        parser.add_argument(f"--{name.replace('.', '-').replace('jsonl', 'jsonl')}-sha256")
    args = parser.parse_args()
    now = datetime.now(SYDNEY)
    expected_hashes = {
        name: getattr(args, name.replace(".", "_").replace("-", "_") + "_sha256")
        for name in AUTHORITY_FILES
    }
    approved = all(expected_hashes.values())
    if any(expected_hashes.values()) and not approved:
        raise ValueError("all four DS-approved authority hashes must be supplied")
    validate_window(args.session, now, args.authorities_dir, approved=approved)
    if approved:
        validate_approved_authorities(args.authorities_dir, expected_hashes, args.session)
    settings = Settings(
        market="ASX",
        broker="ibkr",
        trading_mode="paper",
        execution_mode="recommend",
        delever_sweep_enabled=False,
        phase3_shadow_enabled=True,
        phase3_operational_root=str(args.operational_root),
        phase3_authorities_dir=str(args.authorities_dir),
        ibkr_host="127.0.0.1",
        ibkr_port=4002,
    )
    if not settings.ibkr_account_id:
        raise ValueError("a configured IBKR paper account is required")
    store = HistoryStore(
        args.operational_root,
        repository_root=Path(__file__).resolve().parent.parent,
        protected_roots=(),
    )
    record = approved_shadow_record(args.operational_root)
    account = asyncio.run(read_account_snapshot(settings)) if approved else None
    if account is not None:
        store.log(
            {
                "kind": "read_only_account_snapshot",
                "account": settings.ibkr_account_id,
                "equity": str(account.equity),
                "cash": str(account.cash),
                "observed_at": account.observed_at.isoformat(),
                "summary_requests": 1,
            }
        )
    while True:
        validate_window(args.session, datetime.now(SYDNEY), args.authorities_dir, approved=approved)
        if approved:
            assert account is not None
            complete = asyncio.run(
                run_approved_once(
                    args.session,
                    settings,
                    args.authorities_dir,
                    expected_hashes,
                    store,
                    record,
                    account,
                )
            )
        else:
            complete = asyncio.run(run_raw_once(args.session, settings, store, record))
        if complete:
            break
        if datetime.now(SYDNEY) >= datetime.combine(args.session, time(19, 55), SYDNEY):
            break
        asyncio.run(asyncio.sleep(300))
    event = record.events[-1]
    evidence_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(args.operational_root.iterdir())
        if path.is_file()
    }
    print(
        json.dumps(
            {
                "session": args.session.isoformat(),
                "complete": complete,
                "kind": event["kind"],
                "content_hash": event["content_hash"],
                "card_count": sum(
                    row["kind"] == "card" and row["session"] == args.session.isoformat()
                    for row in record.events
                ),
                "abstention_count": sum(
                    row["kind"] == "abstention" and row["session"] == args.session.isoformat()
                    for row in record.events
                ),
                "evidence_sha256": evidence_hashes,
            },
            sort_keys=True,
        )
    )
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
