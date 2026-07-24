from __future__ import annotations

from qat.domain.risk_engine.audit import AuditLog, RiskDecision


def _decision(symbol: str, approved: bool) -> RiskDecision:
    return RiskDecision(
        symbol=symbol,
        approved=approved,
        final_shares=10.0 if approved else 0.0,
        reason="test",
        inputs={},
    )


def test_record_and_entries():
    log = AuditLog()
    log.record(_decision("AAA", True))
    log.record(_decision("BBB", False))
    assert len(log.entries()) == 2


def test_rejections_filters_only_rejected():
    log = AuditLog()
    log.record(_decision("AAA", True))
    log.record(_decision("BBB", False))
    rejections = log.rejections()
    assert len(rejections) == 1
    assert rejections[0].symbol == "BBB"


def test_for_symbol_filters_correctly():
    log = AuditLog()
    log.record(_decision("AAA", True))
    log.record(_decision("AAA", False))
    log.record(_decision("BBB", True))
    assert len(log.for_symbol("AAA")) == 2
    assert len(log.for_symbol("BBB")) == 1


def test_entries_returns_a_copy_not_the_internal_list():
    log = AuditLog()
    log.record(_decision("AAA", True))
    entries = log.entries()
    entries.append(_decision("ZZZ", True))
    assert len(log.entries()) == 1
