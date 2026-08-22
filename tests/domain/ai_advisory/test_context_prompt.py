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
    travelling in the untrusted channel.

    Both `news` and `fetched_notes` are populated here so the UNTRUSTED block
    actually exists in the rendered text - splitting on "UNTRUSTED" against a
    prompt that never contains it degenerates to "not in empty string" and
    would pass even if rule_checks were rendered inside that block. What
    matters is real adjacency: the rule-check detail must appear before the
    untrusted block starts, not fall within it."""
    text = _context(
        rule_checks=[{"name": "session", "passed": True, "detail": "ASX is open"}],
        news=[{"title": "A result", "providers": ["Somewhere"], "published": "2026-08-21"}],
        fetched_notes=["some external note"],
    ).to_prompt_text()

    untrusted_index = text.index("UNTRUSTED")
    rule_check_index = text.index("ASX is open")
    assert rule_check_index < untrusted_index

    untrusted_block = text[untrusted_index:]
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
    """The rendered sentence for a held position is "The account HOLDS this
    symbol...", never the literal "Position:" - so asserting against that
    literal would pass even if the block rendered unconditionally. Assert on
    the real sentinel so a regression that drops the `if self.position:`
    guard (the M73 shape: an empty-looking block reaching the model as if it
    were data) actually fails this test."""
    assert "HOLDS this symbol" not in _context().to_prompt_text()


def test_the_news_line_states_the_bar_that_was_actually_applied():
    """It said "two or more independent outlets" as a fixed phrase. Since
    QAT_NEWS_MIN_SOURCES defaults to 1 that can be false, and a prompt that
    misdescribes its own inputs is worse than one that omits them."""
    text = _context(
        news=[{"title": "A result", "providers": ["Somewhere"], "published": "2026-08-21"}]
    ).to_prompt_text()

    assert "two or more independent outlets" not in text
    assert "outlet" in text
