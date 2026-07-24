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
