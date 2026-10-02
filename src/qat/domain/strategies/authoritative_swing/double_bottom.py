"""Authoritative confirmed double-bottom and first-close breakout detector."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Context, Decimal, localcontext

from qat.domain.strategies.authoritative_swing.evidence import stable_decision_id
from qat.domain.strategies.authoritative_swing.indicators import (
    completed_weekly_bars,
    ema,
    wilder_atr,
)
from qat.domain.strategies.authoritative_swing.model import (
    DataQuality,
    DecisionStatus,
    FinalBar,
    Pattern,
    PatternCandidate,
    PatternDecision,
    RuleEvidence,
    RuleOutcome,
    SwingHistory,
)
from qat.domain.strategies.authoritative_swing.numeric import NUMERIC_POLICY


@dataclass(frozen=True, slots=True)
class _BottomPair:
    first: int
    second: int
    first_low: Decimal
    second_low: Decimal
    distance_ratio: Decimal
    neckline: Decimal
    neckline_members: tuple[int, ...]
    second_atr: Decimal
    depth: Decimal
    depth_threshold: Decimal


def _context() -> Context:
    return Context(prec=NUMERIC_POLICY.precision, rounding=NUMERIC_POLICY.rounding)


def _outcome(condition: bool) -> RuleOutcome:
    return RuleOutcome.PASS if condition else RuleOutcome.FAIL


def _abstain(code: str, reason: str) -> PatternDecision:
    return PatternDecision(
        Pattern.DOUBLE_BOTTOM,
        DecisionStatus.ABSTAIN,
        (RuleEvidence(code, RuleOutcome.ABSTAIN, reason=reason),),
    )


def _finite_history(history: SwingHistory) -> bool:
    return all(
        value.is_finite()
        for bar in history.daily
        for prices in (bar.raw, bar.adjusted)
        for value in (prices.open, prices.high, prices.low, prices.close)
    )


def _verified_positive_volume(bars: Sequence[FinalBar]) -> bool:
    return all(
        bar.finalized
        and bar.quality is DataQuality.VERIFIED
        and bar.raw.volume > 0
        for bar in bars
    )


def _confirmed_lows(bars: Sequence[FinalBar]) -> tuple[int, ...]:
    indexes: list[int] = []
    for index in range(3, len(bars) - 3):
        low = bars[index].adjusted.low
        neighbors = (*bars[index - 3 : index], *bars[index + 1 : index + 4])
        if all(low < bar.adjusted.low for bar in neighbors):
            indexes.append(index)
    return tuple(indexes)


def _qualifying_pairs(
    bars: Sequence[FinalBar], atr_values: Sequence[Decimal | None]
) -> tuple[_BottomPair, ...]:
    pairs: list[_BottomPair] = []
    pivots = _confirmed_lows(bars)
    for position, first in enumerate(pivots):
        for second in pivots[position + 1 :]:
            spacing = second - first
            if spacing < 5 or spacing > 30:
                continue
            first_low = bars[first].adjusted.low
            second_low = bars[second].adjusted.low
            with localcontext(_context()):
                mean_low = (first_low + second_low) / Decimal(2)
                distance_ratio = abs(first_low - second_low) / mean_low
            if distance_ratio > Decimal("0.02"):
                continue
            between = bars[first + 1 : second]
            if not between:
                continue
            neckline = max(bar.adjusted.high for bar in between)
            members = tuple(
                index
                for index in range(first + 1, second)
                if bars[index].adjusted.high == neckline
            )
            second_atr = atr_values[second]
            if second_atr is None:
                continue
            depth = neckline - mean_low
            depth_threshold = max(mean_low * Decimal("0.03"), second_atr)
            if depth <= depth_threshold:
                continue
            pairs.append(
                _BottomPair(
                    first,
                    second,
                    first_low,
                    second_low,
                    distance_ratio,
                    neckline,
                    members,
                    second_atr,
                    depth,
                    depth_threshold,
                )
            )
    return tuple(sorted(pairs, key=lambda pair: (pair.second, pair.first), reverse=True))


def _weekly_filter(history: SwingHistory, official_sessions: Sequence[date]) -> RuleEvidence:
    try:
        weekly = completed_weekly_bars(history.daily, official_sessions)
    except ValueError as error:
        return RuleEvidence("weekly_filter", RuleOutcome.ABSTAIN, reason=str(error))
    if len(weekly) < 50:
        return RuleEvidence(
            "weekly_filter",
            RuleOutcome.ABSTAIN,
            measured=len(weekly),
            threshold=50,
            reason="fewer than 50 completed weekly bars",
        )
    closes = tuple(bar.adjusted.close for bar in weekly)
    ema20 = ema(closes, 20)[-1]
    ema50 = ema(closes, 50)[-1]
    if ema20 is None or ema50 is None:
        return RuleEvidence(
            "weekly_filter",
            RuleOutcome.ABSTAIN,
            reason="weekly EMA20 or EMA50 is unavailable",
        )
    close_below = closes[-1] < ema20
    ema20_below = ema20 < ema50
    return RuleEvidence(
        "weekly_filter",
        _outcome(not (close_below and ema20_below)),
        measured=f"close_below={close_below};ema20_below_ema50={ema20_below}",
        threshold="reject_when_both_true",
    )


def evaluate_double_bottom(
    history: SwingHistory,
    official_sessions: Sequence[date],
    volume_multiplier: Decimal = Decimal("1.5"),
) -> PatternDecision:
    """Evaluate the most recent confirmed pair against the current crossing."""

    if not history.daily:
        return _abstain("daily_history", "no finalized daily bars")
    if not history.daily[-1].finalized:
        return _abstain("signal_finalized", "breakout bar is not finalized")
    if not volume_multiplier.is_finite() or volume_multiplier <= 0:
        raise ValueError("volume multiplier must be finite and positive")
    if not _finite_history(history):
        return _abstain("finite_prices", "required OHLC values are not finite")

    bars = history.daily
    atr_values = wilder_atr(bars, 14)
    pairs = _qualifying_pairs(bars, atr_values)
    if not pairs:
        return PatternDecision(
            Pattern.DOUBLE_BOTTOM,
            DecisionStatus.REJECTED,
            (
                RuleEvidence(
                    "confirmed_pair",
                    RuleOutcome.FAIL,
                    reason="no confirmed pair satisfies spacing, similarity, and neckline depth",
                ),
            ),
        )
    pair = pairs[0]
    closes = tuple(bar.adjusted.close for bar in bars)
    ema20_values = ema(closes, 20)
    current_ema20 = ema20_values[-1]
    prior_ema20 = ema20_values[-6] if len(ema20_values) >= 6 else None
    elapsed = len(bars) - 1 - pair.second
    rules: list[RuleEvidence] = [
        RuleEvidence(
            "confirmed_pair",
            RuleOutcome.PASS,
            measured=f"{bars[pair.first].session.isoformat()}..{bars[pair.second].session.isoformat()}",
        ),
        RuleEvidence(
            "bottom_spacing",
            RuleOutcome.PASS,
            measured=pair.second - pair.first,
            threshold="5..30",
        ),
        RuleEvidence(
            "bottom_similarity",
            RuleOutcome.PASS,
            measured=pair.distance_ratio,
            threshold=Decimal("0.02"),
        ),
        RuleEvidence(
            "neckline_depth",
            RuleOutcome.PASS,
            measured=pair.depth,
            threshold=pair.depth_threshold,
        ),
        RuleEvidence(
            "breakout_expiry",
            _outcome(elapsed <= 20),
            measured=elapsed,
            threshold=20,
        ),
        RuleEvidence(
            "first_close_crossing",
            _outcome(bars[-2].adjusted.close <= pair.neckline < bars[-1].adjusted.close),
            measured=(
                f"previous={bars[-2].adjusted.close};current={bars[-1].adjusted.close}"
            ),
            threshold=pair.neckline,
        ),
    ]

    if current_ema20 is None:
        rules.append(
            RuleEvidence(
                "close_above_ema",
                RuleOutcome.ABSTAIN,
                reason="daily EMA20 is unavailable",
            )
        )
    else:
        rules.append(
            RuleEvidence(
                "close_above_ema",
                _outcome(bars[-1].adjusted.close > current_ema20),
                measured=bars[-1].adjusted.close,
                threshold=current_ema20,
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

    volume_window = bars[-21:]
    if len(volume_window) < 21 or not _verified_positive_volume(volume_window):
        rules.append(
            RuleEvidence(
                "breakout_volume",
                RuleOutcome.ABSTAIN,
                reason="21 finalized verified positive-volume sessions are required",
            )
        )
    else:
        with localcontext(_context()):
            prior_mean = sum(
                (Decimal(bar.raw.volume) for bar in volume_window[:-1]), Decimal(0)
            ) / Decimal(20)
            volume_ratio = Decimal(volume_window[-1].raw.volume) / prior_mean
        rules.append(
            RuleEvidence(
                "breakout_volume",
                _outcome(volume_ratio >= volume_multiplier),
                measured=volume_ratio,
                threshold=volume_multiplier,
            )
        )
    rules.append(_weekly_filter(history, official_sessions))
    rule_tuple = tuple(rules)
    if any(rule.outcome is RuleOutcome.ABSTAIN for rule in rule_tuple):
        return PatternDecision(Pattern.DOUBLE_BOTTOM, DecisionStatus.ABSTAIN, rule_tuple)
    if any(rule.outcome is RuleOutcome.FAIL for rule in rule_tuple):
        return PatternDecision(Pattern.DOUBLE_BOTTOM, DecisionStatus.REJECTED, rule_tuple)

    current_atr = atr_values[-1]
    assert current_atr is not None
    signal = bars[-1]
    member_identities = tuple(
        f"{bars[index].session.isoformat()}:{bars[index].digest}"
        for index in pair.neckline_members
    )
    pattern_id = stable_decision_id(
        {
            "kind": "pattern_instance",
            "pattern": Pattern.DOUBLE_BOTTOM,
            "symbol": history.symbol,
            "first_bottom": (bars[pair.first].session, bars[pair.first].digest),
            "second_bottom": (bars[pair.second].session, bars[pair.second].digest),
            "neckline_members": member_identities,
        }
    )
    breakout_id = stable_decision_id(
        {
            "kind": "breakout_event",
            "pattern_instance_id": pattern_id,
            "crossing_session": signal.session,
            "signal_digest": signal.digest,
        }
    )
    factor = signal.raw_to_adjusted_price_factor
    candidate = PatternCandidate(
        pattern=Pattern.DOUBLE_BOTTOM,
        pattern_instance_id=pattern_id,
        breakout_event_id=breakout_id,
        signal_session=signal.session,
        analytical_signal_close=signal.adjusted.close,
        analytical_invalidation=pair.second_low,
        analytical_atr14=current_atr,
        metadata=(
            ("first_bottom", bars[pair.first].session.isoformat()),
            ("second_bottom", bars[pair.second].session.isoformat()),
            ("first_bottom_price", pair.first_low),
            ("second_bottom_price", pair.second_low),
            ("neckline", pair.neckline),
            ("neckline_members", ",".join(member_identities)),
            ("elapsed_sessions", elapsed),
            ("bottom_distance_ratio", pair.distance_ratio),
            ("raw_to_adjusted_price_factor", f"{factor.numerator}/{factor.denominator}"),
            ("signal_digest", signal.digest),
        ),
    )
    return PatternDecision(Pattern.DOUBLE_BOTTOM, DecisionStatus.QUALIFIED, rule_tuple, candidate)
