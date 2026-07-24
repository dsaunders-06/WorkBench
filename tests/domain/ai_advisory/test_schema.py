from __future__ import annotations

import pytest
from pydantic import ValidationError

from qat.domain.ai_advisory.schema import AdvisoryRecommendation


def test_valid_recommendation_parses():
    rec = AdvisoryRecommendation(
        recommendation="buy", rationale="strong momentum", confidence=0.8, risk_flags=[]
    )
    assert rec.recommendation == "buy"
    assert rec.confidence == 0.8


def test_confidence_out_of_range_rejected():
    with pytest.raises(ValidationError):
        AdvisoryRecommendation(recommendation="buy", rationale="x", confidence=1.5)


def test_invalid_recommendation_literal_rejected():
    with pytest.raises(ValidationError):
        AdvisoryRecommendation(recommendation="maybe", rationale="x", confidence=0.5)


def test_risk_flags_default_to_empty_list():
    rec = AdvisoryRecommendation(recommendation="hold", rationale="x", confidence=0.5)
    assert rec.risk_flags == []
