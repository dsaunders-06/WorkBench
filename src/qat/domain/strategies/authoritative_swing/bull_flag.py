"""Authoritative five-session pole, flag, and breakout detector."""

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


def _context() -> Context:
    return Context(prec=NUMERIC_POLICY.precision, rounding=NUMERIC_POLICY.rounding)


def _outcome(condition: bool) -> RuleOutcome:
    return RuleOutcome.PASS if condition else RuleOutcome.FAIL


def _abstain(code: str, reason: str) -> PatternDecision:
    return PatternDecision(
        Pattern.BULL_FLAG,
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


def _least_squares_slope(bars: Sequence[FinalBar]) -> Decimal:
    count = len(bars)
    x_mean = Decimal(count - 1) / Decimal(2)
    y_mean = sum((bar.adjusted.close for bar in bars), Decimal(0)) / Decimal(count)
    numerator = sum(
        (
            (Decimal(index) - x_mean) * (bar.adjusted.close - y_mean)
            for index, bar in enumerate(bars)
        ),
        Decimal(0),
    )
    denominator = sum(
        ((Decimal(index) - x_mean) * (Decimal(index) - x_mean) for index in range(count)),
        Decimal(0),
    )
    return numerator / denominator


def _verified_positive_volume(bars: Sequence[FinalBar]) -> bool:
    return all(
        bar.finalized and bar.quality is DataQuality.VERIFIED and bar.raw.volume > 0 for bar in bars
    )


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


def _common_rules(
    history: SwingHistory,
    official_sessions: Sequence[date],
    volume_multiplier: Decimal,
) -> tuple[RuleEvidence, ...]:
    bars = history.daily
    closes = tuple(bar.adjusted.close for bar in bars)
    ema20_series = ema(closes, 20)
    ema50_series = ema(closes, 50)
    current_ema20 = ema20_series[-1]
    current_ema50 = ema50_series[-1]
    prior_ema20 = ema20_series[-6] if len(ema20_series) >= 6 else None
    rules: list[RuleEvidence] = []

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
            ratio = Decimal(volume_window[-1].raw.volume) / prior_mean
        rules.append(
            RuleEvidence(
                "breakout_volume",
                _outcome(ratio >= volume_multiplier),
                measured=ratio,
                threshold=volume_multiplier,
            )
        )

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
    rules.append(_weekly_filter(history, official_sessions))
    return tuple(rules)


def _window_rules(
    bars: Sequence[FinalBar],
    atr_values: Sequence[Decimal | None],
    flag_sessions: int,
) -> tuple[RuleEvidence, ...]:
    breakout_index = len(bars) - 1
    flag_start = breakout_index - flag_sessions
    pole_start = flag_start - 5
    pole = bars[pole_start:flag_start]
    flag = bars[flag_start:breakout_index]
    pole_atr = atr_values[flag_start - 1]
    if len(pole) != 5 or len(flag) != flag_sessions or pole_atr is None:
        return (
            RuleEvidence(
                "pole_move",
                RuleOutcome.ABSTAIN,
                reason="five pole sessions and pole-end ATR14 are required",
            ),
        )

    first_open = pole[0].adjusted.open
    pole_move = pole[-1].adjusted.close - first_open
    pole_threshold = max(first_open * Decimal("0.05"), pole_atr * Decimal(2))
    slope = _least_squares_slope(flag)
    flag_low = min(bar.adjusted.low for bar in flag)
    retracement = pole[-1].adjusted.close - flag_low
    retracement_limit = pole_move * Decimal("0.5")

    rules = [
        RuleEvidence(
            "pole_move",
            _outcome(pole_move >= pole_threshold),
            measured=pole_move,
            threshold=pole_threshold,
        ),
        RuleEvidence(
            "flag_slope",
            _outcome(slope <= 0),
            measured=slope,
            threshold=Decimal(0),
        ),
        RuleEvidence(
            "flag_retracement",
            _outcome(retracement <= retracement_limit),
            measured=retracement,
            threshold=retracement_limit,
        ),
    ]
    if not _verified_positive_volume((*pole, *flag)):
        rules.append(
            RuleEvidence(
                "flag_volume",
                RuleOutcome.ABSTAIN,
                reason="pole and flag volumes must be finalized, verified, and positive",
            )
        )
    else:
        with localcontext(_context()):
            pole_mean = sum((Decimal(bar.raw.volume) for bar in pole), Decimal(0)) / Decimal(5)
            flag_mean = sum((Decimal(bar.raw.volume) for bar in flag), Decimal(0)) / Decimal(
                flag_sessions
            )
        rules.append(
            RuleEvidence(
                "flag_volume",
                _outcome(flag_mean < pole_mean),
                measured=flag_mean,
                threshold=pole_mean,
            )
        )
    flag_high = max(bar.adjusted.high for bar in flag)
    rules.append(
        RuleEvidence(
            "breakout_price",
            _outcome(bars[-1].adjusted.close > flag_high),
            measured=bars[-1].adjusted.close,
            threshold=flag_high,
        )
    )
    return tuple(rules)


def evaluate_bull_flag(
    history: SwingHistory,
    official_sessions: Sequence[date],
    volume_multiplier: Decimal = Decimal("1.5"),
) -> PatternDecision:
    """Evaluate flag lengths longest-first and emit one deterministic candidate."""

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
    common = _common_rules(history, official_sessions, volume_multiplier)
    selected_rules: tuple[RuleEvidence, ...] | None = None

    for flag_sessions in range(8, 2, -1):
        structural = _window_rules(bars, atr_values, flag_sessions)
        rules = structural + common
        if selected_rules is None:
            selected_rules = rules
        if any(rule.outcome is RuleOutcome.ABSTAIN for rule in rules):
            continue
        if any(rule.outcome is RuleOutcome.FAIL for rule in rules):
            continue

        breakout = bars[-1]
        flag = bars[-1 - flag_sessions : -1]
        pole = bars[-1 - flag_sessions - 5 : -1 - flag_sessions]
        current_atr = atr_values[-1]
        assert current_atr is not None
        factor = breakout.raw_to_adjusted_price_factor
        pattern_payload = {
            "kind": "pattern_instance",
            "pattern": Pattern.BULL_FLAG,
            "symbol": history.symbol,
            "pole_digests": tuple(bar.digest for bar in pole),
            "flag_digests": tuple(bar.digest for bar in flag),
        }
        pattern_id = stable_decision_id(pattern_payload)
        breakout_id = stable_decision_id(
            {
                "kind": "breakout_event",
                "pattern_instance_id": pattern_id,
                "signal_digest": breakout.digest,
            }
        )
        candidate = PatternCandidate(
            pattern=Pattern.BULL_FLAG,
            pattern_instance_id=pattern_id,
            breakout_event_id=breakout_id,
            signal_session=breakout.session,
            analytical_signal_close=breakout.adjusted.close,
            analytical_invalidation=min(bar.adjusted.low for bar in flag),
            analytical_atr14=current_atr,
            metadata=(
                ("flag_sessions", flag_sessions),
                ("pole_start", pole[0].session.isoformat()),
                ("pole_end", pole[-1].session.isoformat()),
                ("raw_to_adjusted_price_factor", f"{factor.numerator}/{factor.denominator}"),
                ("signal_digest", breakout.digest),
            ),
        )
        return PatternDecision(Pattern.BULL_FLAG, DecisionStatus.QUALIFIED, rules, candidate)

    if selected_rules is None:
        return _abstain("pattern_history", "at least 16 completed sessions are required")
    status = (
        DecisionStatus.ABSTAIN
        if any(rule.outcome is RuleOutcome.ABSTAIN for rule in selected_rules)
        else DecisionStatus.REJECTED
    )
    return PatternDecision(Pattern.BULL_FLAG, status, selected_rules)
