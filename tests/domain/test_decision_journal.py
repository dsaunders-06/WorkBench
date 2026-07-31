"""The decision journal records what changed, not what repeated (M31b/6).

A strategy re-emits its signal on every tick, so a standing refusal is
re-decided once a minute for as long as the setup holds.
"""

from __future__ import annotations

from qat.domain.decision_journal import DecisionJournal, JournalEntry

# --- Repeat suppression (M31b/6) -------------------------------------------


def _entry(symbol: str, outcome: str, reason: str) -> JournalEntry:
    return JournalEntry(
        order_id=f"{symbol}-{outcome}", symbol=symbol, side="buy", outcome=outcome, reason=reason
    )


def test_the_same_verdict_repeated_is_recorded_once(tmp_path):
    """SPY was refused by the cost rail 249 times in one session - 249 of 262
    rows - burying every real event under a decision that had not changed."""
    journal = DecisionJournal(tmp_path)

    for _ in range(50):
        journal.record(_entry("SPY", "rejected", "cost 13.2% of risk, above the 10% limit"))

    assert len(journal.entries()) == 1


def test_a_changed_verdict_is_always_written(tmp_path):
    """The journal must still show when a refusal started and when it stopped."""
    journal = DecisionJournal(tmp_path)

    journal.record(_entry("SPY", "rejected", "cost above the limit"))
    journal.record(_entry("SPY", "rejected", "cost above the limit"))
    journal.record(_entry("SPY", "auto_signed", "within limits"))
    journal.record(_entry("SPY", "rejected", "cost above the limit"))

    outcomes = [row["outcome"] for row in journal.entries()]
    assert outcomes == ["rejected", "auto_signed", "rejected"]


def test_suppression_is_per_symbol(tmp_path):
    journal = DecisionJournal(tmp_path)

    journal.record(_entry("SPY", "rejected", "same reason"))
    journal.record(_entry("AAPL", "rejected", "same reason"))

    assert len(journal.entries()) == 2
