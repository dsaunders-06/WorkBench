# Phase 1 exit readiness — offline findings, 13 October 2026

The sections below preserve the 13 October investigation as the baseline.
DS approved the Phase 1 exit-readiness batch on 15 October; the implementation
record follows the baseline. The Monday, Tuesday and Wednesday DU-paper probes
provide non-synthetic evidence where stated. This batch does not authorize a
production exit transmission, a stop-trigger test or an opening-auction entry.

## 1. Holding identity

**Current behaviour and evidence.** `data/broker/ib_translate.py::from_ib_position`
translates `position.contract.symbol` using the configured market and returns
the Phase 1 `Position` (`data/broker/adapter.py`) with symbol, quantity, basis
and optional mark, but no account, conId, exchange or currency. In
`data/broker/ib_adapter.py::positions`, `IB.positions()` is a keyed cache, so
the Monday duplicate *callback* defect in the old probe does not cause this
production path to sum the same row twice. Its companion `_portfolio_marks`
keys marks by raw symbol alone. The Monday and Tuesday BHP probe used qualified
ASX conId 4036812; Tuesday's raw callbacks contained duplicate 9-share rows,
while the keyed cache held one 9-share position. The Monday 18-share reading
was reproduced offline from duplicate callbacks but its original log lacks
the individual rows, so that occurrence is not reconstructed with certainty.

`data/broker/account_poller.py::AccountPoller._fetch` preserves the adapter's
list as a tuple, without validating identity. `domain/oms/oms.py::OMS.check_reconciliation`
reduces broker positions to `{pos.symbol: pos.quantity}`: same-symbol contracts
overwrite one another rather than sum. `operational/consolidations.py::ConsolidationReconciler.apply`
and `operational/exit_alerts.py::ExitAlertService._holding_matches` filter by
symbol; two matching rows freeze, but one wrong-contract row with the expected
quantity can pass. `operational/cards.py::CardService._size` compares holdings
with snapshot symbols and builds symbol-keyed portfolio weights; duplicate
identities collapse in those weights. `domain/oms/position_view.py::build_position_views`
creates one row per supplied holding but looks up entries and stops by symbol;
`presentation/dashboard.py::_refresh` and `_populate_positions_table` display
those rows without account or conId. No audited production path sums
`reqPositionsAsync` callback results; the identity problem is loss of contract
identity when the keyed cache is translated.

**Risk.** A same-symbol non-ASX contract or another account can be read as a
QAT ASX holding, affect sizing, pass an exit holding check, or conceal a
reconciliation difference. A symbol-only mark can belong to another contract.

**Proposed change — touches Phase 1 code:** carry `(account, conId)` plus
`secType=STK`, `primaryExchange/exchange`, and `currency=AUD` through the
broker-position model and mark lookup. Before a QAT holding is used by OMS,
poller or panel, require exactly the expected DU account and qualified ASX
stock conId; quarantine/freeze any other holding instead of aliasing it by
symbol. Keep the symbol for display and strategy lookup, not identity. In the
operational consolidation, card and alert layers, compare the same identity
and freeze on mismatch. Tests should deliver duplicate callbacks, distinct
same-symbol conIds, another account, a non-stock and a non-AUD contract; verify
the first deduplicates in `IB.positions()` and every other mismatch freezes
without changing quantity or sending an order. A read-only real DU position
snapshot should confirm the fields and cache behaviour before release.

## 2. Current-quote provenance and failure behaviour

**Current behaviour and evidence.** `data/broker/ib_adapter.py::connect`
requests market-data type 3. `_finite_quote` discards non-finite and
nonpositive bid/ask/last; `get_market_data` streams a qualified contract and
returns only finite prices, or `{}` after its bounded wait or a request
failure. It does not return the observed marketDataType, source timestamp or
age. Tuesday's standalone probe separately required type 3 and a source
timestamp no older than 30 minutes; that guard is not in this adapter.

`domain/oms/oms.py::OMS._costing_price` uses a limit or filled price first,
then ask/last from `get_market_data`, then `reference_price`. A missing quote
can therefore fall back to a submission-time reference; with no usable price
the sign-off cash check rejects. Its `or` expression would let a NaN ask hide
a finite last from a different broker implementation, though the IB adapter
filters NaN. It does not record quote type or age. An opening-auction card has
a limit, so this costing path would choose that limit if transmission is later
enabled. `operational/cards.py::CardService._size` obtains fresh equity/cash
and broker positions at approval but makes no direct quote request; its
portfolio weights use each position's `current_price or avg_price`. The
`current_price` comes from `IBAdapter._portfolio_marks`, where nonpositive and
NaN marks are discarded, but market-data type and mark time are absent. A
missing mark therefore uses average cost for weights without labelling its
age. `operational/exit_alerts.py::entry_fill`, `target_fill` and
`completed_close` do not request a current quote; they use confirmed fills,
broker quantity and completed bars. `data/broker/account_poller.py::_degrade`
retains the last snapshot with an age/error label. The positions panel
(`domain/oms/position_view.py::_last_price`,
`presentation/dashboard.py::_refresh`) uses that mark or shows no Last/P&L
when absent, but a present mark has no source age or type. The snapshot age is
the account poll time, not the quote's source age.

`domain/autonomy/executor.py::AutonomousExecutor._current_price` requests a
broker quote, chooses the first finite positive last/ask/bid, then tries its
feed fallback. If the request raises, all fields are missing/NaN/nonpositive,
and the fallback is absent, raises or is invalid, it returns `None` and logs
that the price-drift check was **skipped**. `AutonomyGate.evaluate` tests drift
only when `current_price is not None` and `order.reference_price` is truthy.
Neither the quote's type nor source age is recorded, and the fallback may be a
bar close rather than a current quote. This autonomous executor is not reached
by recommend-mode cards: `Settings.autonomy_enabled` is false unless mode is
`auto`, `_on_pending` and `retry_pending` return early, and
`CardService.approve` does not call it. It is still a Phase 1 readiness gap
before any future use of that executor.

**Risk.** Type-3 quotes can be accepted at an unknown age; a broker mark can
look current because the account snapshot is fresh; a missing quote can turn a
drift check into no check. This does not meet DS's 12 October provenance
ruling for checks that use a current quote.

**Proposed change — touches Phase 1 code:** return a typed price observation
with value, field, marketDataType, source timestamp and observed timestamp from
the IB adapter; enforce a stated age bound at each current-quote consumer, and
log the observation used or the refusal. Keep NaN/missing/stale as distinct
states. Reconsider whether `OMS._costing_price` may use a stale reference for
recommend-mode sign-off; the limit is a known worst-case buy price, but it is
not a current quote. The operational card and exit layers should show the
relevant observation and abstain/freeze where a current price is required.
Tests should cover type 3 with fresh/stale timestamps, missing timestamp,
NaN fields, a quote absent with and without fallback, and a portfolio mark
whose poll is fresh but source timestamp is old. A read-only DU streaming
observation should confirm actual field/timestamp behaviour; synthetic prices
alone cannot prove it.

## 3. Execution time and fill window

**Current behaviour and evidence.** In `ib_async` 2.1.0,
`objects.py::Execution.time` is a `datetime`; `decoder.py::execDetails`
parses the broker time, applies `TimezoneTWS` when it is naive, and converts
to `wrapper.defaultTimezone`. The saved probe JSON serialised the resulting
value but did **not** record its Python type or the exact tzinfo object. Its
`+00:00` offset and library code support an aware UTC `datetime` inference;
Wednesday's script now records type and tzinfo directly to verify it.

Monday's live order log (SHA-256
`4fa95270e469fd0fd4bf89ce05eb6ad92aedca84e90576883f9b098f9cf02b83`)
shows buy `execution.time=2026-10-11 12:25:16+00:00` against receipt at
`2026-10-11 23:25:18+00:00`. The independent Monday `reqExecutions` recheck
(SHA-256
`026fc41ff902f7b04198e954dd4733b7e49e9bcb8b543b1155f5c9a67323f069`)
reports that same execution at `2026-10-11 23:25:16+00:00`, matching the
10:25 Sydney event. Tuesday's live order log (SHA-256
`5fd91005d351fa7660d05acc02a423cebf6e1f395829611257807c215e21ed50`)
again shows both live fill execution times 11 hours before receipt/status.
The broker wire time string and `TimezoneTWS` value were not saved, so the
origin of the difference is unproven.

`data/broker/ib_translate.py::from_ib_fill` carries `execution.time` unchanged
to `BrokerFill.filled_at`. `data/broker/ib_adapter.py::IBAdapter.recent_fills`
gets `reqExecutionsAsync`, then applies `fill.filled_at <= since` as an
exclusive cutoff. Comparing aware UTC datetimes is mechanically correct, and
the independent Monday **recheck** timestamp would pass a cutoff just before
the actual fill. The live callback timestamp would not. The code cannot
assume those two IBKR paths agree. `OMS._fill_query_floor` extends the cutoff
one second and for outstanding partials; it cannot correct an 11-hour shift.
`OMS._announce_fill` uses its own `_now()` for an immediate acknowledged fill.
The production `PositionView`/dashboard does not convert or show
`execution.time` in Sydney; account snapshot display uses a separate Sydney
formatter. Other journals store/compare `filled_at` as ISO datetimes.

**Risk.** A shifted execution timestamp can cause a stop/target fill to fall
behind the watermark, preventing attribution and making reconciliation halt.
Displaying UTC without the session zone can also mislead an operator reviewing
order timing. The observed recheck suggests the recent-fills path may be
correct, but that has not been established for every fill type.

**Proposed change — touches Phase 1 code if the discrepancy is confirmed in
production:** first capture live callback and `reqExecutions` versions of the
same paper execution, including raw wire time, `TimezoneTWS`, Python type,
tzinfo, order ID and local receipt. Resolve the parser/broker-time contract
before changing a cutoff. Then normalise once at the broker boundary to an
aware UTC instant and format Sydney time only for display. Tests should replay
the two observed timestamps against a realistic watermark, cross midnight and
DST, and verify a stop fill is neither dropped nor doubled. Do not substitute
receipt time for execution time without DS review.

## 4. permId arriving after the five-second wait

**Current behaviour and evidence.** `IBAdapter.place_order`, `_place_bracket`
and `_place_oca` wait through `_await_perm_id`; on timeout they return the
application ID instead of `0` and log a warning. Tuesday's paper market exit
filled, but the adapter warned at five seconds before its completed trade
showed permId `1320325307`. `OMS._sign_off_locked` writes a durable
`transmitting` identity before calling the broker, then `accepted`, records
the application ID in `_transmitted`, and refuses a second sign-off. A process
crash in the transmission window trips the kill switch on restart. A late
permId alone therefore does not make OMS automatically resubmit an entry,
stop or market exit.

For a **resting stop**, `IBAdapter._adopt_from_broker` can rediscover its
permId through open orders when a later modify/cancel uses that ID, and emits
`BrokerOrderIdResolvedEvent`; `OMS._on_broker_order_id_resolved` persists the
alias. For a rapidly filled **entry or market exit**, that open-order route
may already be gone. `IBAdapter.recent_fills` can instead use a UUID-shaped
`orderRef` via `from_ib_fill.app_order_id` to publish the same alias; the OMS
registers it before accounting the fill. The probe's textual orderRef is not
a UUID and does not exercise that production alias route. If the execution
query omits a fill because of the time-window discrepancy above, or orderRef
is absent/noncanonical, that reconciliation route is not proven. The
application may hold a transmitted order while a broker fill lacks its
identity; existing mismatch/kill-switch handling is safer than a duplicate
order, but does not complete QAT-managed exit attribution.

**Proposed change — touches Phase 1 code:** retain the durable no-resubmit
invariant, add an explicit pending-identity state and bounded reconciliation
for each transmitted leg, keyed by account/conId/orderRef/clientId and broker
IDs. Do not treat a missing permId as a rejected order. Require acceptance and
fill evidence before closing that state, and halt further exposure-changing
steps while an identity is unresolved. Tests should delay permId beyond five
seconds for entry, stop and market exit; include immediate fill/no open order,
restart, a missing orderRef, a stop that remains working, and a duplicate
sign-off attempt. The Wednesday paper run should measure the market exit's
actual permId delay and both stop modification acknowledgements; that real
evidence is needed before a production design is approved.

## 5. Implementation record — DS approval, 15 October 2026

This batch carries IBKR account and contract identity through `Position` and
its mark. `IBAdapter.positions` deduplicates the keyed cache, checks the
configured DU account and qualified ASX stock conId, and labels every other
holding foreign. The OMS, governor, account poller, operational card and exit
paths exclude foreign shares from QAT quantity and sizing. A foreign holding
blocks new exposure account-wide; it remains visible with account, conId,
security type, venue and currency. Protective and exit orders for a QAT
holding continue. Test brokers lacking IBKR contract identity retain an
explicit simulation default; the IB adapter classifies real IBKR rows.

`IBAdapter.price_observation` returns value, field, broker market-data type,
source timestamp and observation timestamp. The bound is the single
`Settings.current_quote_max_age_seconds` value, fixed at 1800 seconds pending
another DS decision. The OMS uses a limit as the buy's costing ceiling and
otherwise requires a fresh source-dated quote for market buys. The deferred
autonomous executor also requires such an observation before its drift gate;
it no longer treats a historical bar close as a production current quote or
silently skips drift. The positions panel labels broker marks and shows their
observed time. Historical replay has a separately labelled tier-0
`simulated_bar_close` observation at its simulated clock. It is a synthetic
replay input, not evidence of live quote freshness or data fitness.

`from_ib_fill` accepts only timezone-aware execution times from
`reqExecutions` and normalises them to UTC. The IB adapter reads its local
streamed-fill cache only to compare the two reported times by execId; a
difference over one second logs both values, the host zone and
`TimezoneTWS`. It never uses the streamed time as the ledger timestamp.
No `TimezoneTWS` setting was changed. The 14 October paper probe observed
two streamed/requested pairs exactly 11 hours apart, with requested times
matching local receipts. The broker wire string was not captured, so the
cause remains an inference rather than a verified parser diagnosis.

Each IBKR leg now has a canonical UUID orderRef. A primary leg uses the
application UUID when canonical; attached stop and target legs use stable
UUIDv5 references in the fixed namespace in `pending_legs.py`. For a buy,
the configured-account IB adapter durably writes each leg's account, conId,
clientId, orderRef and application ID before broker hand-off. For a protective
or exit sell it transmits first, then writes the additional per-leg record;
the existing OMS application-order intent is durable before transmission.
This ordering prevents the additional file from delaying an exposure-reducing
order. A zero permId remains
pending, including after a five-second wait. A bounded open-order and
`reqExecutions` read resolves the matching broker identity. While a leg is
unresolved, new buys for that symbol are refused; stop and exit placement
does not wait for a permId. The OMS's existing durable sign-off record still
prevents duplicate transmission across restart. The per-leg record adds
identity evidence without replacing that guard.

The program has no production subscription to streamed fill callbacks.
`IBAdapter.recent_fills` reads `IB.fills()` only as a local diagnostic cache,
and obtains attributable fills from `reqExecutions`. `OMS.absorb_broker_fills`,
the signal bridge and trade ledger consume the resulting `BrokerFill`; the
immediate sign-off announcement uses the OMS clock and is later corrected by
the requested execution. No streamed callback advances a fill watermark.

## 6. Proposed OMS paper round trip — draft, **not authorised to run**

Use one DU paper account through QAT's own OMS and IB adapter, after 10:30
Sydney on a session DS specifies. Recheck the DU account before every Gateway
request. Confirm no BHP.AX holding or working order, no unresolved identity,
and a type-3 BHP observation with source timestamp at most 30 minutes old.
Compute the minimum whole-share parcel reaching AUD 500 from that quote and
abort if the estimated buy exceeds AUD 800. Record source time and age.

1. DS signs off one diagnostic BHP.AX BUY MKT through OMS; this tests the
   safety and identity path and is **not** a substitute strategy entry rule.
   Confirm the exact fill and `reqExecutions` alias to its UUID orderRef.
2. DS signs off one SELL STP GTC for exactly the held shares at the full-tick
   floor of 90% of the reference price. Confirm the broker's working stop,
   orderRef, orderId and permId, allowing pending identity until the
   bounded broker reconciliation resolves it.
3. Raise that same stop one ASX tick through the OMS/adapter modification
   path and confirm the acknowledged broker auxPrice. Cancel and confirm
   cancellation before any market exit.
4. DS signs off one SELL MKT for exactly the confirmed holding. Confirm the
   fill through `reqExecutions`, UTC attribution, orderRef alias, a flat BHP
   position and no working BHP order. Record every status, time, commission,
   identity transition and the final account state.

Stop at the first unexpected broker state. Use only the separately approved
emergency exit for this probe's own shares; never retry a transmission on a
missing permId. The diagnostic market buy does not prove an opening-auction
entry. That and any stop-trigger test remain separate DS decisions.
