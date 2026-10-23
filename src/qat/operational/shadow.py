"""Append-only Phase 3 shadow observations, separate from trade records."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

from qat.config import Settings
from qat.data.broker.adapter import BrokerAdapter
from qat.domain.market_calendar import is_trading_day
from qat.domain.oms.oms import OMS
from qat.domain.strategies.authoritative_swing.sizing import LiquidityProfile, exact_cost_profile
from qat.operational.adapter import (
    Abstention,
    AdapterResult,
    EvaluationParameters,
    OperationalAdapter,
)
from qat.operational.authority_attestations import AuthorityAttestations, base_validity
from qat.operational.cards import CardEventStore, CardService, RecommendationCard
from qat.operational.history import (
    SYDNEY,
    ActionLedger,
    CalendarLedger,
    HaltLedger,
    HistoryStore,
    Membership,
    OperationalBar,
    load_actions,
    load_calendar,
    load_halts,
    load_membership,
)
from qat.operational.ibkr_history import (
    IBKRHistoricalBarSource,
    IBKRRawBarProbe,
    filter_backfill_to_calendar,
)
from qat.operational.shadow_record import ShadowRecord

logger = logging.getLogger(__name__)
PROBE_SYMBOLS = ("SUN.AX", "MFG.AX", "BHP.AX", "CBA.AX", "WGX.AX")


def _abstain_revised_symbols(
    result: AdapterResult, pending: tuple[str, ...], session: date, snapshot_hash: str
) -> AdapterResult:
    blocked = set(pending)
    return replace(
        result,
        candidates=tuple(card for card in result.candidates if card.symbol not in blocked),
        abstentions=result.abstentions
        + tuple(
            Abstention(symbol, session, snapshot_hash, ("bar_revision_pending_ds_review",))
            for symbol in pending
            if not any(existing.symbol == symbol for existing in result.abstentions)
        ),
    )


@dataclass(frozen=True, slots=True)
class _ReadySource:
    bars: tuple[OperationalBar, ...]

    def fetch(self, session: date, symbols: tuple[str, ...]) -> tuple[OperationalBar, ...]:
        return tuple(bar for bar in self.bars if bar.session == session and bar.symbol in symbols)


class Phase3ShadowRunner:
    """Daily 17:30 paper-only producer. Its published UI has no sign-off path."""

    name = "phase3-shadow"

    def __init__(
        self,
        settings: Settings,
        broker: BrokerAdapter,
        oms: OMS,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not settings.phase3_shadow_enabled or not settings.phase3_operational_root:
            raise ValueError("Phase 3 shadow is not configured")
        self.settings = settings
        self.broker = broker
        self.oms = oms
        self.now = now or (lambda: datetime.now(SYDNEY))
        self.cards: tuple[RecommendationCard, ...] = ()
        self.abstentions: tuple[object, ...] = ()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def _authorities(
        self, session: date
    ) -> tuple[CalendarLedger, Membership, HaltLedger, ActionLedger, str]:
        root = Path(self.settings.phase3_authorities_dir)
        calendar = load_calendar(root / "calendar.json")
        membership = load_membership(root / "membership.json")
        halts = load_halts(root / "halts.jsonl")
        actions = load_actions(root / "actions.json")
        if any(item.fixture for item in (calendar, membership, halts, actions)):
            raise ValueError("Phase 3 requires real dated ASX authorities, not fixtures")
        if any(item.valid_through is None for item in (calendar, membership, halts, actions)):
            raise ValueError("Phase 3 authority has no valid-through date")
        base = base_validity(
            calendar.valid_through,
            membership.valid_through,
            halts.valid_through,
            actions.valid_through,
        )
        attestation_hash = ""
        ledger = AuthorityAttestations(
            Path(self.settings.phase3_operational_root) / "authority_attestations.jsonl"
        )
        if session > base and ledger.path.exists():
            hashes = {
                name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                for name in ("calendar.json", "membership.json", "halts.jsonl", "actions.json")
            }
            approved = {
                "calendar.json": self.settings.phase3_calendar_sha256,
                "membership.json": self.settings.phase3_membership_sha256,
                "halts.jsonl": self.settings.phase3_halts_sha256,
                "actions.json": self.settings.phase3_actions_sha256,
            }
            if hashes != approved:
                raise ValueError(
                    "Phase 3 authority files differ from configured DS-approved hashes"
                )
            attestation_hash = ledger.require_current(session, hashes, calendar, base)
        return calendar, membership, halts, actions, attestation_hash

    def _liquidity(self) -> LiquidityProfile | None:
        participation = self.settings.phase3_liquidity_max_participation
        entry = self.settings.phase3_liquidity_entry_impact_bps
        stop = self.settings.phase3_liquidity_stop_exit_impact_bps
        if participation is None or entry is None or stop is None:
            return None
        return LiquidityProfile("operator-configured-v1", participation, entry, stop)

    async def run_once(self, session: date) -> bool:
        """Return whether source retry is finished; never place or cancel orders."""
        root = Path(self.settings.phase3_operational_root)
        repository = Path(__file__).resolve().parents[3]
        store = HistoryStore(root, repository_root=repository, protected_roots=())
        shadow = ShadowRecord(root / "shadow.jsonl")
        try:
            calendar, membership, halts, actions, attestation_hash = self._authorities(session)
            calendar.next_open(session)
            for name, authority in (
                ("calendar", calendar),
                ("membership", membership),
                ("halts", halts),
                ("actions", actions),
            ):
                if authority.valid_through is None or (
                    authority.valid_through < session and not attestation_hash
                ):
                    raise ValueError(f"{name} authority is not valid through session")
            if membership.effective_from > session or (
                membership.effective_to < session and not attestation_hash
            ):
                raise ValueError("dated ASX membership does not cover session")
        except (OSError, ValueError, KeyError) as error:
            detail: dict[str, object] = {"reason": f"authority_unavailable:{error}"}
            raw_bars: tuple[dict[str, object], ...] = ()
            try:
                probe = IBKRRawBarProbe(self.settings, audit=store.log)
                raw_bars = await asyncio.to_thread(probe.fetch, session, PROBE_SYMBOLS)
                detail["raw_bars"] = raw_bars
            except Exception as probe_error:  # noqa: BLE001 - read-only retry, never a card
                detail["raw_probe_error"] = str(probe_error)
            shadow.append("abstention", session, detail)
            return len(raw_bars) == len(PROBE_SYMBOLS) and all(
                bar["stable"] is True for bar in raw_bars
            )

        symbols = tuple(sorted(set(membership.symbols + membership.managed_symbols)))
        source = IBKRHistoricalBarSource(
            self.settings, actions, halts, audit=store.log, coverage_start=calendar.coverage_start
        )
        try:
            bars = await asyncio.to_thread(source.fetch, session, symbols)
        except Exception as error:  # noqa: BLE001 - read-only retry, never a card
            shadow.append("abstention", session, {"reason": f"ibkr_source_failure:{error}"})
            return False

        receipt = self.now()
        backfill = filter_backfill_to_calendar(source.backfill, calendar, audit=store.log)
        if backfill:
            existing = {
                (record.bar.symbol, record.bar.session): record.bar
                for symbol in symbols
                for record in store.decision_bars(symbol, session)
            }
            changed = tuple(
                bar
                for bar in backfill
                if (
                    (prior := existing.get((bar.symbol, bar.session))) is None
                    or (
                        prior.raw,
                        prior.analytical,
                        prior.factor,
                        prior.split_ratio,
                        prior.dividend,
                        prior.finalised,
                    )
                    != (
                        bar.raw,
                        bar.analytical,
                        bar.factor,
                        bar.split_ratio,
                        bar.dividend,
                        bar.finalised,
                    )
                )
            )
            if changed:
                await asyncio.to_thread(
                    store.ingest, changed, calendar, received_at=receipt, shadow_freeze_final=True
                )
        adapter = OperationalAdapter(
            store,
            calendar,
            membership,
            halts,
            actions,
            attested_through=session if attestation_hash else None,
            attestation_hash=attestation_hash,
        )
        attempt = await asyncio.to_thread(
            adapter.attempt_primary,
            session,
            symbols,
            _ReadySource(bars),
            received_at=receipt,
            shadow_freeze_final=True,
        )
        pending = store.shadow_revision_pending(symbols)
        if pending:
            shadow.append(
                "abstention",
                session,
                {"reason": "bar_revision_pending_ds_review", "symbols": pending},
            )
            if len(pending) == len(symbols):
                return True
        if attempt.abstained:
            shadow.append("abstention", session, {"reasons": attempt.reasons})
            return False
        account = await self.broker.account()
        if (
            not isinstance(account.net_liquidation, (int, float))
            or account.net_liquidation <= 0
            or not isinstance(account.cash, (int, float))
            or account.cash < 0
        ):
            shadow.append("abstention", session, {"reason": "account_balances_unavailable"})
            return True
        parameters = EvaluationParameters(
            Decimal(str(account.net_liquidation)),
            Decimal(str(account.cash)),
            exact_cost_profile("ASX", self.settings.ibkr_pricing_model),
            self._liquidity(),
        )
        snapshot = await asyncio.to_thread(adapter.freeze, session, parameters)
        result = await asyncio.to_thread(adapter.run, snapshot, now=self.now())
        result = _abstain_revised_symbols(result, pending, session, snapshot.content_hash)
        self.abstentions = result.abstentions
        for abstention in result.abstentions:
            shadow.append("abstention", session, abstention)
        if result.candidates:
            service = CardService(
                adapter,
                snapshot,
                self.oms,
                self.settings,
                CardEventStore(root / "card_events.jsonl"),
                store,
            )
            self.cards = await service.publish(result, now=self.now())
            for card in self.cards:
                shadow.append("card", session, card)
        retryable_history = {
            "not_final",
            "source_bar_missing",
            "three_year_history",
            "gaps",
            "stale_last_session",
        }
        return (
            len(bars) == len(symbols)
            and all(bar.finalised for bar in (*bars, *backfill))
            and not any(
                retryable_history.intersection(abstention.reasons)
                for abstention in result.abstentions
            )
        )

    async def _loop(self) -> None:
        finished: set[date] = set()
        while True:
            now = self.now().astimezone(SYDNEY)
            session = now.date()
            gate = datetime.combine(session, time(17, 30), SYDNEY)
            deadline = datetime.combine(session, time(20), SYDNEY)
            if (
                is_trading_day("ASX", session)
                and session not in finished
                and gate <= now < deadline
            ):
                try:
                    complete = await self.run_once(session)
                except (OSError, ValueError) as error:
                    logger.exception("Phase 3 shadow halted: %s", error)
                    complete = True
                if complete:
                    finished.add(session)
                else:
                    await asyncio.sleep(300)
            else:
                await asyncio.sleep(60)
