"""Append-only, hash-chained shadow events without trading dependencies."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from qat.domain.strategies.authoritative_swing.evidence import canonical_payload
from qat.operational.history import OPERATIONAL, digest


class ShadowRecord:
    """Hash-chain every generated card and abstention outside Git."""

    def __init__(self, path: Path) -> None:
        resolved = path.resolve()
        if (
            resolved.parent.name != OPERATIONAL
            or any((parent / ".git").exists() for parent in resolved.parents)
            or any(parent.is_symlink() or parent.is_junction() for parent in (path, *path.parents))
        ):
            raise ValueError("shadow record must be in an unlinked OPERATIONAL root outside Git")
        self.path = path
        self.events: list[dict[str, Any]] = []
        if path.exists():
            raw = path.read_bytes()
            if raw and not raw.endswith(b"\n"):
                raise ValueError("shadow chain has a truncated final record")
            for line in raw.splitlines():
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError("shadow chain has an invalid record")
                self._validate(event)
                self.events.append(event)

    def _validate(self, event: dict[str, Any]) -> None:
        identity = {key: value for key, value in event.items() if key != "content_hash"}
        if (
            set(event) != {"sequence", "kind", "session", "detail", "previous_hash", "content_hash"}
            or event["sequence"] != len(self.events) + 1
            or event["kind"] not in {"card", "abstention"}
            or event["previous_hash"] != (self.events[-1]["content_hash"] if self.events else "")
            or digest(identity) != event["content_hash"]
        ):
            raise ValueError("shadow chain identity or hash mismatch")

    def append(self, kind: str, session: date, detail: object) -> dict[str, Any]:
        if kind not in {"card", "abstention"}:
            raise ValueError("unknown shadow event")
        # A second writer or modified file must be detected before append.
        current = ShadowRecord(self.path)
        if [event["content_hash"] for event in current.events] != [
            event["content_hash"] for event in self.events
        ]:
            raise ValueError("shadow chain changed on disk")
        identity = {
            "sequence": len(self.events) + 1,
            "kind": kind,
            "session": session.isoformat(),
            "detail": json.loads(canonical_payload(detail)),
            "previous_hash": self.events[-1]["content_hash"] if self.events else "",
        }
        event = {**identity, "content_hash": digest(identity)}
        self._validate(event)
        with self.path.open("ab") as handle:
            handle.write(canonical_payload(event) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.events.append(event)
        return event
