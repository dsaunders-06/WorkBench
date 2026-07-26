"""Unattended execution (spec M13).

Four pieces, kept separate so each is testable on its own:

* gate.py - decides whether an order may be signed off unattended. Pure
  arithmetic and clock checks, no LLM, deny-by-default.
* executor.py - applies that decision through OMS.sign_off. The only caller
  in the codebase that signs an order off without a person.
* equity_monitor.py - polls equity and feeds the daily-loss and drawdown
  kill-switch rails, which nothing called before M13.
* journal.py - append-only record of every decision, executed and blocked.

Autonomy is off unless Settings.execution_mode == "auto", and is confined to
paper accounts unless a second flag with no Settings UI is also set.
"""

from qat.domain.autonomy.equity_monitor import EquityMonitor, EquityState
from qat.domain.autonomy.executor import AUTONOMOUS_OPERATOR, AutonomousExecutor
from qat.domain.autonomy.gate import (
    AccountState,
    AutonomyGate,
    GateDecision,
    market_for_symbol,
)
from qat.domain.autonomy.journal import AutonomyJournal, JournalEntry

__all__ = [
    "AUTONOMOUS_OPERATOR",
    "AccountState",
    "AutonomousExecutor",
    "AutonomyGate",
    "AutonomyJournal",
    "EquityMonitor",
    "EquityState",
    "GateDecision",
    "JournalEntry",
    "market_for_symbol",
]
