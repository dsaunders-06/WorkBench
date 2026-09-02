"""The per-symbol material an advisory answer is entitled to (M126).

Extracted from the AI Advisor screen because the Workbench asks the same
question about the same company and was given strictly less to answer it with -
no results date, no news - so the two screens could reach different views of one
company at one moment for no stated reason. Two copies of this would drift; one
copy cannot.

Functions rather than a mixin, and no Qt in here, so the fetching rules can be
tested without constructing a screen - the same reasoning `as_context_dicts`
gives for living in `data/news.py`.

Every path degrades to "nothing known". A third-party feed must never be able
to stop the advisor answering, and an advisory screen is the last place that
should raise.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

from qat.data.news import as_context_dicts, corroborate, drop_other_listings
from qat.domain.ai_advisory.context import AdvisoryContext

logger = logging.getLogger(__name__)


class _VerdictSource(Protocol):
    """`SymbolVerdict`'s one method this module needs, and nothing else.

    A Protocol rather than importing `SymbolVerdict` itself, the same reason
    `symbol_verdict.EligibilitySource` is a Protocol rather than importing
    `StrategyEngine`: this module stays free of a dependency it does not
    otherwise need, and a test can supply the one method without building the
    real dataclass.
    """

    def as_dicts(self) -> list[dict[str, object]]: ...


def news_enabled(runtime: object) -> bool:
    settings = getattr(runtime, "settings", None)
    return getattr(settings, "news_source", "none") != "none"


async def news_for(runtime: object, symbol: str) -> list[dict[str, object]]:
    """Corroborated company news, or nothing.

    The fetch runs in a thread because the vendor client is blocking and the
    caller is the UI thread.

    THE CORROBORATION RULE IS APPLIED HERE, deterministically, before the text
    reaches a model - never by asking the model whether its sources agree. An
    attacker who controls one article also controls anything that article
    claims about its own corroboration.

    How many outlets it takes is `QAT_NEWS_MIN_SOURCES`, and it is read from
    settings rather than left at the function's default so that the operator
    can change it without a rebuild. It defaulted to two until 21 August; the
    reasoning for the change, and what it costs, is recorded at the setting.
    """
    source = getattr(runtime, "news_source", None)
    if source is None:
        return []
    settings = getattr(runtime, "settings", None)
    min_sources = int(getattr(settings, "news_min_sources", 2) or 2)
    try:
        items = await asyncio.to_thread(source.fetch, symbol)
        return as_context_dicts(corroborate(drop_other_listings(items), min_sources=min_sources))
    except Exception:  # noqa: BLE001 - news is never worth failing the screen for
        logger.debug("News fetch failed for %s", symbol, exc_info=True)
        return []


def next_earnings_for(runtime: object, symbol: str) -> str:
    """The next scheduled results date, ISO, or "" when unknown.

    Read from the calendar the ENTRY GATE already consults, so the advisor and
    the rail cannot disagree about when results land.
    """
    bridge = getattr(runtime, "signal_bridge", None)
    calendar = getattr(bridge, "earnings_calendar", None)
    if calendar is None:
        return ""
    try:
        when = calendar.next_earnings(symbol)
    except Exception:  # noqa: BLE001 - advisory context is never worth raising for
        logger.debug("Earnings lookup failed for %s", symbol, exc_info=True)
        return ""
    return when.isoformat() if when else ""


async def build_advisory_context(
    runtime: object,
    symbol: str,
    *,
    operator_question: str = "",
    candidate_signal: dict[str, Any] | None = None,
    backtest_stats: dict[str, float] | None = None,
    regime_label: str = "unknown",
    regime_probs: dict[str, float] | None = None,
    verdict: _VerdictSource | None = None,
    positions: dict[str, float] | None = None,
    risk_metrics: dict[str, Any] | None = None,
    fundamentals: dict[str, Any] | None = None,
    fetched_notes: list[str] | None = None,
    position: dict[str, Any] | None = None,
) -> AdvisoryContext:
    """Everything an advisory answer about `symbol` is entitled to, in one place.

    Both screens call this. They differ ONLY in what they can legitimately
    supply - the Workbench has backtest stats and the Advisor has the operator's
    question - and never in what they fetch, because that difference is what let
    them reach different views of one company (M126, and the regime gap this
    closes).

    Every path degrades to "nothing known". A third-party feed must never stop
    the advisor answering, and an advisory screen is the last place that should
    raise.
    """
    # NO macro_signal / macro_series. The spec's correction of 22 August: the
    # macro read is not an attribute waiting to be handed over -
    # `compute_macro_signal` needs an awaited `get_daily_bars` fetch, and the
    # Regime Monitor computes it only when the operator presses Analyse. Wiring
    # it here would put a vendor call on every question, and passing a stale or
    # absent value would be worse. The fields stay empty; the prompt already
    # renders them as absent rather than as zero.
    return AdvisoryContext(
        symbol=symbol,
        regime_label=regime_label,
        regime_probs=dict(regime_probs or {}),
        positions=dict(positions or {}),
        risk_metrics=dict(risk_metrics or {}),
        candidate_signal=dict(candidate_signal or {}),
        backtest_stats=dict(backtest_stats or {}),
        fundamentals=dict(fundamentals or {}),
        next_earnings=next_earnings_for(runtime, symbol),
        news=await news_for(runtime, symbol),
        fetched_notes=list(fetched_notes or []),
        operator_question=operator_question,
        position=dict(position or {}),
        rule_checks=verdict.as_dicts() if verdict is not None else [],
    )
