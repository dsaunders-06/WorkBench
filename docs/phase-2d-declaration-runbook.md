# Phase 2D Stage A declaration authority (implementation only)

**Status: unsigned, unsubmitted, unconfigured.** No declaration, data release,
permit or rerun approval has been signed, timestamped or written to a
production ledger. Stage A supplies offline verification and synthetic tests;
it is not an operator service deployment. Stage B remains on hold.

## Operator key custody and signatures

The operator generates and holds one Ed25519 signing key in a
passphrase-encrypted file **off this machine or under a separate Windows
account that the agent cannot access**. No operator private key, passphrase,
real signature or signing session is available to the agent. The operator
performs generation and signing, outside the agent's account, after reviewing
the exact canonical bytes and their SHA-256. The repository's
[`scripts/operator_signing.py`](../scripts/operator_signing.py) is an offline
operator script; its tests create clearly labelled throwaway keys in a
temporary directory. The agent must not run the script with a real key.

From the separate account, the operator chooses key paths outside this
repository and runs:

```text
python scripts/operator_signing.py generate-key --private-key <operator-only/encrypted-key.pem> --public-key <operator-only/public-key.bin>
```

The script prompts twice for the passphrase, creates an encrypted PKCS#8
private file and a 32-byte raw public-key file, refuses to overwrite either,
and prints the SHA-256 fingerprint of the raw public key. The operator sets
filesystem access so the agent account cannot read the encrypted file or its
directory. The passphrase is never placed in a command line, repository file,
or agent-visible environment variable. If key storage is off-machine, the
operator transfers only the public key and signatures to the custodian.

For a declaration, the operator exports `DeclarationRecord.canonical_bytes()`
from the reviewed record. For a release, permit or rerun, the operator exports
`operator_action_bytes(action, payload)` from the reviewed action and payload.
The operator compares the exported bytes and SHA-256 with the intended
declaration or action, then signs the exact byte file:

```text
python scripts/operator_signing.py sign --private-key <operator-only/encrypted-key.pem> --canonical-file <reviewed-canonical-bytes.bin> --signature-file <new-signature.json> --expected-sha256 <reviewed-64-character-sha256>
```

The script refuses a changed digest or existing signature output. Its JSON
contains the Ed25519 signature, raw public key, public-key fingerprint, and
payload hash for offline operator review. Production verification obtains the
raw public key and its matching fingerprint only from custodian configuration;
the receipt supplies only the signature. Operator IDs and code-level role checks are labels and workflow
conveniences, **not security controls**. The private-key signature is the
authorising act.

The custodian pins the operator raw-public-key SHA-256 and the DER SHA-256 of
every approved TSA root, along with the root DER, current signed CRLs and
allowed TSA policies. On Windows the fixed production configuration path is
`C:\ProgramData\QAT\Custodian\promotion-trust.json`; on Linux it is
`/etc/qat/promotion-trust.json`. The custodian owns that path and its parent
directory and sets permissions so the agent account cannot write either.
Production verification reads only this fixed path; caller-supplied keys and
trust stores are rejected. The schema is `qat-promotion-trust-v1` with
`operator_ed25519_public_key_raw_base64`,
`operator_ed25519_public_key_sha256`, `tsa_roots` entries containing
`der_base64` and `sha256`, `tsa_crls_der_base64`, and
`allowed_tsa_policies`. Test injection requires explicit `test_mode=True` and
runtime throwaway material.

After key loss or compromise, the custodian stops releases, records a
disclosure with the affected fingerprint, time, reason and potentially
affected receipt heads, and marks the old fingerprint inactive. The operator
creates a new key in the separate account. The custodian independently
reviews and re-pins its fingerprint before any new approval. Existing
receipts retain their original signer fingerprint and disclosure lineage;
they are not silently re-signed or treated as newly authorised.

## Declaration and release lineage

`EFFECT_DECLARED` requires a positive exact-decimal `delta_MME` string and an
economic rationale. `PROMOTION_PROTOCOL_DECLARED` binds the data, Phase 4
risk, tail, statistical, feasibility and promotion rules.
`METHOD_AUDIT_DECLARED` binds candidates, scenario matrix, generators, seeds,
caps, code hash and pilot report hash. The operator must review the
[unsigned draft](METHOD_AUDIT_DECLARED_UNSIGNED_DRAFT.json), full pilot,
source decision and [freeze proposals](phase-2d-operator-freeze-proposals.md)
before signing any declaration.

An independently signed RFC 3161 token for the SHA-256 of each operator
signature accompanies every declaration. `append_declaration` accepts an
already signed and timestamped receipt; it cannot sign or request a token.
Offline verification checks the pinned Ed25519 signature, token imprint,
sequence, nonce, identities, prior head and strictly increasing declaration
and timestamp times. The initial head is 64 zeroes; each later declaration
binds the exact prior receipt head. Three verified records are required for a
development or validation release. A separately signed operator approval
binds each release's exact payload before a receipt is appended or a shard
handle is returned. The same applies to the reference-view release and a
development rerun.

The RFC 3161 verifier accepts DER CMS SignedData with a SHA-256 imprint and
ESS signer-certificate binding. It requires pinned TSA roots, current signed
CRLs, exclusive `timeStamping` EKU, an allowed policy OID and a valid signing
time. X.509 chains and revocation lists are used **only** for TSA timestamp
verification, not for operator signatures. Unsupported CMS structures fail
closed. The [recorded throwaway token fixture](../tests/promotion/fixtures/rfc3161-throwaway-test-only)
is public test data; its private keys are not in Git. Tests make no live TSA
calls. Once the operator approves a TSA, record one real public token and
chain as an additional fixture to prove strict parsing accepts its encodings.

**Timestamp authority proposed for operator approval only:** DigiCert's
[RFC 3161 service](https://knowledge.digicert.com/general-information/rfc3161-compliant-time-stamp-authority-server),
subject to review of its public-trust CP/CPS, policy OID, chain, trust anchor,
revocation capture, terms and operational suitability. No endpoint, root or
policy is approved or configured by this proposal. No timestamp request has
been sent.

The production service and deployment need operator review of account
separation, trust-file ACLs, atomic ledger persistence and recovery, TSA/CRL
provenance and real role assignment. One person may fill multiple human roles,
but the accounts and keys remain distinct; the runbook must not claim
independent human review in that case.
