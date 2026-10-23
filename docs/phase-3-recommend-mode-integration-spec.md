# Phase 3: recommend-mode integration — draft specification

**Status:** operator-frozen operational contract, document only. Steps 2–6 of
the implementation plan are not yet authorized, and no trading is authorized.
The authoritative strategy is unvalidated; Phase 2 promotion remains closed
under [the closure decision](phase-2-closure.md).

At about 17:30 `Australia/Sydney` after each ASX closing auction, a new operational adapter takes
a versioned input snapshot from the operational
history store and calls the pure authoritative engine. A `QUALIFIED` setup
becomes a QAT recommendation card containing pattern identity and evidence,
bar/session and source version, proposed raw entry limit, structural stop,
Phase 1-sized whole-share quantity, account risk and applicable risk warnings.
The card always displays **“unvalidated strategy, no demonstrated edge”**.
It expires at the next ASX session's open, matching the strategy's next-open
entry. A missing or unfinished bar blocks only its symbol; session-wide calendar,
time and unresolved IBKR-source failures block the whole session. Abstentions
and missing data produce no executable card.

DS's 23 October 2026 amendment to the step-4 entry ruling specifies a pre-open
`BUY LMT GTD` at the approved card limit, with an IBKR-enforced expiry shortly
after the stock's opening auction (default 10:15:00 Australia/Sydney). The
entry must never fall back to a `DAY` or `GTC` limit. `OPG` is unavailable for
ASX stocks in the observed contract details; the 19 October IBCS reply says
paper mirrors live for this order-type restriction. The one-off paper GTD
probe precedes any production implementation. See the
[Phase 3 decision log](PHASE3_DECISION_LOG.md).

The engine cannot import the UI, OMS, broker, scheduler or network. The new
adapter translates operational snapshots into pure engine inputs; the separate
hand-off layer recalculates current quantity and risk under the Phase 1
safeguards. In the current build, the existing per-order `OMS.sign_off` path is
the only transmission path and requires explicit DS confirmation in
`recommend` mode; opening-auction
transmission remains disabled in the current build, so approval records an advisory decision and
exact manual-entry details, not a broker order. An accepted correction to card
inputs appends a revocation and requires a fresh card and approval before the
next open. Changed quantity or risk at approval requires DS to reconfirm both
the original and current values. Expired cards cannot be approved. The default
account is paper. No order is submitted without DS's approval. Autonomous
trading without that approval is I-2, deferred to a separate DS decision.
Entry sign-off approves the card's whole exit plan: the protective stop, +1R
partial target, breakeven move, upward-only trailing, and next-open exits for
close invalidation and the time stop. QAT is intended to transmit and manage that
approved plan without a further dialog once a reviewed Phase 1 change permits
it. Anything that adds exposure or loosens protection needs fresh sign-off.
Real-money use is blocked until DS separately decides the Phase 4 limits below
and approves an operational release. See the [intent register](INTENT.md).

## Operational bars and separation from research

IBKR is the single primary bar source. If its required bar fails or is not
final, the adapter abstains for that session; it cannot silently substitute
another vendor. Yahoo is a logged cross-check only and never supplies a
replacement bar. Every accepted IBKR bar has its retrieval time and timezone,
exchange session, finalization marker, revision/version and content hash. It
is labelled `OPERATIONAL` at ingestion and stored in a namespace and access
path separate from sealed research evidence. Operational and shadow
data never become development, validation or holdout observations under the
closed protocol. Corrections append a new version; they do not overwrite the
bar or a prior recommendation. Corrections received through the next ASX
session's open are accepted as appended versions; a correction affecting a
card revokes that card and requires a fresh decision. Any related pending OMS
order must be withdrawn or re-reviewed through the OMS, never by the engine
or a direct broker call. Later corrections remain logged for audit and
reconciliation, without retroactively changing a prior card. The adapter
uses raw as-traded prices for orders and a documented split-only analytical
view for indicators. If a
source cannot establish those representations, the strategy abstains.

DS rulings of 13 October 2026 fix the operational daily bar to IBKR `TRADES`
with `useRTH=0` (all-hours); its close includes the ASX closing auction. The
future operational IBKR history client must set `whatToShow="TRADES"` and
`useRTH=False` on its daily-history request. No production operational-history
client exists yet. The existing generic `IBAdapter.get_historical` uses
`useRTH=True` and is not the operational source; this stage does not change it.

Policy B for the future real client: convert each IBKR price float through its
shortest round-trip decimal (`Decimal(repr(value))`), retain the original float
for audit, and require integer volume. An `AS_TRADED` daily OHLC price is valid
on half the applicable ASX order-price step (AUD 0.005 at and above AUD 2);
anything off that half-step grid blocks the symbol. `DERIVED` bars retain the
approved tick exemption and exact-inverse volume rule. Order prices remain on
the full ASX tick. The +1R partial sell target is rounded **up** to the next
full ASX order tick, so the resting limit cannot sell below 1R; the persisted
position plan and exit alert carry that same price.

The operational path relaxes research-only requirements for signed,
physically partitioned shards, a frozen catalog, predeclared signal/tail
boundaries, and custodian release receipts. Those controls exist to protect a
statistical claim and sealed holdout, not to make a supervised daily card.
It does **not** relax final-bar status, chronological uniqueness, valid
OHLCV and exchange/currency identity, corporate-action consistency, correct
raw and split-only prices, current membership, session-calendar and halt
handling, exact-decimal prices and risk, or fail-closed missing-data behavior.
The adapter records source/version and quality decisions so an operational
recommendation can be replayed without treating it as research evidence.

ASX's published trading calendar, refreshed annually and amended with ad hoc
closures from ASX market notices, is the session authority. The repository's
rule-based calendar is a cross-check only; a disagreement blocks affected
cards pending review. S&P/ASX 200 quarterly rebalance announcements are the
universe authority, recorded as a dated, versioned membership file. A symbol
leaving the index receives no new cards, while its existing positions continue
to be managed under the applicable safety and exit rules.

The history store maintains at least three complete years of finalized daily
bars for every current universe symbol, including suspended or departed-symbol
history needed for a held position. It checks expected trading sessions,
duplicates, ordering, gaps, stale last sessions, nonpositive or contradictory
OHLCV, raw tick validity, source revisions and split/dividend continuity.
Missing or disputed required history blocks that symbol's recommendation; no
forward fill or silent vendor substitution is allowed.

## Shadow record and risk boundary

Every recommendation receives an append-only record at creation, whether
approved, declined, expired or ignored. It includes input snapshot and engine
version hashes, card evidence and risk, operator disposition, and any OMS
order ID. Later records append a hypothetical entry, fill, exit, corporate
action, halt and terminal lifecycle under the Phase 2 replay rules, separately
from actual paper execution. Corrections add linked events; they never rewrite
the original card. The shadow record is retained indefinitely and included
in backups; reviewers receive read-only access while the designated writer
may append. Shadow results are operational review material, not an edge claim
or a substitute for a newly declared promotion protocol.

Sizing and transmission use the existing Phase 1 risk controls. The proposed
Phase 4 starting values are **inactive on paper**: no more than 10% of equity
in one position, no more than 5% total risk at the stops, no more than 25% of
equity in one sector, a stop at least 2% below the raw entry price, and an
order quantity no greater than 1% of the stock's 20-day median daily share
volume. These are judgment-based safety
limits to evaluate and decide before any real-money use, not evidence-based
return settings or changes to Phase 1 paper controls. The adapter remains
paper-default and recommend-only; real money needs a separate operator
decision and release.

Isolation acceptance requires static transitive-import checks and runtime
tests proving that the pure engine has no path to UI, OMS, broker adapter,
network or order submission. The operational adapter cannot import UI, OMS or
execution paths; the separate hand-off layer may import the adapter and Phase 1
OMS interfaces. A second set proves that, in the current build, no card,
rejected card, stale card or global auto-mode setting can transmit without the
Phase 1 OMS risk check and explicit per-order human sign-off.
