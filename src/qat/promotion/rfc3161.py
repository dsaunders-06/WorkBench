"""Offline, fail-closed verification of RFC 3161/CMS timestamp receipts.

Only DER, SHA-256 imprints, issuer-and-serial SignerInfo, and RSA/ECDSA
signatures are accepted. Unsupported CMS features are rejected, not ignored.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography import x509
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, ExtensionOID


class TimestampVerificationError(ValueError):
    """A timestamp or its offline trust evidence could not be verified."""


@dataclass(frozen=True, slots=True)
class TrustStore:
    """Pinned DER trust roots and current DER CRLs, supplied outside the agent."""

    roots: tuple[bytes, ...]
    crls: tuple[bytes, ...]


@dataclass(frozen=True, slots=True)
class VerifiedTimestamp:
    generated_at: datetime
    serial: int
    policy_oid: str
    signer_sha256: str


@dataclass(frozen=True, slots=True)
class _Node:
    tag: int
    value: bytes
    encoded: bytes

    def children(self) -> tuple[_Node, ...]:
        return _parse_all(self.value)


def _parse_all(data: bytes) -> tuple[_Node, ...]:
    result: list[_Node] = []
    pos = 0
    while pos < len(data):
        start = pos
        if pos + 2 > len(data):
            raise TimestampVerificationError("truncated DER")
        tag = data[pos]
        pos += 1
        if tag & 0x1F == 0x1F:
            raise TimestampVerificationError("high-tag-number DER is unsupported")
        length = data[pos]
        pos += 1
        if length & 0x80:
            count = length & 0x7F
            if count == 0 or count > 4 or pos + count > len(data):
                raise TimestampVerificationError("invalid DER length")
            raw = data[pos : pos + count]
            if raw[0] == 0:
                raise TimestampVerificationError("nonminimal DER length")
            length = int.from_bytes(raw, "big")
            if length < 128:
                raise TimestampVerificationError("nonminimal DER length")
            pos += count
        if pos + length > len(data):
            raise TimestampVerificationError("truncated DER value")
        pos += length
        result.append(_Node(tag, data[pos - length : pos], data[start:pos]))
    return tuple(result)


def _one(data: bytes, tag: int) -> _Node:
    nodes = _parse_all(data)
    if len(nodes) != 1 or nodes[0].tag != tag:
        raise TimestampVerificationError("unexpected DER structure")
    return nodes[0]


def _oid(node: _Node) -> str:
    if node.tag != 0x06 or not node.value:
        raise TimestampVerificationError("expected object identifier")
    first = node.value[0]
    arcs = [min(first // 40, 2), first - 40 * min(first // 40, 2)]
    value = 0
    for byte in node.value[1:]:
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            arcs.append(value)
            value = 0
    if value or node.value[-1] & 0x80:
        raise TimestampVerificationError("invalid object identifier")
    return ".".join(map(str, arcs))


def _integer(node: _Node) -> int:
    if node.tag != 0x02 or not node.value or node.value[0] & 0x80:
        raise TimestampVerificationError("expected positive integer")
    return int.from_bytes(node.value, "big")


def _algorithm_oid(node: _Node) -> str:
    if node.tag != 0x30:
        raise TimestampVerificationError("algorithm identifier must be a sequence")
    fields = node.children()
    if len(fields) not in (1, 2) or (len(fields) == 2 and fields[1].encoded != b"\x05\x00"):
        raise TimestampVerificationError("invalid algorithm identifier parameters")
    return _oid(fields[0])


def _validate_x509_subject(node: _Node) -> None:
    """Require a valid X.509 Name in each embedded certificate choice."""
    certificate = node.children()
    tbs = certificate[0].children()
    subject = tbs[5 if tbs[0].tag == 0xA0 else 4]
    if subject.tag != 0x30:
        raise TimestampVerificationError("invalid embedded certificate subject")
    for rdn in subject.children():
        if rdn.tag != 0x31:
            raise TimestampVerificationError("invalid embedded certificate subject")
        for attribute in rdn.children():
            if attribute.tag != 0x30:
                raise TimestampVerificationError("invalid embedded certificate subject")
            fields = attribute.children()
            if len(fields) != 2:
                raise TimestampVerificationError("invalid embedded certificate subject")
            _oid(fields[0])
            value = fields[1]
            if value.tag == 0x0C:
                value.value.decode("utf-8")
            elif value.tag not in (0x13, 0x14, 0x1C, 0x1E):
                raise TimestampVerificationError("invalid embedded certificate subject string")


def _verify_signature(public_key: object, signature: bytes, data: bytes) -> None:
    if isinstance(public_key, rsa.RSAPublicKey):
        public_key.verify(signature, data, padding.PKCS1v15(), hashes.SHA256())
    elif isinstance(public_key, ec.EllipticCurvePublicKey):
        public_key.verify(signature, data, ec.ECDSA(hashes.SHA256()))
    else:
        raise TimestampVerificationError("unsupported signing key")


def _verify_x509_signature(
    public_key: object, signature: bytes, data: bytes, algorithm: object
) -> None:
    if not isinstance(algorithm, hashes.SHA256):
        raise TimestampVerificationError("certificate/CRL must use SHA-256")
    _verify_signature(public_key, signature, data)


def verify_certificate_chain(
    leaf_der: bytes,
    intermediates_der: tuple[bytes, ...],
    trust: TrustStore,
    *,
    at: datetime,
    now: datetime,
    tsa: bool,
) -> x509.Certificate:
    """Validate a pinned path and current, signed CRL for every non-root cert."""
    if not trust.roots or not trust.crls or at.tzinfo is None or now.tzinfo is None:
        raise TimestampVerificationError("pinned roots, CRLs, and aware times required")
    try:
        leaf = x509.load_der_x509_certificate(leaf_der)
        intermediates = [x509.load_der_x509_certificate(x) for x in intermediates_der]
        roots = [x509.load_der_x509_certificate(x) for x in trust.roots]
        crls = [x509.load_der_x509_crl(x) for x in trust.crls]
        path = [leaf, *intermediates]
        if len(path) != len({x.fingerprint(hashes.SHA256()) for x in path}):
            raise TimestampVerificationError("repeated certificate in path")
        for index, cert in enumerate(path):
            issuer = (
                path[index + 1]
                if index + 1 < len(path)
                else next((root for root in roots if root.subject == cert.issuer), None)
            )
            if issuer is None or cert.issuer != issuer.subject:
                raise TimestampVerificationError("certificate chain lacks pinned issuer")
            for instant in (at, now):
                if not issuer.not_valid_before_utc <= instant <= issuer.not_valid_after_utc:
                    raise TimestampVerificationError("issuer certificate expired or not yet valid")
            for instant in (at, now):
                if not cert.not_valid_before_utc <= instant <= cert.not_valid_after_utc:
                    raise TimestampVerificationError("certificate expired or not yet valid")
            _verify_x509_signature(
                issuer.public_key(),
                cert.signature,
                cert.tbs_certificate_bytes,
                cert.signature_hash_algorithm,
            )
            constraints = issuer.extensions.get_extension_for_oid(
                ExtensionOID.BASIC_CONSTRAINTS
            ).value
            if not isinstance(constraints, x509.BasicConstraints) or not constraints.ca:
                raise TimestampVerificationError("issuer is not a CA")
            issuer_usage = issuer.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE).value
            if (
                not isinstance(issuer_usage, x509.KeyUsage)
                or not issuer_usage.key_cert_sign
                or not issuer_usage.crl_sign
            ):
                raise TimestampVerificationError("issuer cannot sign certificates and CRLs")
            matches = [crl for crl in crls if crl.issuer == issuer.subject]
            if len(matches) != 1:
                raise TimestampVerificationError("exactly one issuer CRL is required")
            crl = matches[0]
            _verify_x509_signature(
                issuer.public_key(),
                crl.signature,
                crl.tbs_certlist_bytes,
                crl.signature_hash_algorithm,
            )
            if crl.next_update_utc is None or not crl.last_update_utc <= now <= crl.next_update_utc:
                raise TimestampVerificationError("CRL is stale or not yet valid")
            if crl.get_revoked_certificate_by_serial_number(cert.serial_number) is not None:
                raise TimestampVerificationError("signer certificate is revoked")
        usage = leaf.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE).value
        if not isinstance(usage, x509.KeyUsage) or not usage.digital_signature:
            raise TimestampVerificationError("signer lacks digitalSignature usage")
        if tsa:
            eku = leaf.extensions.get_extension_for_oid(ExtensionOID.EXTENDED_KEY_USAGE).value
            if not isinstance(eku, x509.ExtendedKeyUsage) or list(eku) != [
                ExtendedKeyUsageOID.TIME_STAMPING
            ]:
                raise TimestampVerificationError("TSA requires exclusive timeStamping usage")
        return leaf
    except (
        InvalidSignature,
        UnsupportedAlgorithm,
        ValueError,
        x509.InvalidVersion,
        x509.ExtensionNotFound,
        TypeError,
    ) as exc:
        raise TimestampVerificationError("invalid certificate or revocation evidence") from exc


def _attribute(attrs: tuple[_Node, ...], oid: str) -> _Node:
    matching = [a.children() for a in attrs if a.tag == 0x30 and _oid(a.children()[0]) == oid]
    if len(matching) != 1 or len(matching[0]) != 2:
        raise TimestampVerificationError("missing or duplicate signed attribute")
    values = matching[0][1]
    if values.tag != 0x31 or len(values.children()) != 1:
        raise TimestampVerificationError("invalid signed attribute value")
    return values.children()[0]


def verify_timestamp_token(
    token_der: bytes,
    signed_digest: bytes,
    *,
    trust: TrustStore,
    now: datetime,
    allowed_policies: frozenset[str],
) -> VerifiedTimestamp:
    """Verify an offline RFC 3161 token against its imprint and pinned TSA PKI."""
    try:
        if len(signed_digest) != 32 or not allowed_policies:
            raise TimestampVerificationError("SHA-256 digest and allowed policy required")
        content = _one(token_der, 0x30).children()
        if (
            len(content) != 2
            or _oid(content[0]) != "1.2.840.113549.1.7.2"
            or content[1].tag != 0xA0
        ):
            raise TimestampVerificationError("token is not CMS SignedData")
        signed = _one(content[1].value, 0x30).children()
        if len(signed) < 5 or _integer(signed[0]) != 3 or signed[1].tag != 0x31:
            raise TimestampVerificationError("invalid CMS SignedData")
        digest_algorithms = {_algorithm_oid(algorithm) for algorithm in signed[1].children()}
        if not digest_algorithms or digest_algorithms != {"2.16.840.1.101.3.4.2.1"}:
            raise TimestampVerificationError("unsupported CMS digest algorithm list")
        if signed[2].tag != 0x30:
            raise TimestampVerificationError("invalid encapsulated content wrapper")
        encap = signed[2].children()
        if len(encap) != 2 or _oid(encap[0]) != "1.2.840.113549.1.9.16.1.4" or encap[1].tag != 0xA0:
            raise TimestampVerificationError("missing TSTInfo content type")
        tst_bytes = _one(encap[1].value, 0x04).value
        tst = _one(tst_bytes, 0x30).children()
        if len(tst) < 5 or _integer(tst[0]) != 1:
            raise TimestampVerificationError("invalid TSTInfo")
        policy = _oid(tst[1])
        if policy not in allowed_policies:
            raise TimestampVerificationError("unapproved TSA policy")
        imprint = tst[2].children()
        if len(imprint) != 2 or _oid(imprint[0].children()[0]) != "2.16.840.1.101.3.4.2.1":
            raise TimestampVerificationError("TSA imprint must use SHA-256")
        if imprint[1].tag != 0x04 or imprint[1].value != signed_digest:
            raise TimestampVerificationError("timestamp imprint mismatch")
        serial = _integer(tst[3])
        if tst[4].tag != 0x18:
            raise TimestampVerificationError("missing UTC GeneralizedTime")
        generated_at = datetime.strptime(tst[4].value.decode("ascii"), "%Y%m%d%H%M%SZ").replace(
            tzinfo=UTC
        )
        if generated_at > now:
            raise TimestampVerificationError("timestamp is in the future")
        cert_field = signed[3]
        if cert_field.tag != 0xA0:
            raise TimestampVerificationError("CMS certificates required")
        cert_nodes = cert_field.children()
        if not cert_nodes or any(node.tag != 0x30 for node in cert_nodes):
            raise TimestampVerificationError("unsupported CMS CertificateChoices")
        for node in cert_nodes:
            _validate_x509_subject(node)
        certs = tuple(node.encoded for node in cert_nodes)
        parsed_certs = tuple(x509.load_der_x509_certificate(cert) for cert in certs)
        signer_set = signed[4]
        if signer_set.tag != 0x31 or len(signer_set.children()) != 1:
            raise TimestampVerificationError("exactly one TSA signer required")
        signer_node = signer_set.children()[0]
        if signer_node.tag != 0x30:
            raise TimestampVerificationError("SignerInfo must be a sequence")
        signer = signer_node.children()
        if len(signer) != 6 or _integer(signer[0]) != 1:
            raise TimestampVerificationError("unsupported SignerInfo")
        if signer[1].tag != 0x30:
            raise TimestampVerificationError("issuer-and-serial signer required")
        sid = signer[1].children()
        if len(sid) != 2:
            raise TimestampVerificationError("issuer-and-serial signer required")
        signer_certs = [
            (encoded, cert)
            for encoded, cert in zip(certs, parsed_certs, strict=True)
            if cert.issuer.public_bytes() == sid[0].encoded
            and cert.serial_number == _integer(sid[1])
        ]
        if len(signer_certs) != 1:
            raise TimestampVerificationError("TSA signer certificate missing or ambiguous")
        leaf_der, leaf = signer_certs[0]
        roots = tuple(x509.load_der_x509_certificate(root) for root in trust.roots)
        intermediates: list[bytes] = []
        current = leaf
        while not any(root.subject == current.issuer for root in roots):
            issuers = [
                (encoded, cert)
                for encoded, cert in zip(certs, parsed_certs, strict=True)
                if encoded != leaf_der and cert.subject == current.issuer
            ]
            if len(issuers) != 1 or issuers[0][0] in intermediates:
                raise TimestampVerificationError("certificate chain lacks pinned issuer")
            encoded, current = issuers[0]
            intermediates.append(encoded)
        leaf = verify_certificate_chain(
            leaf_der,
            tuple(intermediates),
            trust,
            at=generated_at,
            now=now,
            tsa=True,
        )
        signer_digest = _algorithm_oid(signer[2])
        if signer_digest != "2.16.840.1.101.3.4.2.1" or signer_digest not in digest_algorithms:
            raise TimestampVerificationError("CMS digest must use SHA-256")
        attrs = signer[3]
        if attrs.tag != 0xA0:
            raise TimestampVerificationError("signed attributes required")
        children = attrs.children()
        if _oid(_attribute(children, "1.2.840.113549.1.9.3")) != "1.2.840.113549.1.9.16.1.4":
            raise TimestampVerificationError("CMS contentType mismatch")
        digest_attr = _attribute(children, "1.2.840.113549.1.9.4")
        if digest_attr.tag != 0x04 or digest_attr.value != hashlib.sha256(tst_bytes).digest():
            raise TimestampVerificationError("CMS messageDigest mismatch")
        ess = _attribute(children, "1.2.840.113549.1.9.16.2.47")
        ess_cert = ess.children()[0].children()[0].children()[0]
        if ess_cert.tag != 0x04 or ess_cert.value != hashlib.sha256(leaf_der).digest():
            raise TimestampVerificationError("ESS signer certificate hash mismatch")
        signature_algorithm = _algorithm_oid(signer[4])
        signer_key = leaf.public_key()
        if not (
            isinstance(signer_key, rsa.RSAPublicKey)
            and signature_algorithm in ("1.2.840.113549.1.1.1", "1.2.840.113549.1.1.11")
            or isinstance(signer_key, ec.EllipticCurvePublicKey)
            and signature_algorithm == "1.2.840.10045.4.3.2"
        ):
            raise TimestampVerificationError("unsupported CMS signature algorithm")
        if signer[5].tag != 0x04:
            raise TimestampVerificationError("CMS signature missing")
        signed_attrs_der = bytes([0x31]) + attrs.encoded[1:]
        _verify_signature(signer_key, signer[5].value, signed_attrs_der)
        return VerifiedTimestamp(generated_at, serial, policy, hashlib.sha256(leaf_der).hexdigest())
    except (
        IndexError,
        InvalidSignature,
        UnsupportedAlgorithm,
        UnicodeDecodeError,
        ValueError,
        TypeError,
        x509.InvalidVersion,
        x509.ExtensionNotFound,
    ) as exc:
        if isinstance(exc, TimestampVerificationError):
            raise
        raise TimestampVerificationError("malformed or unverifiable RFC 3161 token") from exc
