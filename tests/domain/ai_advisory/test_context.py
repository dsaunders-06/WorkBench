from __future__ import annotations

from qat.domain.ai_advisory.context import AdvisoryContext


def test_to_prompt_text_includes_core_fields():
    context = AdvisoryContext(
        symbol="AAPL",
        regime_label="bull",
        regime_probs={"bull": 0.8},
        positions={"AAPL": 10.0},
        risk_metrics={"var_95": 0.02},
        candidate_signal={"side": "buy", "conviction": 0.7},
    )
    text = context.to_prompt_text()
    assert "AAPL" in text
    assert "bull" in text
    assert "var_95" in text


def test_fetched_notes_are_labelled_as_untrusted():
    context = AdvisoryContext(
        symbol="AAPL",
        regime_label="bull",
        regime_probs={},
        positions={},
        risk_metrics={},
        candidate_signal={},
        fetched_notes=["some news blurb"],
    )
    text = context.to_prompt_text()
    assert "untrusted" in text.lower()
    assert "some news blurb" in text


def test_fundamentals_reach_the_prompt():
    """M40. The deep-dive reasoned about price, regime and macro while knowing
    nothing about the company - a regression from the original application,
    where earnings informed the recommendation."""
    context = AdvisoryContext(
        symbol="AAPL",
        regime_label="bull",
        regime_probs={},
        positions={},
        risk_metrics={},
        candidate_signal={},
        fundamentals={"sector": "Technology", "roe": 0.31, "is_synthetic": False},
    )
    text = context.to_prompt_text()
    assert "roe" in text
    assert "Technology" in text
    assert "0.31" in text


def test_synthetic_fundamentals_say_so_loudly():
    """The app falls back to a seeded synthetic source when no vendor is
    configured, and every figure it produces is invented but entirely
    plausible. Handing those to a model unlabelled would be worse than handing
    it nothing: it would reason confidently about a company from numbers that
    describe no company at all."""
    context = AdvisoryContext(
        symbol="AAPL",
        regime_label="bull",
        regime_probs={},
        positions={},
        risk_metrics={},
        candidate_signal={},
        fundamentals={"sector": "Technology", "roe": 0.31, "is_synthetic": True},
    )
    text = context.to_prompt_text()
    assert "SYNTHETIC" in text
    assert "not real company data" in text
    # The flag itself is not a figure and must not read as one.
    assert "is_synthetic" not in text


def test_real_fundamentals_are_not_labelled_synthetic():
    context = AdvisoryContext(
        symbol="AAPL",
        regime_label="bull",
        regime_probs={},
        positions={},
        risk_metrics={},
        candidate_signal={},
        fundamentals={"sector": "Technology", "roe": 0.31, "is_synthetic": False},
    )
    assert "SYNTHETIC" not in context.to_prompt_text()


def test_no_fundamentals_omits_the_section():
    context = AdvisoryContext(
        symbol="AAPL",
        regime_label="bull",
        regime_probs={},
        positions={},
        risk_metrics={},
        candidate_signal={},
    )
    assert "fundamentals" not in context.to_prompt_text().lower()


def test_no_fetched_notes_omits_section():
    context = AdvisoryContext(
        symbol="AAPL",
        regime_label="bull",
        regime_probs={},
        positions={},
        risk_metrics={},
        candidate_signal={},
    )
    text = context.to_prompt_text()
    assert "untrusted" not in text.lower()
