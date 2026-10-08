# Phase 2D Stage A declaration authority (implementation only)

**Dormant after the 8 October 2026 closure.** Do not execute the signing,
timestamp, declaration or release steps below. No inference method qualified;
see [the closure note](phase-2-closure.md). This runbook remains historical
Stage A engineering documentation.

**Status: unsigned, unsubmitted, unconfigured.** No declaration, data release,
permit or rerun approval has been signed, timestamped or written to a
production ledger. Stage A supplies offline verification and synthetic tests;
it is not an operator service deployment. Stage B remains on hold.

## Operator key custody and signatures

The operator generates and holds one Ed25519 signing key in a
passphrase-encrypted file **off this machine or under a separate Windows
account that the agent cannot access**. No operator private key, passphrase,
real signature or signing session is available to the agent. The operator
performs generation and signing outside the agent's account. The primary path
uses OpenSSL directly; the agent must never run these commands with a real key.

From that separate account, with private-key paths outside the repository,
the operator uses OpenSSL 3.x to create an encrypted Ed25519 key and public
key. Set `$operatorDir` to a directory inaccessible to the agent account;
keep the same path values for later signing:

```powershell
openssl version
$operatorDir = Read-Host 'Operator-only directory outside this machine or agent account'
$private = Join-Path $operatorDir 'private.pem'
$public = Join-Path $operatorDir 'public.pem'
$publicSpki = Join-Path $operatorDir 'public.spki.der'
$publicRaw = Join-Path $operatorDir 'public.raw'
openssl genpkey -algorithm Ed25519 -aes-256-cbc -out $private
openssl pkey -in $private -pubout -out $public
openssl pkey -in $private -pubout -outform DER -out $publicSpki
$spki = [IO.File]::ReadAllBytes($publicSpki)
if ($spki.Length -ne 44 -or [Convert]::ToHexString($spki[0..11]) -ne '302A300506032B6570032100') { throw 'Unexpected Ed25519 public-key encoding' }
[IO.File]::WriteAllBytes($publicRaw, [byte[]]$spki[12..43])
Get-FileHash $publicRaw -Algorithm SHA256
```

OpenSSL prompts for the passphrase. It must not appear in command arguments,
repository files or agent-visible environment variables. The 32-byte raw
public key and its SHA-256 fingerprint go to the custodian; the encrypted
private key and its directory remain inaccessible to the agent account.

For a declaration, the operator independently reviews the readable payload
JSON, computes its SHA-256 and checks it against the `payload_sha256` in the
readable canonical declaration envelope. The operator then reviews every
envelope field, including name, sequence, prior head, identity, nonce and
declared time. The envelope is exported as the exact bytes from
`DeclarationRecord.canonical_bytes()`. For a release, permit or rerun, the
operator reviews the readable action and payload from
`operator_action_bytes(action, payload)`. The operator displays the exact
canonical byte file and checks its SHA-256 against the reviewed value **before**
signing; a hash alone is not a content review:

```powershell
$canonical = Read-Host 'Reviewed canonical byte-file path'
$signature = Read-Host 'New raw signature output path'
[Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($canonical))
Get-FileHash $canonical -Algorithm SHA256
openssl pkeyutl -sign -rawin -inkey $private -in $canonical -out $signature
openssl pkeyutl -verify -rawin -pubin -inkey $public -in $canonical -sigfile $signature
```

The output is a 64-byte raw Ed25519 signature. The operator transfers only
that signature to the receipt. Production verification obtains the raw public
key and its matching fingerprint from custodian configuration. Operator IDs
and code-level role checks are labels and workflow conveniences, **not
security controls**. The private-key signature is the authorising act.

[`scripts/operator_signing.py`](../scripts/operator_signing.py) is an optional
convenience after independent review of its source. Its pinned SHA-256 is
`5d3297938e5f4f35d9bab8ccc92266c10c063af6e17335b04bc5e8509d83d3a3`;
the operator checks `Get-FileHash scripts/operator_signing.py -Algorithm
SHA256` in the separate account and refuses a different hash until the script
is reviewed and re-pinned. Its `generate-key` and `sign` commands prompt for
the passphrase, refuse overwrites and require the reviewed canonical-file
hash. Its tests use runtime throwaway keys only.

**Before any QAT component runs**, an administrator pre-creates
`C:\ProgramData\QAT\Custodian` and its parent `C:\ProgramData\QAT` under
the separate local `QATCustodian` account or Administrators/SYSTEM ownership.
The ACL on both directories and the trust file must grant write, append,
delete, delete-child, change-permissions and take-ownership rights only to
`QATCustodian`, Administrators and SYSTEM. Remove untrusted explicit and
inherited grants, including Users, Authenticated Users, Everyone,
INTERACTIVE and CREATOR OWNER, and inspect `Get-Acl` or `icacls` output on
each path before placing the file. No symlink, junction or mount point may
occur anywhere along the path. `C:\` and `C:\ProgramData` must have trusted
ownership and must not grant an untrusted principal replacement rights over
the QAT directory. The agent's account must not belong to Administrators and
must run non-elevated; administrators are outside this protection boundary.
The gate checks ownership and every explicit/inherited ACL entry before
loading trust bytes, and refuses an unsafe path.

During custodian setup on the operator's Windows machine, after placing the
public trust file, run this read-only trust-path check once from the separate
custodian account:

```powershell
python scripts/check_custodian_trust_path.py
```

It prints the owner and every allow entry (SID, rights mask and inheritance
flag) for each path component, validates the production path, then creates a
temporary file containing only test text beside the trust file, grants Users
write access to that file, and confirms the verifier refuses it specifically
for the write grant. The test file is removed even if the check fails. Save
the output in the custodian setup record; any failure stops release setup.

The custodian pins the operator raw-public-key SHA-256 and the DER SHA-256 of
every approved TSA root, along with the root DER, current signed CRLs and
allowed TSA policies. On Windows the fixed production configuration path is
`C:\ProgramData\QAT\Custodian\promotion-trust.json`; on Linux it is
`/etc/qat/promotion-trust.json`. On Linux, the file and every parent to `/`
must be root-owned with no group or other write bit. On Windows, the custody
and ancestor rules above apply.
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
separation, atomic ledger persistence and recovery, TSA/CRL provenance and
real role assignment. One person may fill multiple human roles,
but the accounts and keys remain distinct; the runbook must not claim
independent human review in that case.
