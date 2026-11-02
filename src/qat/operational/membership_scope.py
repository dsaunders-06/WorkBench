"""Format-free, immutable active membership supplied by a verified authority reader.

This module reads no successor file and grants no approval. Shadow entry points
must receive an explicitly configured source; there is no raw-universe fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from qat.operational.history import Membership, digest


@dataclass(frozen=True, slots=True)
class ActiveMembers:
    session: date
    symbols: tuple[str, ...]
    base_membership_hash: str
    scope_hash: str

    def __post_init__(self) -> None:
        if (
            type(self.session) is not date
            or not isinstance(self.symbols, tuple)
            or any(not isinstance(symbol, str) for symbol in self.symbols)
            or any(
                not isinstance(value, str) for value in (self.base_membership_hash, self.scope_hash)
            )
            or self.symbols != tuple(sorted(set(self.symbols)))
            or any(not symbol.endswith(".AX") for symbol in self.symbols)
            or any(
                len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
                for value in (self.base_membership_hash, self.scope_hash)
            )
        ):
            raise ValueError("invalid active membership selection")


class ActiveMembershipSource(Protocol):
    """An approved reader resolves a selection; its physical format is external."""

    def resolve(
        self, membership: Membership, session: date, *, attested_through: date | None = None
    ) -> ActiveMembers: ...


def validate_active_members(
    membership: Membership,
    session: date,
    selected: ActiveMembers,
    *,
    attested_through: date | None = None,
) -> ActiveMembers:
    allowed = {
        symbol
        for symbol in membership.symbols
        if membership.is_current(symbol, session, attested_through=attested_through)
    }
    if (
        not isinstance(selected, ActiveMembers)
        or selected.session != session
        or selected.base_membership_hash != membership.content_hash
        or not selected.symbols
        or not set(selected.symbols) <= allowed
    ):
        raise ValueError("active membership session, base or scope is unavailable")
    return selected


def resolve_active_members(
    membership: Membership,
    session: date,
    source: ActiveMembershipSource | None,
    *,
    attested_through: date | None = None,
) -> ActiveMembers:
    if source is None:
        raise ValueError("active_membership_source_unconfigured")
    return validate_active_members(
        membership,
        session,
        source.resolve(membership, session, attested_through=attested_through),
        attested_through=attested_through,
    )


def base_active_members(
    membership: Membership, session: date, *, attested_through: date | None = None
) -> ActiveMembers:
    """Legacy generic-adapter scope; never a successor approval or shadow default."""
    symbols = tuple(
        symbol
        for symbol in membership.symbols
        if membership.is_current(symbol, session, attested_through=attested_through)
    )
    return validate_active_members(
        membership,
        session,
        ActiveMembers(
            session,
            symbols,
            membership.content_hash,
            digest(
                {
                    "domain": "qat-base-membership-scope-v1",
                    "session": session,
                    "membership_hash": membership.content_hash,
                    "symbols": symbols,
                }
            ),
        ),
        attested_through=attested_through,
    )
