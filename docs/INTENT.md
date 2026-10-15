# QAT intent register

Accepted by DS on 10 October 2026. This register changes only by DS's
explicit decision.

```text
I-1 | QAT presents each recommendation. DS approves or declines.
      On approval, QAT places and manages the whole trade (entry,
      stop, exits) through the IBKR Gateway. Manual order entry
      in TWS does not meet this intent | Target; currently
      advisory-only because entry transmission is blocked pending
      broker verification
I-2 | A more autonomous version is possible later, as a separate
      decision DS makes | Deferred
I-3 | Paper account first. Live trading only by DS's decision
      after a paper rehearsal, with Phase 4 position limits set |
      Binding
I-4 | The strategy is unvalidated, with no edge claim, and every
      recommendation says so | Binding
I-5 | DS approves every order; signing and approval authority
      rests with DS | Binding (reworded 10 October)
I-6 | IBKR is the single data and broker source. Yahoo is a logged cross-check only, except Yahoo earnings dates, which are approved as an event-risk input that can only reduce position size. | Binding (changed by DS 16 October 2026)
I-7 | Phase 1 safety controls (kill switch, pre-trade checks,
      protective stops) are never bypassed | Binding
```

The current advisory-only state is a temporary deviation from I-1. Every next step must aim at restoring I-1, not at living with the deviation.

DS changed I-6 on 15 and 16 October 2026. The [data-source inventory](DATA_SOURCES.md)
records all sources, including indirect ones, and their validation status. A
source is added, removed or changed only by DS's explicit decision. The present
configuration's deviations are recorded there, without silently treating them
as approved.
