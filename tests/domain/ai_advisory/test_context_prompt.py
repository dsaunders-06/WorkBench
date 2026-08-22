"""What the prompt actually tells the model about its own inputs.

The rule this file enforces: an absent figure is STATED, never zeroed and never
silently dropped. M73 exists because 0.0 for an unrecorded VaR reached the model
as "no tail risk", and a language model has no way to ask which it was.
"""

from __future__ import annotations

from qat.domain.ai_advisory.context import AdvisoryContext


def _context(**overrides) -> AdvisoryContext:
    kwargs = dict(
        symbol="BHP.AX",
        regime_label="low_vol",
        regime_probs={"low_vol": 0.6},
        positions={},
        risk_metrics={},
        candidate_signal={},
    )
    kwargs.update(overrides)
    return AdvisoryContext(**kwargs)


def test_the_rule_checks_are_rendered_as_the_systems_own_facts():
    text = _context(
        rule_checks=[
            {"name": "session", "passed": True, "detail": "ASX is open, phase 'Morning Trend'"}
        ]
    ).to_prompt_text()

    assert "session" in text
    assert "Morning Trend" in text


def test_a_rule_that_could_not_be_evaluated_is_not_rendered_as_a_pass():
    """`passed=None` means not knowable now. Rendering it alongside passes
    would tell the model the regime permits a strategy nobody has classified
    yet."""
    text = _context(
        rule_checks=[
            {"name": "regime", "passed": None, "detail": "not yet known - no regime classified"}
        ]
    ).to_prompt_text()

    assert "not yet known" in text
    assert "NOT KNOWN" in text or "could not be" in text.lower()


def test_the_rule_checks_are_not_labelled_untrusted():
    """They are the application's OWN deterministic output about itself.
    `fetched_notes` quarantines third-party text; filing these there would
    repeat the misfiling M117 corrected when the operator's own question was
    travelling in the untrusted channel."""
    text = _context(
        rule_checks=[{"name": "session", "passed": True, "detail": "ASX is open"}]
    ).to_prompt_text()

    untrusted_block = text.split("UNTRUSTED")[1] if "UNTRUSTED" in text else ""
    assert "ASX is open" not in untrusted_block


def test_a_held_position_reaches_the_model_with_its_basis():
    """Before this, `positions` was {symbol: quantity} and nothing else - so a
    model asked whether to SELL knew the share count and no entry price, no
    P&L, no stop and no hold state."""
    text = _context(
        position={"entry_price": 40.0, "pnl_r": -0.21, "notes": ["held until 3 Sep"]}
    ).to_prompt_text()

    assert "40.0" in text
    assert "-0.21" in text
    assert "held until 3 Sep" in text


def test_no_position_block_when_nothing_is_held():
    assert "Position:" not in _context().to_prompt_text()


def test_the_news_line_states_the_bar_that_was_actually_applied():
    """It said "two or more independent outlets" as a fixed phrase. Since
    QAT_NEWS_MIN_SOURCES defaults to 1 that can be false, and a prompt that
    misdescribes its own inputs is worse than one that omits them."""
    text = _context(
        news=[{"title": "A result", "providers": ["Somewhere"], "published": "2026-08-21"}]
    ).to_prompt_text()

    assert "two or more independent outlets" not in text
    assert "outlet" in text
