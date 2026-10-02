"""Canonical serialization and deterministic evidence identifiers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from datetime import date
from decimal import Decimal
from enum import Enum


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("canonical decimal values must be finite")
    if value.is_zero():
        return "0"
    return format(value.normalize(), "f")


def _semantic_value(value: object) -> object:
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
    if isinstance(value, float):
        raise TypeError("binary float values are forbidden in canonical evidence")
    if isinstance(value, Enum):
        return _semantic_value(value.value)
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _semantic_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical evidence mappings require string keys")
        return {key: _semantic_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_semantic_value(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported canonical evidence value: {type(value).__name__}")


def canonical_payload(value: object) -> bytes:
    """Return canonical UTF-8 JSON for semantic strategy evidence."""

    semantic = _semantic_value(value)
    return json.dumps(
        semantic,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def stable_decision_id(value: object) -> str:
    """Derive the stable Phase 2 decision identity from semantic content."""

    return f"swing:{hashlib.sha256(canonical_payload(value)).hexdigest()}"
