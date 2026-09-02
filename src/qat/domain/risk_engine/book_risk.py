"""Portfolio risk over the book ACTUALLY HELD, independent of any decision.

⚠️ WHY THIS EXISTS. `risk_metrics()` read the last risk decision's
`portfolio_check`, which is written one rail AFTER the governor's position-count
rejection. With the book at 10 of 10 every candidate is refused before the
portfolio checker runs, so 3,533 of 3,596 audit rows carry no number at all - and
`AuditLog._entries` is in-memory, so `entries()` is empty at every startup
regardless. The model was being told "none available" on every run.

⚠️ ABSENT IS None, NEVER 0.0. `compute_historical_var` and
`compute_expected_shortfall` both return 0.0 below two observations. Calling them
blindly on a thin book would hand the model "no tail risk" about something it
could not measure, which is precisely the failure `risk_metrics`' docstring names:
"a metric the last check did not record reached the model as a MEASURED ZERO".
Every gate here happens BEFORE the call - but that alone is not the guarantee:
`min_observations` arrives as an unvalidated int, and a caller passing 0 or 1
would otherwise gate on nothing. `compute_book_risk` clamps it up to 2, the
floor those two functions themselves impose, so the rail cannot be switched
off by whoever calls it.

The computation reuses `PortfolioRiskChecker`'s own internals rather than
reimplementing them, because the live figure is displayed BESIDE the decision
figure and two numbers measured with different instruments cannot be compared.
That is the 8 August lesson: 5.02% against a true 5.87%.

⚠️ EVERY NUMERIC INPUT CARRIES THE SAME GUARD, NOT ONLY EQUITY. A NaN or
+/-inf dollar WEIGHT is truthy, so a bare `if value:` filter lets it through,
and pandas' skipna=True then turns the resulting NaN weight fraction into a
MEASURED 0.0 concentration - so weights are checked for finiteness too, and
the excluded symbol is named in `notes` rather than silently vanishing from
the book. RETURN observations get the same treatment one step later:
`_combined_portfolio_returns`'s dropna() removes NaN rows but not +/-inf
ones, which `pct_change()` over a vendor zero close legitimately produces
(see signal_bridge.py's `_returns_by_ts`) and which two infinities landing
either side of a percentile target collapse to a measured 0.0 or inf. Those
are filtered out before VaR/ES are called, `observations` reflects the
reduced count, and the same floor gate applies to whatever remains - an
all-infinite book falls through to None on its own, the same way an all-NaN
one already did. A zero-dollar position is excluded from `symbols` outright,
and a sector map that names none of the held symbols leaves `sector_pct` at
None WITH a note, rather than reading as an uncontested (and wrong) zero.

⚠️ `BookRiskMonitor`, below, is the live sampler this module was built for -
independent of any risk decision, on its own timer, over the book actually
held. It reads the account through the SHARED throttled `AccountPoller`
rather than polling the broker itself, and a reader may only ever consult a
measurement through `fresh()`, which treats a stale one exactly as a missing
one.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

from qat.config import Settings
from qat.data.bars import MultiSymbolAggregator
from qat.data.broker.account_poller import AccountPoller
from qat.domain.risk_engine.portfolio_risk import (
    _ES_CONFIDENCE,
    _VAR_CONFIDENCE_95,
    _VAR_CONFIDENCE_99,
    PortfolioRiskChecker,
    compute_expected_shortfall,
    compute_historical_var,
)

logger = logging.getLogger(__name__)

# The mathematical floor, not a policy choice: compute_historical_var and
# compute_expected_shortfall both return 0.0 (not None) below this many
# observations. compute_book_risk enforces it regardless of what
# min_observations its caller passes - see the CRITICAL note above.
_MIN_OBSERVATIONS_FLOOR = 2


@dataclass(frozen=True, slots=True)
class BookRisk:
    """One measurement of the held book. Every metric is optional, and `None`
    means "not measurable", which is a DIFFERENT CLAIM from zero."""

    computed_at: datetime
    symbols: int
    observations: int
    var_95: float | None
    var_99: float | None
    es_975: float | None
    single_name_pct: float | None
    sector_pct: float | None
    notes: tuple[str, ...]

    @property
    def has_any(self) -> bool:
        return any(
            value is not None
            for value in (
                self.var_95,
                self.var_99,
                self.es_975,
                self.single_name_pct,
                self.sector_pct,
            )
        )

    def age_seconds(self, now: datetime) -> float:
        return (now - self.computed_at).total_seconds()


def _absent(now: datetime, notes: tuple[str, ...], symbols: int = 0) -> BookRisk:
    return BookRisk(
        computed_at=now,
        symbols=symbols,
        observations=0,
        var_95=None,
        var_99=None,
        es_975=None,
        single_name_pct=None,
        sector_pct=None,
        notes=notes,
    )


def compute_book_risk(
    *,
    weights: dict[str, float],
    returns: dict[str, pd.Series],
    total_equity: float,
    sector_by_symbol: dict[str, str] | None,
    now: datetime,
    min_observations: int,
) -> BookRisk:
    """Measure the held book. Never raises; never substitutes zero for absent.

    ⚠️ `single_name_pct` and `sector_pct` are the LARGEST in the book, where the
    decision path's fields of the same name are the CANDIDATE's. There is no
    candidate here. Wherever the two are displayed together they must be
    labelled differently, or a coincidence reads as agreement.

    `min_observations` is an unvalidated int supplied by the caller; it is
    clamped up to `_MIN_OBSERVATIONS_FLOOR` before it gates anything, so a
    caller passing 0 or 1 cannot switch VaR/ES off.
    """
    notes: list[str] = []
    held: dict[str, float] = {}
    for symbol, value in weights.items():
        if not value:
            continue
        if not math.isfinite(value):
            # A NaN or infinite dollar weight is truthy, so the zero-filter just
            # above lets it through. Left in `held` it turns the weight fraction
            # below into NaN, and pandas' skipna=True then collapses the all-NaN
            # row to a MEASURED 0.0 - the same failure mode already closed for
            # equity, on the sibling input. Exclude it AND say so, rather than
            # let it vanish as if it were simply zero exposure.
            notes.append(
                f"{symbol} weight is not finite (nan/inf), so it cannot be "
                "measured and was excluded from the book"
            )
            continue
        held[symbol] = value

    if not held:
        return _absent(now, tuple(notes) or ("no positions held",))
    if not (math.isfinite(total_equity) and total_equity > 0):
        # Finiteness and sign must both be checked: `total_equity <= 0` alone
        # lets NaN through (nan <= 0 is False), and `total_equity > 0` alone
        # lets +inf through (inf > 0 is True). Either one reaching here turns
        # every weight fraction downstream into NaN or 0.0, and pandas'
        # skipna=True then collapses the all-NaN row to a MEASURED 0.0 -
        # exactly the sentinel this module exists to refuse.
        notes.append("equity is not available, so nothing can be measured")
        return _absent(now, tuple(notes), len(held))

    # Concentration needs no return history, so it is computed first and
    # survives a book too thin for VaR.
    single_name_pct = max(abs(value) for value in held.values()) / total_equity

    sector_pct: float | None = None
    if sector_by_symbol:
        by_sector: dict[str, float] = {}
        for symbol, value in held.items():
            sector = sector_by_symbol.get(symbol)
            if sector is None:
                continue
            by_sector[sector] = by_sector.get(sector, 0.0) + abs(value)
        if by_sector:
            sector_pct = max(by_sector.values()) / total_equity

    if sector_pct is None:
        notes.append("no held symbol is in the sector map, so sector concentration is unknown")

    portfolio_returns = PortfolioRiskChecker._combined_portfolio_returns(
        held, returns, total_equity
    )
    # dropna() inside _combined_portfolio_returns removes NaN rows but NOT
    # +/-inf ones. pct_change() over a vendor zero close (signal_bridge.py's
    # `closes.pct_change().dropna()`) legitimately produces +inf, and a SHORT
    # position's negative weight fraction flips that to -inf in this combined
    # series. Left in, it reaches np.percentile / tail.mean() below: when the
    # target percentile lands between two infinities the subtraction is
    # -inf - -inf = nan, and max(0.0, -float(nan)) is 0.0 because nan > 0.0 is
    # False - a MEASURED ZERO about tail risk that was never actually
    # measured. Excluding it here, before `observations` is taken, means an
    # all-infinite book lowers the count and falls through the existing floor
    # gate to None on its own, the same way an all-NaN book already does.
    finite = portfolio_returns[portfolio_returns.map(math.isfinite)]
    if len(finite) != len(portfolio_returns):
        notes.append(
            f"{len(portfolio_returns) - len(finite)} non-finite return observation(s) "
            "excluded - they cannot be measured"
        )
    portfolio_returns = finite
    observations = len(portfolio_returns)

    # ⚠️ THE GATE, BEFORE THE CALL - and the floor it gates on is not simply
    # whatever min_observations the caller passed. See _MIN_OBSERVATIONS_FLOOR.
    # Below the floor these three stay None.
    floor = max(_MIN_OBSERVATIONS_FLOOR, min_observations)
    if observations < floor:
        notes.append(
            f"{observations} overlapping return observation(s) across {len(held)} position(s), "
            f"below the floor of {floor} needed - VaR and ES are UNKNOWN, not zero"
        )
        return BookRisk(
            computed_at=now,
            symbols=len(held),
            observations=observations,
            var_95=None,
            var_99=None,
            es_975=None,
            single_name_pct=single_name_pct,
            sector_pct=sector_pct,
            notes=tuple(notes),
        )

    return BookRisk(
        computed_at=now,
        symbols=len(held),
        observations=observations,
        var_95=compute_historical_var(portfolio_returns, _VAR_CONFIDENCE_95),
        var_99=compute_historical_var(portfolio_returns, _VAR_CONFIDENCE_99),
        es_975=compute_expected_shortfall(portfolio_returns, _ES_CONFIDENCE),
        single_name_pct=single_name_pct,
        sector_pct=sector_pct,
        notes=tuple(notes),
    )


def _returns_from_bars(bars: pd.DataFrame | None) -> pd.Series:
    """Close-to-close returns indexed by TIMESTAMP.

    Deliberately the same shape as `signal_bridge._returns_by_ts`: correlating
    two symbols on a positional index compares one symbol's fifth bar to
    another's fifth bar, which are the same day only if both have identical
    history. Duplicated timestamps are collapsed last-wins, because a duplicated
    index fails the whole portfolio computation - which refused every order for
    a full session on 3 August.
    """
    if bars is None or len(bars) < 2 or "ts" not in bars or "close" not in bars:
        return pd.Series(dtype=float)
    frame = bars[["ts", "close"]]
    frame = frame[~frame["ts"].duplicated(keep="last")]
    if len(frame) < 2:
        return pd.Series(dtype=float)
    closes = frame["close"].astype(float)
    closes.index = pd.DatetimeIndex(frame["ts"])
    return closes.pct_change().dropna()


class BookRiskMonitor:
    """Engine (per domain.orchestrator.Engine protocol).

    ⚠️ IT DOES NOT POLL THE BROKER. `EquityMonitor` already states the principle
    for its own sampler - "a separate poller would double the broker traffic to
    record the same number" - and the dashboard calls `AccountPoller` "one
    shared, throttled read rather than two broker calls per tick". This engine
    reads that same shared poller.
    """

    name = "book-risk-monitor"

    def __init__(
        self,
        account_poller: AccountPoller,
        bars: MultiSymbolAggregator,
        settings: Settings | None = None,
        sector_by_symbol: dict[str, str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.account_poller = account_poller
        self.bars = bars
        self.settings = settings or Settings()
        self.sector_by_symbol = sector_by_symbol or {}
        self._clock = clock or (lambda: datetime.now(UTC))
        self.latest: BookRisk | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.poll()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a bad poll must not kill the rails
                logger.exception("Book-risk poll failed; continuing")
            await asyncio.sleep(self.settings.book_risk_poll_seconds)

    async def poll(self) -> BookRisk | None:
        """One measurement.

        ⚠️ A failure LEAVES THE PREVIOUS VALUE STANDING rather than clearing it.
        That is safe only because every value carries `computed_at` and readers
        go through `fresh()`.

        ⚠️ A SNAPSHOT CARRYING `error` IS REFUSED, THE SAME AS A RAISED
        EXCEPTION - not computed from. `AccountPoller._fetch` catches the
        broker's own exceptions and returns `_degrade(...)`, which keeps
        serving the LAST GOOD reading with `taken_at` carried forward
        UNCHANGED and `error` set, precisely so a transient failure does not
        blank the panel. `snapshot()` therefore does NOT raise on a broker
        outage, so the except clause above never fires for one - this check
        is the only thing standing between a stale broker read and a book
        computed from it. Same idiom as balances_panel.py:390
        (`stale = snapshot.error or snapshot.is_stale`).
        """
        try:
            snapshot = await self.account_poller.snapshot()
        except Exception:  # noqa: BLE001 - the previous measurement survives
            logger.warning("Could not read the account for book risk; keeping the last measurement")
            return self.latest

        if snapshot.error is not None:
            logger.warning(
                "Account snapshot is degraded (%s); keeping the last book-risk measurement",
                snapshot.error,
            )
            return self.latest

        equity = getattr(snapshot.balances, "equity", None)
        if equity is None:
            logger.debug(
                "No equity in the account snapshot; keeping the last book-risk measurement"
            )
            return self.latest

        weights = {
            position.symbol: position.quantity * position.avg_price
            for position in snapshot.positions
            if position.quantity
        }
        returns = {
            symbol: series
            for symbol in weights
            if not (series := _returns_from_bars(self.bars.frame_if_present(symbol))).empty
        }

        self.latest = compute_book_risk(
            weights=weights,
            returns=returns,
            total_equity=float(equity),
            sector_by_symbol=self.sector_by_symbol,
            # The DATA's own timestamp, NOT the clock: age_seconds must measure
            # how old the READING is, not how long ago this method happened to
            # run. A degraded snapshot is already refused above, but even a
            # healthy one can be an already-cached read up to interval_seconds
            # old (AccountPoller.snapshot()) - taken_at is the honest figure
            # either way. `_clock` stays reserved for fresh()'s notion of "now".
            now=snapshot.taken_at,
            min_observations=self.settings.book_risk_min_observations,
        )
        return self.latest

    def fresh(self, now: datetime | None = None) -> BookRisk | None:
        """The latest measurement, or None if it is too old to be believed.

        ⚠️ A stale snapshot is treated IDENTICALLY to a missing one. There is no
        third state and no "probably still fine" path - that is what item 6
        refused when it rejected searching back through the audit CSV.

        ⚠️ A NEGATIVE age - `computed_at` dated in the future, from clock skew
        or an injected clock running backwards - is refused too, not treated
        as fresher than fresh. A value dated in the future about the present
        is not trustworthy, so it is treated as absent, the same as one dated
        too far in the past.
        """
        if self.latest is None:
            return None
        age = self.latest.age_seconds(now or self._clock())
        if age < 0:
            logger.warning(
                "Book-risk measurement is dated %.1fs in the future; refusing it as unreliable",
                -age,
            )
            return None
        if age > self.settings.book_risk_max_age_seconds:
            return None
        return self.latest
