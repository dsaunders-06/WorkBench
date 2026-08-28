"""The regime note's button says what it does, and leaves a record (item 18).

It was labelled **"Review & Apply"** and its handler was one line:
`self.review_button.setText("Reviewed ✓")`. Nothing else in `src` or `tests`
referenced it.

Being inert toward TRADING is deliberate and right - spec §K is "Review &
Apply, never auto-apply". The defect is the *label*, and what it leaves
behind: the acknowledgement was not journalled, not logged and not persisted,
so it could not serve as evidence that a human saw a regime change before a
trade, and it reset on the next `RegimeEvent`. Same family as M73's framing
that existed only in a docstring and M105's connection test that returned a
tick regardless.

⚠️ **Two halves, and the caption is the weaker one.** A button that changes
its own text is not a record - it is gone at the next event and unanswerable
afterwards. The log line is the deliverable; the tests below are ordered to
say so.

Driven through the real screen, not by calling the handler on a bare object:
the M87 class of defect renders correctly in a logic test and wrong on screen.
"""

from __future__ import annotations

import logging

from qat.config import Settings
from qat.data.broker.adapter import AccountSummary, Position
from qat.domain.events import RegimeEvent
from qat.presentation.dashboard import DashboardScreen
from qat.presentation.runtime import Runtime


class _StubBroker:
    async def account(self) -> AccountSummary:
        return AccountSummary(net_liquidation=100_000.0, cash=50_000.0, buying_power=50_000.0)

    async def positions(self) -> list[Position]:
        return []


def _screen(qtbot, tmp_path, market: str = "ASX") -> DashboardScreen:
    settings = Settings(_env_file=None, data_dir=str(tmp_path), market=market)
    screen = DashboardScreen(Runtime.build_demo(settings=settings, broker=_StubBroker()))
    qtbot.addWidget(screen)
    return screen


def test_the_button_does_not_promise_to_apply_anything(qtbot, tmp_path) -> None:
    """The whole of the original complaint. `&&` is Qt's escape for a literal
    ampersand, so the old caption read "Review & Apply" on screen."""
    label = _screen(qtbot, tmp_path).review_button.text()

    assert "Apply" not in label and "apply" not in label, (
        f"the button reads {label!r} and applies nothing - spec §K's "
        f"'never auto-apply' is a policy, not a caption"
    )


async def test_acknowledging_writes_a_log_line_naming_the_regime(qtbot, tmp_path, caplog) -> None:
    """⚠️ THE DELIVERABLE. Without this the acknowledgement exists only as a
    caption that the next RegimeEvent erases."""
    screen = _screen(qtbot, tmp_path)
    await screen._on_regime(RegimeEvent(label="bull", probs={"bull": 0.8}, exposure_scalar=1.0))

    with caplog.at_level(logging.INFO, logger="qat.presentation.dashboard"):
        screen.review_button.click()

    lines = [r.getMessage() for r in caplog.records if "ACKNOWLEDGED" in r.getMessage()]
    assert len(lines) == 1, f"expected one acknowledgement line, got {lines}"
    assert "bull" in lines[0], (
        f"'acknowledged at 14:02' answers a much weaker question than "
        f"'acknowledged the bull note at 14:02': {lines[0]}"
    )
    assert "nothing was applied" in lines[0].lower(), (
        "the line is read months later by someone establishing what a human "
        "did; it must not imply an action was taken"
    )


def test_an_acknowledgement_before_any_regime_says_unknown(qtbot, tmp_path, caplog) -> None:
    """⚠️ It must not invent a label. Acknowledging nothing in particular is
    still worth recording; recording it as if it named a regime is not."""
    screen = _screen(qtbot, tmp_path)

    with caplog.at_level(logging.INFO, logger="qat.presentation.dashboard"):
        screen.review_button.click()

    line = next(r.getMessage() for r in caplog.records if "ACKNOWLEDGED" in r.getMessage())
    assert "unknown" in line


def test_the_caption_confirms_with_a_zoned_local_time(qtbot, tmp_path) -> None:
    """Items 21 and 40's rule, on a surface added after them: a time shown to a
    human is either session-local or says which zone it is. This does both."""
    screen = _screen(qtbot, tmp_path)
    screen.review_button.click()

    caption = screen.review_button.text()
    assert "Acknowledged" in caption
    assert "AEST" in caption or "AEDT" in caption, caption


def test_the_caption_follows_the_MARKET_not_the_machine(qtbot, tmp_path) -> None:
    """⚠️ Item 21's actual instruction, which is easy to satisfy by accident on
    a box that happens to sit in Sydney. The zone comes from the exchange the
    book trades on; the same click under `market="US"` must not say AEST."""
    screen = _screen(qtbot, tmp_path, market="US")
    screen.review_button.click()

    caption = screen.review_button.text()
    assert "AEST" not in caption and "AEDT" not in caption, caption
    assert "ST" in caption or "DT" in caption, caption


async def test_a_new_regime_resets_the_button_but_not_the_record(qtbot, tmp_path, caplog) -> None:
    """The caption is per-note and SHOULD reset - a tick left standing under a
    new regime would claim an acknowledgement nobody made. The log line is what
    survives, which is the reason the log line exists."""
    screen = _screen(qtbot, tmp_path)

    with caplog.at_level(logging.INFO, logger="qat.presentation.dashboard"):
        screen.review_button.click()
        assert "Acknowledged" in screen.review_button.text()
        await screen._on_regime(RegimeEvent(label="bear", probs={"bear": 0.7}, exposure_scalar=0.5))

    assert "Acknowledged" not in screen.review_button.text()
    assert any("ACKNOWLEDGED" in r.getMessage() for r in caplog.records)


def test_the_handler_still_touches_no_trading_path() -> None:
    """Spec §K, pinned. The rename must not become a licence to wire it up:
    'the AI proposes, the human disposes' means this control reaches no part of
    the trading system, and the fix for a dishonest label was never to make the
    label true by acting."""
    from pathlib import Path

    import qat

    source = (Path(qat.__file__).parent / "presentation" / "dashboard.py").read_text(
        encoding="utf-8"
    )
    handler = source.split("def _on_review_clicked")[1].split("\n    def ")[0]

    for forbidden in (".place_order(", ".sign_off(", ".submit(", "exposure_scalar ="):
        assert forbidden not in handler, f"the acknowledgement must not act: {forbidden}"
