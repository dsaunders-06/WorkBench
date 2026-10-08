"""Future market inputs cannot change already recorded Phase 2 evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from qat.domain.backtester.swing_artifacts import _json_bytes
from qat.domain.backtester.swing_fills import AmbiguityPolicy
from qat.domain.backtester.swing_replay import AuthoritativeSwingReplay
from qat.domain.backtester.swing_results import ReplayArm, RunStatus, SwingReplayResult
from scripts.research.run_authoritative_swing import (
    _COSTS,
    _LIQUIDITY,
    _STARTING_EQUITY,
    _GoldenEngine,
    _GoldenFixture,
    _run_golden,
    _synthetic_golden,
)


def _prefix(replay: SwingReplayResult, through: date) -> bytes:
    """Serialize only evidence whose session has already occurred."""
    return _json_bytes(
        {
            "decisions": tuple(item for item in replay.decisions if item.session <= through),
            "fills": tuple(item for item in replay.fills if item.session <= through),
            "equity": tuple(item for item in replay.equity if item.session <= through),
        }
    )


def _replay(fixture: _GoldenFixture, *, truncated: bool) -> SwingReplayResult:
    return AuthoritativeSwingReplay(
        calendar_rows=fixture.calendar,
        bars=fixture.bars,
        membership=fixture.membership,
        corporate_actions=fixture.corporate_actions,
        benchmark=fixture.benchmark,
        engine=_GoldenEngine(fixture.decisions, ReplayArm.COMBINED),
        starting_equity=_STARTING_EQUITY,
        costs=_COSTS,
        liquidity=_LIQUIDITY,
        ambiguity_policy=AmbiguityPolicy.CONSERVATIVE,
        final_entry_session=None if truncated else fixture.final_entry_session,
    ).run()


def _truncated(fixture: _GoldenFixture, through: date) -> _GoldenFixture:
    return replace(
        fixture,
        calendar=tuple(row for row in fixture.calendar if row.calendar_date <= through),
        sessions=tuple(day for day in fixture.sessions if day <= through),
        bars={
            symbol: tuple(bar for bar in history if bar.session <= through)
            for symbol, history in fixture.bars.items()
        },
        membership={day: members for day, members in fixture.membership.items() if day <= through},
        benchmark=tuple(bar for bar in fixture.benchmark if bar.session <= through),
        corporate_actions=tuple(
            event for event in fixture.corporate_actions if event.effective_session <= through
        ),
    )


def _changed_future(fixture: _GoldenFixture, through: date) -> _GoldenFixture:
    bars = {
        symbol: tuple(
            (
                replace(
                    bar,
                    raw=replace(bar.raw, high=bar.raw.high + Decimal(1)),
                    adjusted=replace(
                        bar.adjusted,
                        high=bar.adjusted.high
                        + Decimal(bar.raw_to_adjusted_price_factor.numerator)
                        / Decimal(bar.raw_to_adjusted_price_factor.denominator),
                    ),
                    digest=bar.digest + "-future-changed",
                )
                if bar.session > through
                else bar
            )
            for bar in history
        )
        for symbol, history in fixture.bars.items()
    }
    membership = {
        day: members - {"REJ.AX"} if day > through else members
        for day, members in fixture.membership.items()
    }
    calendar = tuple(
        (
            replace(row, source_hash=row.source_hash + "-future-changed")
            if row.calendar_date > through
            else row
        )
        for row in fixture.calendar
    )
    benchmark = tuple(
        (
            replace(
                bar,
                raw=replace(bar.raw, high=bar.raw.high + 1),
                adjusted=replace(bar.adjusted, high=bar.adjusted.high + 1),
                digest=bar.digest + "-future-changed",
            )
            if bar.session > through
            else bar
        )
        for bar in fixture.benchmark
    )
    actions = tuple(
        (
            replace(event, event_id=event.event_id + "-future-changed")
            if event.effective_session > through
            else event
        )
        for event in fixture.corporate_actions
    )
    return replace(
        fixture,
        bars=bars,
        membership=membership,
        calendar=calendar,
        benchmark=benchmark,
        corporate_actions=actions,
    )


def test_every_evaluated_session_is_invariant_to_truncation_and_future_mutations() -> None:
    fixture = _synthetic_golden(Decimal("1.5"))
    baseline = _run_golden(fixture, AmbiguityPolicy.CONSERVATIVE)[ReplayArm.COMBINED]
    assert baseline.status is RunStatus.VALID
    assert baseline.decisions
    evaluated_sessions = sorted({decision.session for decision in baseline.decisions})
    assert evaluated_sessions == list(fixture.sessions[:70])
    for through in evaluated_sessions:
        expected = _prefix(baseline, through)
        truncated = _replay(_truncated(fixture, through), truncated=True)
        mutated = _replay(_changed_future(fixture, through), truncated=False)
        assert truncated.status is RunStatus.VALID, (through, truncated.invalid_reasons)
        assert mutated.status is RunStatus.VALID, (through, mutated.invalid_reasons)
        assert _prefix(truncated, through) == expected, through
        assert _prefix(mutated, through) == expected, through
