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
versions/hashes, receipt/retrieval times, calendar, membership and halt-ledger contents,
exact equity/cash/cost/liquidity inputs, quality decisions, session-wide source
failure state and a fingerprint of the unchanged engine source and its pure
QAT dependencies. Audit noise from a repeated evaluation is not an input.
A later correction requires a new snapshot and cannot mutate an earlier one.

A primary IBKR failure blocks the session while unresolved. The adapter's
`attempt_primary` method permits an explicitly scheduled retry of the same
source and requested symbol scope before 20:00 Sydney time. A successful retry
clears that scope's failure. A success for a different scope cannot clear it;
a failure still present at 20:00 remains blocking. Each attempt, including one
rejected at the deadline, is logged. The adapter does not schedule retries or
use a substitute source. Empty or duplicate requested symbol sets fail closed.

## Finality and output

`run` refuses a naive clock, verifies the snapshot hash, and refuses evaluation
before 17:30 Australia/Sydney. The supplied ledger must contain both the session
and its next open. Missing or unfinished bars block only the affected symbol,
including an explicitly managed departed symbol, and record its reason. A
documented halt removes that symbol's expected bar for the covered session;
the symbol abstains for that session while other symbols continue. A future
receipt similarly blocks only its symbol. A changed engine fingerprint, an
expired session, unresolved source failure, or corrupt storage produces no
candidates.

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
bars, documented halts, unresolved gaps, recovered retries before 20:00,
deadline failure, corruption, unknown session/next-open coverage, expiry, independent
receipt deadlines, later correction isolation, atomic audit reads, Decimal
context independence, partial symbol blocks, immutable candidates, and a
failure that cannot be erased by an unrelated success.

## Questions reserved for review

Real authority files and actual IBKR finality/corporate-action verification still
require operator review and separately authorized data access/backfill. Yahoo
discrepancies are logged only, with no adjudication policy while Yahoo never
supplies data. Retry scheduling, operational filesystem ACLs and backups,
correction-to-card revocation wiring, Phase 1 sizing, OMS,
shadow persistence and paper rehearsal remain outside this build. No strategy
validation or promotion claim is made.
