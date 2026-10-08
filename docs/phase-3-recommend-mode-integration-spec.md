# Phase 3: recommend-mode integration — draft specification

**Status:** operator-frozen operational contract, document only. Steps 2–6 of
the implementation plan are not yet authorized, and no trading is authorized.
The authoritative strategy is unvalidated; Phase 2 promotion remains closed
under [the closure decision](phase-2-closure.md).

At about 17:30 `Australia/Sydney` after each ASX closing auction, and only
after all required daily bars are finalized, a new operational adapter takes
a versioned input snapshot from the operational
history store and calls the pure authoritative engine. A `QUALIFIED` setup
becomes a QAT recommendation card containing pattern identity and evidence,
bar/session and source version, proposed raw entry limit, structural stop,
Phase 1-sized whole-share quantity, account risk and applicable risk warnings.
The card always displays **“unvalidated strategy, no demonstrated edge”**.
It expires at the next ASX session's open, matching the strategy's next-open
entry. Abstentions and missing data produce no executable card.

The engine cannot import the UI, OMS, broker, scheduler or network. The new
adapter is the sole translation boundary. It may hand a reviewed card to the
existing Phase 1 OMS risk pipeline, which recalculates current quantity and
risk before any order is queued. Only the existing per-order `OMS.sign_off`
path may transmit, after explicit human confirmation in `recommend` mode.
Any changed price, stop, quantity, risk, bar version or stale session revokes
the card and requires a fresh one and fresh approval. The default account is
paper. No autonomous submission is allowed; real-money use is blocked until
the operator separately decides the
Phase 4 limits below and approves an operational release.

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
tests proving that the pure engine has no path to UI, OMS, broker, network or
order submission; only the adapter can call outward. A second set proves that
no card, rejected card, stale card or global auto-mode setting can transmit
without the Phase 1 OMS risk check and explicit per-order human sign-off.
