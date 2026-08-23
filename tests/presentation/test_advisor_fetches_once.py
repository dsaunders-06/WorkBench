"""One question, one news fetch.

The Advisor used to fetch company news TWICE per question: once for the sources
block it shows the operator, and again inside `build_advisory_context` for the
model. `news_for` is not a cache read - it calls the vendor live, in a thread,
every time, and degrades silently to `[]` when the call fails.

So the two round trips could legitimately disagree. A story publishes between
them; or the second is rate-limited where the first succeeded. The operator is
then shown stories the model never received, or shown none while it reasoned
from several - and has no way to tell.

**That is M126's defect exactly**, reproduced inside a single screen, on every
question asked. M126 exists because news was fetched, corroborated and handed to
a model with nowhere for the operator to see it; showing them a DIFFERENT set is
not an improvement on showing them nothing.

Counting the fetches is the only way to see this. In the happy path both fetches
return the same thing and every visible output agrees, so no assertion about the
rendered text or the context contents can catch it.
"""

from __future__ import annotations

import pytest

from qat.config import Settings
from qat.domain.ai_advisory.schema import AdvisoryRecommendation
from qat.presentation.ai_advisor import AiAdvisorScreen
from qat.presentation.runtime import Runtime


class _CountingNewsSource:
    """Records every fetch, returns nothing.

    Returning `[]` keeps the corroboration path out of this test: what is being
    measured is how many times the vendor is ASKED, not what it answers.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch(self, symbol: str) -> list:
        self.calls.append(symbol)
        return []


class _StubAdvisory:
    """The model, stubbed. `_ask` must reach it for the test to have exercised
    the whole path, so this records that it was called."""

    def __init__(self) -> None:
        self.calls = 0

    async def get_regime_narrative(self, context) -> AdvisoryRecommendation:
        self.calls += 1
        return AdvisoryRecommendation(
            recommendation="hold",
            confidence=0.5,
            rationale="stubbed",
            risk_flags=[],
        )


def _screen(qtbot) -> AiAdvisorScreen:
    runtime = Runtime.build_demo(settings=Settings(_env_file=None, ui_level="standard"))
    screen = AiAdvisorScreen(runtime)
    qtbot.addWidget(screen)
    return screen


@pytest.mark.asyncio
async def test_one_question_asks_the_vendor_once(qtbot):
    screen = _screen(qtbot)
    source = _CountingNewsSource()
    screen.runtime.news_source = source
    advisory = _StubAdvisory()
    screen.runtime.ai_service = advisory

    symbol = screen.symbol_picker.currentText()
    await screen._ask("is the valuation stretched?")

    assert advisory.calls == 1, "the model was never reached - the test proved nothing"
    assert source.calls == [symbol], (
        f"expected exactly one news fetch for {symbol}, got {len(source.calls)}: "
        "the screen and the context builder are each fetching, so what the "
        "operator is shown can differ from what the model was given"
    )


@pytest.mark.asyncio
async def test_the_sources_block_is_rendered_before_the_answer(qtbot):
    """The fetch moved; the ORDER the operator sees must not.

    M126's whole point is that the operator reads the reply already knowing what
    it rested on, rather than inferring it afterwards. Building the context
    first is what removed the second fetch - it must not have pushed the sources
    block below the answer as a side effect.
    """
    screen = _screen(qtbot)
    screen.runtime.news_source = _CountingNewsSource()
    screen.runtime.ai_service = _StubAdvisory()

    await screen._ask("anything")

    transcript = screen.conversation.toPlainText()
    sources_at = transcript.find("Next scheduled results")
    answer_at = transcript.find("Advisor")

    assert sources_at != -1, "the sources block was not rendered at all"
    assert answer_at != -1, "the answer was not rendered at all"
    assert sources_at < answer_at, "the sources block must precede the answer it describes"
