"""Earnings are a scheduled binary event, not a draw from the distribution (M57).

Every other rail in this engine reasons about how prices usually move. An
earnings announcement does not obey that: it gaps, and a gap is the one hazard
a resting stop cannot protect against, because the price never trades at the
stop. The ledger has already paid for this once - the CVS stop gapped at an
open and filled 47 shares in pieces.

The response is to halve, not to refuse. Refusing loses the setup outright, and
this book already turns away hundreds of candidates a night for capacity. The
direction of an earnings move is unknown; that it can be large is not.
"""

from __future__ import annotations

from qat.config import Settings
from qat.domain.bus import EventBus
from qat.domain.risk_engine.engine import OrderCandidate, RiskEngine
from qat.domain.risk_engine.kill_switch import KillSwitch


def _engine(**kwargs: object) -> RiskEngine:
    settings = Settings(_env_file=None, **kwargs)  # type: ignore[arg-type]
    return RiskEngine(EventBus(), KillSwitch(), settings=settings)


def _candidate(days_to_earnings: int | None = None, side: str = "buy") -> OrderCandidate:
    return OrderCandidate(
        symbol="AAA",
        side=side,  # type: ignore[arg-type]
        price=100.0,
        atr=2.0,
        candidate_returns=[],
        win_rate=0.5,
        win_loss_ratio=2.0,
        days_to_earnings=days_to_earnings,
    )


def _shares(engine: RiskEngine, candidate: OrderCandidate) -> float:
    decision = engine.evaluate_order(candidate, 100_000.0, {}, {}, available_cash=500_000.0)
    return decision.final_shares


def test_a_trade_into_earnings_is_halved_not_refused() -> None:
    engine = _engine()
    clear = _shares(engine, _candidate(days_to_earnings=None))
    into_earnings = _shares(engine, _candidate(days_to_earnings=2))

    assert clear > 0, "the control has to actually size, or this proves nothing"
    assert into_earnings > 0, "halved, not refused - the setup is still worth taking"
    assert into_earnings == clear * 0.5


def test_the_window_is_inclusive_at_both_ends() -> None:
    """Off-by-one here is the difference between covering the announcement and
    sizing full into it."""
    engine = _engine(earnings_blackout_days=5)
    clear = _shares(engine, _candidate(days_to_earnings=None))

    assert _shares(engine, _candidate(days_to_earnings=0)) == clear * 0.5
    assert _shares(engine, _candidate(days_to_earnings=5)) == clear * 0.5
    assert _shares(engine, _candidate(days_to_earnings=6)) == clear


def test_an_earnings_date_already_past_does_not_shrink_anything() -> None:
    """A stale calendar entry reads as a negative distance. The risk it names
    has already happened, so it must not size the next trade down forever."""
    engine = _engine()
    clear = _shares(engine, _candidate(days_to_earnings=None))

    assert _shares(engine, _candidate(days_to_earnings=-1)) == clear


def test_an_unknown_earnings_date_sizes_normally() -> None:
    """The vendor genuinely cannot answer for every symbol. Unknown must not
    silently mean "safe" OR "halve everything" - it means this rail abstains,
    exactly as the fundamentals strategies do on a missing figure."""
    engine = _engine()
    assert _shares(engine, _candidate(days_to_earnings=None)) > 0


def test_selling_into_earnings_is_never_shrunk() -> None:
    """Every sizing rail here gates ADDED risk. Halving an exit would leave
    half a position exposed to the very event the rail is worried about."""
    engine = _engine()
    decision = engine.evaluate_order(
        _candidate(days_to_earnings=1, side="sell"), 100_000.0, {}, {}, available_cash=500_000.0
    )
    clear = engine.evaluate_order(
        _candidate(days_to_earnings=None, side="sell"), 100_000.0, {}, {}, available_cash=500_000.0
    )
    assert decision.final_shares == clear.final_shares


def test_the_rail_can_be_switched_off() -> None:
    engine = _engine(enforce_earnings_event_risk=False)
    clear = _shares(engine, _candidate(days_to_earnings=None))

    assert _shares(engine, _candidate(days_to_earnings=1)) == clear


def test_a_calendar_that_misbehaves_cannot_block_an_order() -> None:
    """The wiring, not the rail. The bridge asks a third-party calendar on
    every candidate; if that raises, the trade must still be evaluated. An
    optional protection that can refuse orders is worse than no protection."""
    from qat.domain.oms.signal_bridge import _earnings_distance

    class Exploding:
        def trading_days_until(self, symbol, as_of=None):
            raise RuntimeError("vendor down")

    assert _earnings_distance(Exploding(), "AAA") is None


def test_the_bridge_defaults_to_abstaining() -> None:
    """No calendar supplied is the pre-M57 behaviour, not a silent full-size
    assumption dressed up as a decision."""
    from qat.data.earnings import NullEarningsCalendar
    from qat.domain.oms.signal_bridge import _earnings_distance

    assert _earnings_distance(NullEarningsCalendar(), "AAA") is None


def test_the_decision_records_why_it_was_halved() -> None:
    """A position at half size with nothing saying so is indistinguishable
    from the sizer having produced that number on its own."""
    engine = _engine()
    decision = engine.evaluate_order(
        _candidate(days_to_earnings=2), 100_000.0, {}, {}, available_cash=500_000.0
    )

    assert decision.inputs.get("days_to_earnings") == 2
    assert decision.inputs.get("earnings_event_scalar") == 0.5
