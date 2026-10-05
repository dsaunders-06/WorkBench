# Phase 2D Stage A declaration authority (implementation only)

**Status: unsigned, unsubmitted, unconfigured.** No `EFFECT_DECLARED`,
`PROMOTION_PROTOCOL_DECLARED`, or `METHOD_AUDIT_DECLARED` has been signed,
timestamped, or written to a production ledger. The Stage A source is an
offline-verifiable authority boundary and synthetic release gate. It is not an
operator service deployment.

The operator or appointed custodian must keep the declaration signing key and
development/validation decryption keys outside this repository and outside the
automated-agent account. The operator-controlled service supplies a pinned
signing certificate path, RFC 3161 timestamp policy and trust path, fresh
signed CRLs, a scoped append-only ledger, and an atomic compare-and-append
operation. `append_declaration` requires that external authority; an ordinary
agent call without it raises `SigningAuthorityError`. It checks the exact
canonical record, signature, timestamp imprint, certificate validity and
revocation, sequence, nonce, identities, prior head, and strictly increasing
declaration/timestamp chronology before appending. A three-record verified
chain is required before development release. The initial head is 64 zeroes;
each subsequent record binds the exact previous receipt head.

`EFFECT_DECLARED` must supply a positive exact-decimal `delta_MME` string and
economic rationale. The protocol record binds every data, Phase 4 risk, tail,
statistical, feasibility and promotion rule family. The method record binds
the candidate family, scenario matrix, generators, seeds, size/power caps,
code hash and generic-pilot report hash. The operator must review and freeze
the [unsigned draft](METHOD_AUDIT_DECLARED_UNSIGNED_DRAFT.json), the full pilot,
the source decision and the [freeze proposals](phase-2d-operator-freeze-proposals.md)
before any real record is attempted.

The offline RFC 3161 verifier accepts DER CMS SignedData with one SHA-256
SignerInfo, SHA-256 message imprint and ESS signer-certificate binding. It
requires a pinned root, current signed CRLs, exclusive timeStamping EKU, an
approved timestamp policy OID, and a time inside the signer certificate's
validity. Unsupported CMS structures fail closed. The
[`tests/promotion/fixtures/rfc3161-throwaway-test-only`](../tests/promotion/fixtures/rfc3161-throwaway-test-only)
directory contains a recorded token and public test PKI for offline tests;
its private keys are outside Git and labelled **THROWAWAY TEST ONLY**. OpenSSL
independently verified that token before it was recorded. Tests make no live
timestamp-authority calls.

**Timestamp authority proposed for operator approval only:** DigiCert's
[RFC 3161 service](https://knowledge.digicert.com/general-information/rfc3161-compliant-time-stamp-authority-server),
subject to operator review of its [public-trust CP/CPS](https://www.digicert.com/content/dam/digicert/pdfs/legal/digicert-public-trust-cp-cps.pdf),
certificate policy OID, chain, trust anchor, revocation capture, terms of use,
and operational suitability. DigiCert reports replacement of three timestamp
certificates on 3 September 2026. No endpoint or trust anchor is selected or
configured by this proposal. The operator must approve an authority and
freeze the exact responder/policy/trust inputs before making a live request.

The actual service implementation and deployment need a separate operator
review of account separation, atomic ledger persistence and recovery,
certificate/CRL provenance, and the real role assignment. One person may fill
multiple human roles, but the accounts and keys remain distinct and the
runbook must not claim independent human review in that case. Stage B and all
promotion-data access remain locked.
