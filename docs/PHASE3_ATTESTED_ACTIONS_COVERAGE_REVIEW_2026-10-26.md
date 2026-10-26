# Attested actions coverage — local review

DS's corrected 26 October instruction supersedes the earlier explicit-field stop. The merged attestation design already states that a verified daily attestation names the approved files that hold for that session. This change adds no attestation field, schema, ledger reader, hash/chain verifier or write path.

The read-only script and configured shadow runner already verify the ledger against the session and current approved hashes. When that existing loader returns a verified attestation hash, each passes the verified session to IBKRHistoricalBarSource. Without one, it passes None. Conversion and assess_history use max(actions.coverage_end, attested_through or date.min), retaining coverage_start and all other checks. Loaded authority objects, authority content hashes and ledger bytes are unchanged. The adapter already passes its verified date to assess_history.

## Source comparison inventory

Reviewed every src reference to coverage_end and valid_through, including multiline comparisons, plus an AST inventory of direct attribute comparisons. Locations below are from base e89203a; small additions in this branch move later line numbers.

| File and base line | Check | Disposition |
|---|---|---|
| src/qat/operational/ibkr_history.py:266 | Bar session within actions coverage_start/end | Fixed: effective upper end uses the caller's already-verified date; lower end unchanged. |
| src/qat/operational/history.py:1723 | Three-year start and evaluation session within actions range | Fixed: effective upper end uses the existing attested_through argument; lower end unchanged. |
| src/qat/operational/adapter.py:228,230 | Authority valid_through missing or older than evaluation session | Already covered by the preceding verified attested-through guard at 226; unchanged. |
| src/qat/operational/shadow.py:121,174,175 | Real authority date required; stale relative to session | Already rejects missing validity and accepts a current verified attestation through the existing loader/hash condition; unchanged. Source construction now forwards that same verified date. |
| src/qat/operational/history.py:257–270 | Membership daily validity and overall effective interval | Already uses max with attested_through. Individual entry effective_to remains binding; unchanged. |
| src/qat/operational/history.py:1687 | Membership overall effective_to for evaluation session | Already uses max with attested_through; unchanged. |
| src/qat/operational/history.py:1690 | Calendar coverage_start/end encloses required history and session | Not an authority-age gap: it is the range of enumerated approved sessions. An attestation cannot invent absent calendar sessions. Approved calendar covers through 31 December 2027; unchanged. |
| src/qat/operational/history.py:160,162,165,179 | Calendar internal bounds, enumerated session/closure facts and fixed-file validity within those bounds | Schema/fact integrity, not evaluation-session authority age. No attestation is applied; unchanged. |
| src/qat/operational/history.py:237,240,241 | Membership schema requires validity, binds overall effective_to, and requires published_on <= valid_through | Fixed-file schema/publication integrity; unchanged. |
| src/qat/operational/history.py:409,410 | Halt publication chronology relative to fixed valid_through | Fixed-file chronology; no coverage_end field exists on HaltLedger. Unchanged. |
| src/qat/operational/history.py:496 | Whether to serialize the optional fixed halt validity header | Serialization presence check; no session comparison. Unchanged. |
| src/qat/operational/history.py:572,574,575,581,588 | Actions internal range, fixed validity and dated action/capital-return events inside its range | Schema/fact integrity; unchanged. No future event is created by extending effective daily coverage. |
| src/qat/operational/authority_attestations.py:150,152,158,185,192,196 | Base-validity versus scheduled/recorded sessions and append/current-session boundaries | Existing verifier/writer rules, not an unbridged consumer check. No changes or additional reads. |

The remaining load_* occurrences only parse or require validity fields. There are no other unbridged current-session authority-age comparisons in src. The corresponding script authority-validity/membership checks already accept its verified current attestation; their validation is unchanged.

## Regression proof and limits

Portable tests create temporary authorities with the 23 October dates, an actual hash-chained 26 October attestation, and offline ib_async daily bars. Both real shadow entry points originally abstained at the source range check. After only that check was extended, they still exposed the separate history coverage refusal. The complete fix passes both actions gates. Short deliberately incomplete test history still abstains for its own gaps; these tests do not claim strategy readiness or create a usable trading card.

Boundary tests cover sessions before/on the fixed end, verified extension, a session beyond the latest date, no attestation, unchanged coverage_start, existing-loader rejection of broken chains/changed actions hashes, and missing or late attestations. Friday-to-Monday verification skips non-trading weekend days through the existing calendar-driven chain rule. Reads preserve temporary ledger and authority bytes.

Production changes: src/qat/operational/ibkr_history.py; src/qat/operational/history.py; src/qat/operational/shadow.py.

Other changes: scripts/phase3_shadow_readonly_check.py; tests/operational/test_attested_actions_coverage.py; this review note and the implementation plan.

This branch is local and unmerged. It does not change tonight's already-reported e89203a run, re-run a shadow pass, apply volume revisions, modify the real store/authorities, change any approved probe branch, enable QAT, transmit a card or place/cancel an order. Full verification, head and bundle hashes are reported separately after the checks finish. No GitHub CI run is created under the push hold.
