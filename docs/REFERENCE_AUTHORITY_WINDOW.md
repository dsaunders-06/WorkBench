# Minimum Phase 3 reference-authority window — 22 October 2026

This is a reading of `build/card-path-shadow` at `ac97137`, for a **22 October
2026** live shadow-card decision. It does not validate or approve any authority
file. A missing, incomplete, or conflicting authority still makes the card
abstain. The operational IBKR history client asks for `3 Y` daily bars
(`IBKRHistoricalBarSource._fetch`, `src/qat/operational/ibkr_history.py`);
`assess_history` computes `session.replace(year=session.year - 3)` and requires
the expected sessions and real corporate-action coverage from that date
(`src/qat/operational/history.py`). The engine independently takes the same
three-year resistance window (`resistance_history`,
`src/qat/domain/strategies/authoritative_swing/resistance.py`). The recent
21-bar split embargo and shorter pattern/volume windows do not shorten this
gate (`OperationalAdapter.run`, `src/qat/operational/adapter.py`).

| Requirement | Longest operational read and code path | Earliest required coverage for a card on 22 October 2026; needs beyond it? |
| --- | --- | --- |
| **R05 ASX calendar/closures** | `assess_history` calls `calendar.conflicts(start, session)` and checks every expected session from the three-year cutoff. `OperationalAdapter.freeze` and `CardService` need the **next open**; `ExitAlertService._next_resumed_open` may need a later open after a halt (`operational/history.py`, `adapter.py`, `cards.py`, `exit_alerts.py`). | **22 October 2023** through at least the next session, **23 October 2026**, for this card. A file intended to remain usable through 2027 needs the first confirmed 2028 open to support a card on the final 2027 session. Older coverage may be needed if retained halt/action entries have boundary/ex-session dates before the three-year cutoff: `assess_history` checks every past halt entry's endpoints and `OperationalAdapter.freeze` checks every action event against the calendar, without a cutoff. |
| **R06 dated S&P/ASX 200 membership** | `ShadowCardRunner.run_once` and `assess_history` require **one current effective interval** covering the decision day; `OperationalAdapter.freeze` evaluates the current `symbols` and `managed_symbols` (`operational/shadow.py`, `history.py`, `adapter.py`). No operational function replays past membership for the bar window. | **22 October 2026**, in a file whose effective interval includes that date. There is no three-year membership-file requirement for one live card. A subsequent day's card needs a then-current file; managed symbols must still be listed after index departure. Historical dated snapshots are a separate research/replay need. |
| **R07 halt/suspension ledger** | `assess_history` excludes ledger-covered days from expected bars across **three years**; `IBKRHistoricalBarSource._halt_placeholder` rejects an unexplained zero-volume bar; `OperationalAdapter.run` blocks a currently halted card (`operational/history.py`, `ibkr_history.py`, `adapter.py`). `ExitAlertService._next_resumed_open` checks future halt coverage. | Evidence for interruptions affecting **22 October 2023 onward**, plus current status and any future resumption needed for a managed exit. The ledger is append-only (`HistoryStore.accept_halts` and `HaltLedger.__post_init__`, `operational/history.py`). A previously accepted older entry cannot simply be pruned; its boundary dates must remain in the calendar even if the bar window has rolled forward. An empty file is not proof that no halt occurred. |
| **R08 splits/consolidations** | `assess_history` requires an action authority from the three-year cutoff and checks factors, provenance and ex-session details for every bar; `IBKRHistoricalBarSource._convert` composes split factors over its fetched bars; `OperationalAdapter.run` applies a **21 post-split session** embargo (`operational/history.py`, `ibkr_history.py`, `adapter.py`). `OperationalAdapter.managed_split_adjustments` reads split events after a position's `last_adjusted_session`, with **no three-year clamp**. | **22 October 2023** for a new card. For an already managed position, cover actions since its last independently reconciled adjustment, even if that predates 22 October 2023. `OperationalAdapter.freeze` also insists that every retained action ex-session is in the calendar. |
| **R09 dividends/cash in lieu** | `assess_history` checks each bar's ex-session dividend against the action ledger throughout the **three-year** bar window; `IBKRHistoricalBarSource._convert` reads the same event metadata. Held-position cash and basis reconciliation uses the broker transaction/position path and `operational/consolidations.py`, not a bounded new-card lookback. | **22 October 2023** for the card's action authority. Retain earlier event/transaction evidence when a still-managed position or cash-in-lieu reconciliation depends on it; there is no general three-year bound for the full holding lifecycle. |

The date is a **calendar cutoff**, not a demand for a bar on Sunday
22 October 2023. The first expected trading session is the next one. This
analysis assumes the historical events have been fully curated; the schema's
coverage dates alone do not prove that. A real file must pass the loader and
cross-check, be cited, and receive DS approval under [I-6](INTENT.md).

## Separate Phase 2 research and validation

The operational files do **not** become research observations. The [Phase 3
integration contract](phase-3-recommend-mode-integration-spec.md) separates
operational/shadow data from sealed development, validation and holdout data;
[Phase 2 promotion was closed](phase-2-closure.md) before those promotion-tier
datasets were opened. A future Phase 2 replay would require point-in-time
calendar, membership (including departed/delisted names), halt and action
authorities for **every replay decision**, with the engine's three-year
prehistory before the first evaluated decision, plus held-position events
through closure. The [ASX-transferable validation design](superpowers/specs/2026-08-12-asx-transferable-validation-design.md)
specifically calls out point-in-time membership and survivorship bias. No
single earliest research date can be stated until DS approves a new sealed
research interval and protocol; a 2023–2027 operational file would not suffice
for a replay that begins before October 2026.

## Can public notices support operator curation?

| Authority | Agent's assessment for the operational window | Ongoing effort and remaining proof |
| --- | --- | --- |
| **R05 calendar** | **Potentially yes.** ASX's [2023](https://asxonline.com/public/notices/2022/august/0905.22.08.html), [2024](https://asxonline.com/content/asxonline/public/notices/2023/August/0840.23.08.html), and [2025](https://asxonline.com/public/notices/2024/august/0957.24.08.html) annual trade notices and its [2026–27 cash-market calendar](https://www.asx.com.au/markets/market-resources/trading-hours-calendar/cash-market-trading-hours/trading-calendar) give scheduled days; ad hoc closure completeness still needs a notice audit. | Moderate initial backfill/independent session-by-session comparison, then annual refresh and daily notice monitoring. Confirm operational storage/use terms. A draft is not approval. |
| **R06 membership** | **Possible but not yet proved.** The live card needs a dated *current* roster, not three years of rosters. [S&P/ASX 200 notices](https://www.spglobal.com/spdji/en/indices/equity/sp-asx-200/) can document rebalances and interim changes, but a complete current constituent base and every effective change must be proved; the code's `source` field requires `https://www.spglobal.com/`. | High initial roster audit and continuing rebalance/extraordinary-action monitoring. Public viewing does not establish database storage/use rights. |
| **R07 halts** | **Possible only with complete evidence.** ASX [company news](https://www.asx.com.au/connectivity-and-data/information-services/company-news) and notices can justify individual halt spans, but absence of a notice in a casual search is not evidence of no halt. The MFG zero-volume probe shows why the ledger must be checked independently. | High historical notice review per symbol and same-day monitoring of starts, extensions and resumptions; append-only chain maintenance. Licence/retention rights need checking. |
| **R08–R09 actions** | **Possible for a small covered universe, unproved at ASX 200 scale.** ASX [ReferencePoint](https://www.asx.com.au/connectivity-and-data/information-services/reference-data) and [company news](https://www.asx.com.au/connectivity-and-data/information-services/company-news) identify events; a free-notice-only curated ledger would need proof of every split, consolidation and dividend, exact ratio/amount, corrections and cash-in-lieu terms across three years and any older managed holding. | Very high historical and daily issuer-by-issuer review; independent reconciliation to IBKR bars/transactions. Published notices do not themselves settle systematic storage/use rights. |

**Calendar draft blocker.** The [ASX 2026–27 cash-market calendar](https://www.asx.com.au/markets/market-resources/trading-hours-calendar/cash-market-trading-hours/trading-calendar) marks
26 April 2027 open (ANZAC substitute), and [ASX notice 0208.26.02](https://asxonline.com/public/notices/2026/february/0208.26.02.html)
explicitly confirms normal trading on 27 April 2026 despite the NSW holiday.
`asx_holidays` in `src/qat/domain/market_calendar.py` applies a
generic weekend substitution and marks **both** dates closed. As a result,
`CalendarLedger.conflicts` in `operational/history.py` rejects the published
sessions across the three-year history. This branch changes no production
rules. The draft calendar stays outside Git and unwired; a separately reviewed
rule/calendar reconciliation is needed before any real shadow card can pass.

The external `asx-calendar-v1-20231022-through-2027-DRAFT.json` has **1,063
sessions** and **32 cited weekday holiday closures**, with an external
per-closure ASX provenance manifest. Its SHA-256 is
`0f15b244bb3a82cacaad05c9efd6f4620256883dec52b3e38b62a8c2c2e97dd6`.
The manifest's SHA-256 is
`ecc8ae28ed1c615357d2a4925fbd98d68eaab3c0b0245c0b47e88345935d176e`.
The operational loader parses its schema and supplies the 23 October 2026
next open, but `CalendarLedger.conflicts` returns true for today's three-year
window because of 27 April 2026. No full-day ad hoc event was added without
a verified notice; a complete notice-archive audit is still required before
claiming historical completeness. The file also needs a confirmed 2028 next
open before use for a 31 December 2027 card. Neither the file nor this review
approves it for operational use.
