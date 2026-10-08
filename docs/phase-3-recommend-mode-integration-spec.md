# Phase 3: recommend-mode integration — draft specification

**Status:** document for operator review; no implementation or trading
authorization. The authoritative strategy is unvalidated, and Phase 2
promotion remains closed under [the closure decision](phase-2-closure.md).

At each ASX close, after all required daily bars are finalized, a new
operational adapter takes a versioned input snapshot from the operational
history store and calls the pure authoritative engine. A `QUALIFIED` setup
becomes a QAT recommendation card containing pattern identity and evidence,
bar/session and source version, proposed raw entry limit, structural stop,
Phase 1-sized whole-share quantity, account risk and applicable risk warnings.
The card always displays **“unvalidated strategy, no demonstrated edge”**.
Abstentions and missing data produce no executable card.

The engine cannot import the UI, OMS, broker, scheduler or network. The new
adapter is the sole translation boundary. It may hand a reviewed card to the
existing Phase 1 OMS risk pipeline, which recalculates current quantity and
risk before any order is queued. Only the existing per-order `OMS.sign_off`
path may transmit, after explicit human confirmation in `recommend` mode.
Any changed price, stop, quantity, risk or stale session requires a fresh card
and approval. The default account is paper. No autonomous submission is
allowed; real-money use is blocked until the operator separately decides the
Phase 4 limits below and approves an operational release.

## Operational bars and separation from research

Every accepted vendor or broker bar has a named source, retrieval time and
timezone, exchange session, finalization marker, revision/version, and content
hash. It is labelled `OPERATIONAL` at ingestion and stored in a namespace and
access path separate from sealed research evidence. Operational and shadow
data never become development, validation or holdout observations under the
closed protocol. Corrections append a new version; they do not overwrite the
bar or a prior recommendation. The adapter uses raw as-traded prices for
orders and a documented split-only analytical view for indicators. If a
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

The history store maintains at least three complete years of finalized daily
bars for every current universe symbol, including delisted or suspended
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
the original card. Shadow results are operational review material, not an
edge claim or a substitute for a newly declared promotion protocol.

Sizing and transmission use the existing Phase 1 risk controls. Before any
real-money use, the operator must separately decide and test Phase 4
per-position notional and concentration caps, aggregate risk-at-stop and
simultaneous-position limits, sector/correlated exposure limits, minimum
stop-distance or maximum cost-to-risk rules, liquidity/participation limits,
and overnight-gap and corporate-event exposure limits. Their values are not
chosen in this document. Until then the adapter remains paper-default and
recommend-only.

Isolation acceptance requires static transitive-import checks and runtime
tests proving that the pure engine has no path to UI, OMS, broker, network or
order submission; only the adapter can call outward. A second set proves that
no card, rejected card, stale card or global auto-mode setting can transmit
without the Phase 1 OMS risk check and explicit per-order human sign-off.
