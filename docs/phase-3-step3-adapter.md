# Phase 3 step 3 — frozen operational adapter

Only steps 2 and 3 are authorized. This stage adds an offline adapter, not an
application service. No UI card wiring, Phase 1 sizing, OMS hand-off, shadow
record lifecycle, paper rehearsal, real backfill or vendor connection exists.
The Phase 2 engine and tick utility have not changed.

## Frozen input

`HistoryStore.read_view` copies accepted bar versions and source/quality audit
events in one SQLite read transaction. `OperationalAdapter.freeze` assesses
that immutable view against the supplied calendar and membership authorities,
then hashes the entire snapshot. It includes raw and split-only OHLCV, source
versions/hashes, receipt/retrieval times, calendar and membership contents,
exact equity/cash/cost/liquidity inputs, quality decisions, session-wide source
failure state and a fingerprint of the unchanged engine source and its pure
QAT dependencies. Audit noise from a repeated evaluation is not an input.
A later correction requires a new snapshot and cannot mutate an earlier one.

A source failure remains blocking for its entire session. Later successes,
including for another symbol, cannot clear it. Source audit entries also retain
the requested symbol scope. Empty or duplicate requested symbol sets fail
closed. There is no automatic unblock/recovery operation in this stage.

## Finality and output

`run` refuses a naive clock, verifies the snapshot hash, and refuses evaluation
before 17:30 Australia/Sydney. The supplied ledger must contain both the session
and its next open. Every required symbol, including explicitly managed departed
symbols, must have its session bar and finalized required history. Missing or
unfinished required bars block the session and record symbol-specific reasons.
Future-received inputs, a changed engine fingerprint, an expired session,
source failure, or corrupt storage produce no candidates.

After finality, other integrity failures block only affected symbols. Departed
managed symbols retain history sufficiency checks but receive no new candidates;
position management execution remains outside this stage.

The adapter constructs the engine's existing `SwingHistory` and `FinalBar`
inputs without modifying the engine. It passes exact balances, cost/liquidity
profiles and the evaluation session. Only `QUALIFIED` setup envelopes become
frozen `CardCandidate` values. Each contains the complete immutable engine
`SetupDecision` (pattern identities, pattern evidence, sizing quantities and
rules), raw entry limit, raw protective structural stop and invalidation,
source record references with versions/hashes and OPERATIONAL labels, snapshot
and engine hashes, and expiry at the next ledger open. Every candidate contains
`unvalidated strategy, no demonstrated edge`. The engine's quantity is evidence,
not a Phase 1-sized executable instruction. No Phase 1 quantity is added now.

Rejected setups, abstentions, blocked symbols and engine exceptions produce
immutable reason records. The adapter appends those reasons to the OPERATIONAL
quality audit; it does not persist cards or create the step 5 shadow lifecycle.
If the store itself is inaccessible, the immutable returned abstention is the
available record and persistence is not claimed.

The engine runs within its existing fixed Decimal precision/rounding policy.
Candidate and abstention serialization uses canonical UTF-8 JSON: Decimal as
exact canonical strings, ordered immutable tuples, sorted object keys, ISO
dates/timestamps, and no binary floats. Valid runs of the same snapshot produce
byte-identical output; clocks outside its eligibility interval instead receive
fixed finality/expiry refusals.

## Isolation evidence

`test_operational_isolation.py` walks QAT imports transitively,
including function/conditional imports, TYPE_CHECKING branches and package
initializers. Typing-only imports cannot expand the broker exception. UI/presentation,
OMS, scheduler, execution and network dependencies are prohibited; the engine
also cannot import the operational adapter. Dynamic imports/eval/exec are
rejected. The broker allowlist is exactly `qat.data.broker.ticks`, with mutation
controls proving any additional broker import fails. Ticks must import only
the standard library and `qat.domain.market_calendar`; broker/__init__.py must
contain no imports or calls. The source corpus helper prevents an empty scan
from masquerading as isolation.

The runtime test traps every function and method defined in the repository's
OMS and broker modules except ticks, plus socket/DNS, HTTP, requests and IB
client entry points. The unchanged real engine still produces the qualified
fixture candidate. All tests retain the suite-wide network guard.

Other fixtures verify the 17:30 boundary in Sydney and UTC, unfinished managed
bars, corruption, unknown session/next-open coverage, expiry, independent
receipt deadlines, later correction isolation, atomic audit reads, Decimal
context independence, partial symbol blocks, immutable candidates, and a
failure that cannot be erased by an unrelated success.

## Questions reserved for review

Real authority files and actual IBKR finality/corporate-action verification still
require operator review and separately authorized data access/backfill. Yahoo
discrepancies are logged only; any additional discrepancy adjudication policy
is undecided. A production unblock/recovery workflow, operational filesystem
ACLs and backups, correction-to-card revocation wiring, Phase 1 sizing, OMS,
shadow persistence and paper rehearsal remain outside this build. No strategy
validation or promotion claim is made.
