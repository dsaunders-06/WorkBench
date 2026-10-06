# Phase 2D Stage A security corrections for operator review

**Scope:** Part 1 only. No real operator key was generated, read or used. No
declaration, data release, permit or rerun was signed, submitted or timestamped.
All cryptographic signing in tests used runtime-generated throwaway Ed25519
keys. The RFC 3161 tests use a recorded, public throwaway token and make no
live timestamp-authority calls.

The operator signature path now verifies Ed25519 against the raw public key
and its SHA-256 fingerprint in fixed custodian-owned configuration. Production
calls reject injected trust. Declaration receipts carry signatures and RFC
3161 tokens but no caller-supplied verification key. Declaration append accepts
an already signed, timestamped receipt and has no signing or timestamp
capability. Reference, development and validation releases, and development
reruns require a separately signed, domain-separated approval before a receipt
is committed. A replacement bundle re-verifies its rerun approval. Operator
IDs and software role checks are workflow labels, not security controls.

The [offline operator script](../scripts/operator_signing.py) creates a
passphrase-encrypted Ed25519 key and signs only a byte file matching an
operator-reviewed SHA-256. The [runbook](phase-2d-declaration-runbook.md)
specifies the separate account or off-machine key custody, custodian pinning,
loss/compromise disclosure and re-pinning, and the unsigned declaration
workflow. The old RSA operator-certificate fixture was removed. X.509 remains
only in TSA timestamp verification.

The RFC 3161 verifier now checks the unsigned CMS wrapper tags, versions,
identifiers, digest-algorithm set, certificate choices, issuer-and-serial
SignerInfo, and signature algorithm. Its recorded valid token passes. A
single-bit flip at every byte of that token is compared with `openssl ts
-verify`. Our verifier rejects every flip OpenSSL rejects. OpenSSL accepts
the following **44** flips that our stricter parser rejects; the test pins
the exact offsets, byte regions and standards rules. Any new or missing
divergence fails until reviewed.

The cited rules are in [RFC 5652](https://www.rfc-editor.org/rfc/rfc5652.html),
[RFC 5754](https://www.rfc-editor.org/rfc/rfc5754.html) and
[RFC 5280](https://www.rfc-editor.org/rfc/rfc5280.html).

| Byte offsets in recorded token | Region and required rule |
| --- | --- |
| 25 | SignedData version, RFC 5652 §5.1 |
| 41 | SHA-256 digestAlgorithms parameters, RFC 5652 §5.1 and RFC 5754 §2 |
| 1002, 1019, 1021, 1032, 1062, 1063, 1066, 1068, 1069, 1070, 1071, 1074, 1077, 1078, 1079, 1080, 1083, 1084, 1085, 1086, 1087, 1089, 1144, 1434, 1454 | Unused embedded X.509 certificate syntax, RFC 5652 §10.2.2 and RFC 5280 §4.1 |
| 1747, 1765, 1773, 1781 | SignerInfo version and issuer/serial binding, RFC 5652 §5.3 |
| 1803 | SignerInfo digest parameters, RFC 5652 §5.3 and RFC 5754 §2 |
| 1805, 1821 | Signed attributes syntax, RFC 5652 §§5.3, 11.1 |
| 1976, 1977, 1978, 1979, 1980, 1981, 1982, 1983, 1984, 1985 | Signature-algorithm identifier, RFC 5652 §5.3 |

The timestamp authority remains a proposal for operator approval, as in the
runbook. After approval, a recorded real public token and chain should be
added to the strict parser tests. No authority endpoint or trust anchor has
been chosen by this work.

Verification on the branch before this security-only commit: Ruff, latest
Black `--check .` (26.5.1), `mypy src`, and `bandit -q -r src` passed. The full
suite passed with 4,370 tests and 26 skips using the null keyring backend.
The RFC 3161 offline differential passed all 18 focused tests.
