"""Pinned public-key verification for operator-authorised promotion actions.

The private key is never loaded here. Production trust comes from a fixed
custodian-owned configuration path; test injection is explicit and separate.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from qat.promotion.rfc3161 import TrustStore


class OperatorSignatureError(ValueError):
    """An action lacks a signature by the pinned operator public key."""


class TrustConfigurationError(ValueError):
    """Custodian-controlled promotion trust configuration is unavailable."""


PRODUCTION_TRUST_PATH = (
    Path("C:/ProgramData/QAT/Custodian/promotion-trust.json")
    if os.name == "nt"
    else Path("/etc/qat/promotion-trust.json")
)

_ACTIONS = frozenset(
    {
        "REFERENCE_VIEW_RELEASED",
        "DEV_DATA_RELEASED",
        "VALIDATION_DATA_RELEASED",
        "DEV_RERUN_AUTHORIZED",
        "HOLDOUT_PERMIT",
        "HOLDOUT_RERUN_AUTHORIZED",
    }
)

_CUSTODIAN_ACCOUNT = r".\QATCustodian"
_BOUNDARY_WRITE_RIGHTS = (
    0x00000002  # FILE_WRITE_DATA / FILE_ADD_FILE
    | 0x00000004  # FILE_APPEND_DATA / FILE_ADD_SUBDIRECTORY
    | 0x00000010  # FILE_WRITE_EA
    | 0x00000040  # FILE_DELETE_CHILD
    | 0x00000100  # FILE_WRITE_ATTRIBUTES
    | 0x00010000  # DELETE
    | 0x00040000  # WRITE_DAC
    | 0x00080000  # WRITE_OWNER
    | 0x10000000  # GENERIC_ALL
    | 0x40000000  # GENERIC_WRITE
)
_ANCESTOR_REPLACEMENT_RIGHTS = (
    0x00000040  # FILE_DELETE_CHILD
    | 0x00010000  # DELETE
    | 0x00040000  # WRITE_DAC
    | 0x00080000  # WRITE_OWNER
    | 0x10000000  # GENERIC_ALL
)


@dataclass(frozen=True, slots=True)
class _WindowsAcl:
    owner: str
    grants: tuple[tuple[str, int, bool], ...]  # SID, mask, inherit-only


def _is_reparse_point(path: Path) -> bool:
    info = path.lstat()
    if os.name == "nt":
        return bool(info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    return stat.S_ISLNK(info.st_mode)


def _windows_sid(account: str) -> str:
    import ctypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    lookup = advapi.LookupAccountNameW
    lookup.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    lookup.restype = ctypes.c_int
    sid_size = ctypes.c_uint32()
    domain_size = ctypes.c_uint32()
    kind = ctypes.c_uint32()
    lookup(
        None,
        account,
        None,
        ctypes.byref(sid_size),
        None,
        ctypes.byref(domain_size),
        ctypes.byref(kind),
    )
    if not sid_size.value:
        raise TrustConfigurationError("custodian account cannot be resolved")
    sid = ctypes.create_string_buffer(sid_size.value)
    domain = ctypes.create_unicode_buffer(max(1, domain_size.value))
    if not lookup(
        None,
        account,
        sid,
        ctypes.byref(sid_size),
        domain,
        ctypes.byref(domain_size),
        ctypes.byref(kind),
    ):
        raise TrustConfigurationError("custodian account cannot be resolved")
    return _sid_text(ctypes.addressof(sid), advapi, kernel)


def _sid_text(pointer: int, advapi: Any, kernel: Any) -> str:
    import ctypes

    convert = advapi.ConvertSidToStringSidW
    convert.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    convert.restype = ctypes.c_int
    free = kernel.LocalFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = ctypes.c_void_p
    text_pointer = ctypes.c_void_p()
    if not convert(pointer, ctypes.byref(text_pointer)):
        raise TrustConfigurationError("Windows SID cannot be decoded")
    try:
        value = text_pointer.value
        if value is None:
            raise TrustConfigurationError("Windows SID cannot be decoded")
        return ctypes.wstring_at(value)
    finally:
        free(text_pointer)


def _trusted_windows_sids() -> dict[str, str]:
    return {
        "custodian": _windows_sid(_CUSTODIAN_ACCOUNT),
        "administrators": "S-1-5-32-544",
        "system": "S-1-5-18",
        "trusted_installer": _windows_sid(r"NT SERVICE\TrustedInstaller"),
    }


def _windows_acl_snapshot(path: Path) -> _WindowsAcl:
    """Read the owner's SID and every explicit or inherited DACL entry."""
    import ctypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    get_info = advapi.GetNamedSecurityInfoW
    get_info.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    get_info.restype = ctypes.c_uint32
    get_ace = advapi.GetAce
    get_ace.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    get_ace.restype = ctypes.c_int
    free = kernel.LocalFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = ctypes.c_void_p
    owner = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    result = get_info(
        str(path),
        1,
        0x00000005,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if result:
        raise TrustConfigurationError(f"Windows trust ACL could not be read ({result})")
    try:
        if not owner.value or not dacl.value:
            raise TrustConfigurationError("trust path lacks an owner or a DACL")
        header = ctypes.string_at(dacl.value, 8)
        count = int.from_bytes(header[4:6], "little")
        grants: list[tuple[str, int, bool]] = []
        for index in range(count):
            ace = ctypes.c_void_p()
            if not get_ace(dacl, index, ctypes.byref(ace)) or not ace.value:
                raise TrustConfigurationError("trust ACL entry could not be read")
            ace_header = ctypes.string_at(ace.value, 4)
            ace_type, flags = ace_header[:2]
            size = int.from_bytes(ace_header[2:4], "little")
            if size < 12 or ace_type not in (0, 1):
                raise TrustConfigurationError("unsupported trust ACL entry")
            if ace_type == 0:
                mask = int.from_bytes(ctypes.string_at(ace.value + 4, 4), "little")
                grants.append((_sid_text(ace.value + 8, advapi, kernel), mask, bool(flags & 0x08)))
        return _WindowsAcl(_sid_text(owner.value, advapi, kernel), tuple(grants))
    finally:
        free(descriptor)


def _validate_trust_path_security(path: Path) -> None:
    """Fail closed before loading any trust bytes from the fixed path."""
    components = (*reversed(path.parents), path)
    for component in components:
        if _is_reparse_point(component):
            raise TrustConfigurationError("trust path contains a reparse point")
    if os.name != "nt":
        for component in components:
            info = component.stat()
            if info.st_uid != 0 or info.st_mode & 0o022:
                raise TrustConfigurationError("trust path is not root-owned and locked")
        return
    if path.parent.name.casefold() != "custodian" or path.parent.parent.name.casefold() != "qat":
        raise TrustConfigurationError("unexpected Windows custody boundary")
    sids = _trusted_windows_sids()
    boundary_owners = {sids["custodian"], sids["administrators"], sids["system"]}
    ancestor_owners = {sids["administrators"], sids["system"], sids["trusted_installer"]}
    boundary = {path, path.parent, path.parent.parent}
    for component in components:
        acl = _windows_acl_snapshot(component)
        in_boundary = component in boundary
        if acl.owner not in (boundary_owners if in_boundary else ancestor_owners):
            raise TrustConfigurationError("trust path has an untrusted owner")
        prohibited = _BOUNDARY_WRITE_RIGHTS if in_boundary else _ANCESTOR_REPLACEMENT_RIGHTS
        for principal, mask, inherit_only in acl.grants:
            if principal in boundary_owners:
                continue
            if not in_boundary and inherit_only:
                continue
            if mask & prohibited:
                raise TrustConfigurationError("trust path grants replacement or write rights")


@dataclass(frozen=True, slots=True)
class CustodianTrust:
    operator_public_key_raw: bytes
    operator_public_key_sha256: str
    tsa_root_sha256: tuple[str, ...]
    tsa_trust: TrustStore
    allowed_tsa_policies: frozenset[str]

    def __post_init__(self) -> None:
        fingerprints = self.tsa_root_sha256
        if (
            len(self.operator_public_key_raw) != 32
            or hashlib.sha256(self.operator_public_key_raw).hexdigest()
            != self.operator_public_key_sha256
            or re.fullmatch(r"[0-9a-f]{64}", self.operator_public_key_sha256) is None
            or not fingerprints
            or len(set(fingerprints)) != len(fingerprints)
            or len(fingerprints) != len(self.tsa_trust.roots)
            or any(re.fullmatch(r"[0-9a-f]{64}", x) is None for x in fingerprints)
            or tuple(hashlib.sha256(root).hexdigest() for root in self.tsa_trust.roots)
            != fingerprints
            or not self.tsa_trust.crls
            or not self.allowed_tsa_policies
        ):
            raise TrustConfigurationError("invalid pinned operator or TSA trust")


@dataclass(frozen=True, slots=True)
class OperatorApproval:
    signature: bytes


def _decode_base64(value: object) -> bytes:
    if not isinstance(value, str):
        raise TrustConfigurationError("trust entry must be base64 text")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise TrustConfigurationError("invalid trust base64") from exc


def resolve_custodian_trust(
    *, test_mode: bool = False, test_trust: CustodianTrust | None = None
) -> CustodianTrust:
    """Load fixed production pins, or explicit throwaway pins in test mode."""
    if test_mode:
        if test_trust is None:
            raise TrustConfigurationError("test mode needs explicit throwaway trust")
        return test_trust
    if test_trust is not None:
        raise TrustConfigurationError("production mode refuses caller-supplied trust")
    try:
        _validate_trust_path_security(PRODUCTION_TRUST_PATH)
        raw = json.loads(PRODUCTION_TRUST_PATH.read_bytes())
        if raw["schema"] != "qat-promotion-trust-v1":
            raise TrustConfigurationError("unsupported custodian trust schema")
        roots = tuple(_decode_base64(item["der_base64"]) for item in raw["tsa_roots"])
        fingerprints = tuple(item["sha256"] for item in raw["tsa_roots"])
        crls = tuple(_decode_base64(value) for value in raw["tsa_crls_der_base64"])
        return CustodianTrust(
            operator_public_key_raw=_decode_base64(raw["operator_ed25519_public_key_raw_base64"]),
            operator_public_key_sha256=raw["operator_ed25519_public_key_sha256"],
            tsa_root_sha256=fingerprints,
            tsa_trust=TrustStore(roots, crls),
            allowed_tsa_policies=frozenset(raw["allowed_tsa_policies"]),
        )
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise TrustConfigurationError("custodian trust could not be loaded") from exc


def verify_operator_signature(content: bytes, signature: bytes, *, trust: CustodianTrust) -> None:
    """Require Ed25519 over exact bytes by the externally pinned key."""
    if len(signature) != 64:
        raise OperatorSignatureError("invalid Ed25519 signature length")
    fingerprint = hashlib.sha256(trust.operator_public_key_raw).hexdigest()
    if not hmac.compare_digest(fingerprint, trust.operator_public_key_sha256):
        raise OperatorSignatureError("operator public key differs from custodian pin")
    try:
        Ed25519PublicKey.from_public_bytes(trust.operator_public_key_raw).verify(signature, content)
    except (InvalidSignature, ValueError) as exc:
        raise OperatorSignatureError("operator signature is invalid") from exc


def operator_action_bytes(action: str, payload: dict[str, object]) -> bytes:
    """Domain-separated canonical bytes for releases, permits and reruns."""
    if action not in _ACTIONS:
        raise OperatorSignatureError("unknown operator action")
    try:
        canonical = json.dumps(
            {"action": action, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise OperatorSignatureError("operator action payload is not canonical JSON") from exc
    return b"QAT-OPERATOR-ACTION-v1\n" + canonical


def verify_operator_approval(
    approval: OperatorApproval, action: str, payload: dict[str, object], *, trust: CustodianTrust
) -> None:
    verify_operator_signature(
        operator_action_bytes(action, payload),
        approval.signature,
        trust=trust,
    )
