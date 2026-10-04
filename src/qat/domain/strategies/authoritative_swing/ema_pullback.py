"""Authoritative EMA20 pullback with bullish-rejection detector."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Context, Decimal, localcontext

from qat.domain.strategies.authoritative_swing.evidence import stable_decision_id
from qat.domain.strategies.authoritative_swing.indicators import (
    completed_weekly_bars,
    ema,
    wilder_atr,
)
from qat.domain.strategies.authoritative_swing.model import (
    DecisionStatus,
    Pattern,
    PatternCandidate,
    PatternDecision,
    RuleEvidence,
    RuleOutcome,
    SwingHistory,
)
from qat.domain.strategies.authoritative_swing.numeric import NUMERIC_POLICY


def _context() -> Context:
    return Context(prec=NUMERIC_POLICY.precision, rounding=NUMERIC_POLICY.rounding)


def _outcome(condition: bool) -> RuleOutcome:
    return RuleOutcome.PASS if condition else RuleOutcome.FAIL


def _finite_history(history: SwingHistory) -> bool:
    return all(
        value.is_finite()
        for bar in history.daily
        for prices in (bar.raw, bar.adjusted)
        for value in (prices.open, prices.high, prices.low, prices.close)
    )


def _abstain(code: str, reason: str) -> PatternDecision:
    return PatternDecision(
        pattern=Pattern.EMA_PULLBACK,
        status=DecisionStatus.ABSTAIN,
        rules=(RuleEvidence(code, RuleOutcome.ABSTAIN, reason=reason),),
    )


def evaluate_ema_pullback(
    history: SwingHistory, official_sessions: Sequence[date]
) -> PatternDecision:
    """Evaluate the frozen EMA pullback rules using the official session catalog."""

    if not history.daily:
        return _abstain("daily_history", "no finalized daily bars")
    signal = history.daily[-1]
    if not signal.finalized:
        return _abstain("signal_finalized", "signal bar is not finalized")
    if not _finite_history(history):
        return _abstain("finite_prices", "required OHLC values are not finite")

    closes = tuple(bar.adjusted.close for bar in history.daily)
    daily_ema20 = ema(closes, 20)
    daily_ema50 = ema(closes, 50)
    atr14 = wilder_atr(history.daily, 14)
    current_ema20 = daily_ema20[-1]
    current_ema50 = daily_ema50[-1]
    prior_ema20 = daily_ema20[-6] if len(daily_ema20) >= 6 else None
    current_atr14 = atr14[-1]

    try:
        weekly = completed_weekly_bars(history.daily, official_sessions)
    except ValueError as error:
        return _abstain("official_sessions", str(error))
    weekly_closes = tuple(bar.adjusted.close for bar in weekly)
    weekly_ema20 = ema(weekly_closes, 20)
    weekly_ema50 = ema(weekly_closes, 50)

    rules: list[RuleEvidence] = []
    if current_ema20 is None or current_ema50 is None:
        rules.append(
            RuleEvidence(
                "daily_ema_trend",
                RuleOutcome.ABSTAIN,
                reason="daily EMA20 or EMA50 is unavailable",
            )
        )
    else:
        rules.append(
            RuleEvidence(
                "daily_ema_trend",
                _outcome(current_ema20 > current_ema50),
                measured=current_ema20 - current_ema50,
                threshold=Decimal(0),
            )
        )

    if current_ema20 is None or prior_ema20 is None:
        rules.append(
            RuleEvidence(
                "daily_ema_rising",
                RuleOutcome.ABSTAIN,
                reason="current or five-session-prior EMA20 is unavailable",
            )
        )
    else:
        rules.append(
            RuleEvidence(
                "daily_ema_rising",
                _outcome(current_ema20 > prior_ema20),
                measured=current_ema20 - prior_ema20,
                threshold=Decimal(0),
            )
        )

    prices = signal.adjusted
    if current_ema20 is None:
        rules.extend(
            (
                RuleEvidence("ema_touch", RuleOutcome.ABSTAIN, reason="daily EMA20 unavailable"),
                RuleEvidence(
                    "close_above_ema", RuleOutcome.ABSTAIN, reason="daily EMA20 unavailable"
                ),
            )
        )
    else:
        rules.extend(
            (
                RuleEvidence(
                    "ema_touch",
                    _outcome(prices.low <= current_ema20),
                    measured=prices.low,
                    threshold=current_ema20,
                ),
                RuleEvidence(
                    "close_above_ema",
                    _outcome(prices.close > current_ema20),
                    measured=prices.close,
                    threshold=current_ema20,
                ),
            )
        )

    body = abs(prices.close - prices.open)
    candle_range = prices.high - prices.low
    geometry_valid = (
        body > 0
        and candle_range > 0
        and prices.low <= min(prices.open, prices.close)
        and prices.high >= max(prices.open, prices.close)
    )
    lower_wick = min(prices.open, prices.close) - prices.low
    with localcontext(_context()):
        wick_ratio = lower_wick / body if body > 0 else None
    rules.extend(
        (
            RuleEvidence(
                "bullish_close",
                _outcome(prices.close > prices.open),
                measured=prices.close - prices.open,
                threshold=Decimal(0),
            ),
            RuleEvidence(
                "positive_geometry",
                _outcome(geometry_valid),
                measured=candle_range,
                threshold=Decimal(0),
            ),
            RuleEvidence(
                "lower_wick",
                _outcome(body > 0 and lower_wick >= Decimal(2) * body),
                measured=wick_ratio,
                threshold=Decimal(2),
            ),
            RuleEvidence(
                "upper_third_close",
                _outcome(
                    candle_range > 0
                    and Decimal(3) * (prices.close - prices.low) >= Decimal(2) * candle_range
                ),
                measured=prices.close,
                threshold=(
                    (prices.low + (Decimal(2) * candle_range / Decimal(3)))
                    if candle_range > 0
                    else None
                ),
            ),
        )
    )

    if len(weekly) < 50 or not weekly_ema20 or not weekly_ema50:
        rules.append(
            RuleEvidence(
                "weekly_filter",
                RuleOutcome.ABSTAIN,
                measured=len(weekly),
                threshold=50,
                reason="fewer than 50 completed weekly bars",
            )
        )
    else:
        latest_weekly_ema20 = weekly_ema20[-1]
        latest_weekly_ema50 = weekly_ema50[-1]
        if latest_weekly_ema20 is None or latest_weekly_ema50 is None:
            rules.append(
                RuleEvidence(
                    "weekly_filter",
                    RuleOutcome.ABSTAIN,
                    reason="weekly EMA20 or EMA50 is unavailable",
                )
            )
        else:
            close_below = weekly[-1].adjusted.close < latest_weekly_ema20
            ema20_below = latest_weekly_ema20 < latest_weekly_ema50
            rules.append(
                RuleEvidence(
                    "weekly_filter",
                    _outcome(not (close_below and ema20_below)),
                    measured=(f"close_below={close_below};ema20_below_ema50={ema20_below}"),
                    threshold="reject_when_both_true",
                )
            )

    rule_tuple = tuple(rules)
    if any(rule.outcome is RuleOutcome.ABSTAIN for rule in rule_tuple) or current_atr14 is None:
        if current_atr14 is None:
            rule_tuple += (
                RuleEvidence("atr14", RuleOutcome.ABSTAIN, reason="ATR14 is unavailable"),
            )
        return PatternDecision(Pattern.EMA_PULLBACK, DecisionStatus.ABSTAIN, rule_tuple)
    if any(rule.outcome is RuleOutcome.FAIL for rule in rule_tuple):
        return PatternDecision(Pattern.EMA_PULLBACK, DecisionStatus.REJECTED, rule_tuple)

    if current_ema20 is None:
        raise ValueError("qualified pattern requires initialized current_ema20")
    if current_atr14 is None:
        raise ValueError("qualified pattern requires initialized current_atr14")
    factor = signal.raw_to_adjusted_price_factor
    candidate = PatternCandidate(
        pattern=Pattern.EMA_PULLBACK,
        pattern_instance_id=stable_decision_id(
            {
                "kind": "pattern_instance",
                "pattern": Pattern.EMA_PULLBACK,
                "symbol": history.symbol,
                "signal_session": signal.session,
                "signal_digest": signal.digest,
            }
        ),
        breakout_event_id=None,
        signal_session=signal.session,
        analytical_signal_close=prices.close,
        analytical_invalidation=min(prices.low, current_ema20),
        analytical_atr14=current_atr14,
        metadata=(
            ("raw_to_adjusted_price_factor", f"{factor.numerator}/{factor.denominator}"),
            ("signal_digest", signal.digest),
        ),
    )
    return PatternDecision(
        Pattern.EMA_PULLBACK,
        DecisionStatus.QUALIFIED,
        rule_tuple,
        candidate,
    )
