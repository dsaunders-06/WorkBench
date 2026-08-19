"""The read-only capability probe put to a live IB Gateway - W1.1's instrument.

`capabilities.py` answers "what does OUR adapter implement", by inspecting our
own classes. It connects to nothing, so its output is identical whether or not
an IBKR account exists. This module answers the other half, and only a running
Gateway can: **what does IBKR actually return.**

The distinction matters because of how these capabilities fail. `recent_fills`,
`resting_stops`, `resting_stop_orders` and `announcements` are optional on
`BrokerAdapter` and every caller guards with `getattr`, so a missing one
neither raises nor corrupts - absorption, verification and detection just stop
happening. A summary of a response can reproduce that same silence. The raw
response cannot, which is why `Observation.raw` is a repr of the object itself
and the report prints it verbatim.

Four outcomes, deliberately not three:

    absent  no such method on the client
    raised  it exists and failed - and what it raised IS the measurement
            (permissions, subscriptions and pacing all surface here)
    empty   it answered, with nothing
    data    it answered, with something

"Returned empty" and "is not implemented" are different findings that a
boolean would merge, and merging them is how a capability audit concludes a
working method is missing, or the reverse.

**This module never writes.** Stage 1 permits exactly one order - a single
operator-approved stop, placed by hand to answer whether a simulated stop is
visible to `openTrades()` - and it is not placed from here.
"""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from qat.config import Settings
from qat.data.broker.ib_adapter import _LIVE_PORTS, _PAPER_PORTS, LivePortInPaperModeError

Outcome = Literal["absent", "raised", "empty", "data"]

# A clientId of its own. IBKR does not multiplex a clientId: a second
# connection using one already in use silently displaces the first, so a probe
# sharing the app's id would knock the running application off its Gateway.
PROBE_CLIENT_ID = 99

ANNOUNCEMENTS = "announcements - no IB equivalent exists"

_NO_ANNOUNCEMENT_FEED = (
    "No structured corporate-action feed. Measured against ib_async 2.1.0: "
    "reqFundamentalData returns XML report documents and reqHistoricalNews "
    "returns unstructured headline text. Neither is an announcements feed in "
    "the shape M39's detector consumes, so this is a decision to record "
    "(Task 5), not code to write."
)


@dataclass(frozen=True)
class Observation:
    """One call, and what came back. `raw` is evidence, not description."""

    question: str
    call: str
    outcome: Outcome
    raw: str
    count: int | None = None
    perm_ids: tuple[int, ...] = field(default=())


# (question this answers, how it is called, attribute, positional args)
_PROBES: tuple[tuple[str, str, str, tuple[Any, ...]], ...] = (
    (
        "Is this the PAPER session? Paper accounts are prefixed DU.",
        "IB.managedAccounts()",
        "managedAccounts",
        (),
    ),
    (
        "recent_fills: what does this session's fill history look like? "
        "Documented as 'all fills from this session', so it CANNOT see a fill "
        "that happened while the app was down - the case absorb_broker_fills "
        "exists for.",
        "IB.fills()",
        "fills",
        (),
    ),
    (
        "recent_fills: how far back do executions actually go? This is the "
        "retention measurement - IB.fills() cannot answer it.",
        "IB.reqExecutions()",
        "reqExecutions",
        (),
    ),
    (
        "resting_stops / resting_stop_orders: is a stop VISIBLE to the API? "
        "If a simulated stop is invisible here, protection verification "
        "silently stops working - the app's strongest safety claim.",
        "IB.openTrades()",
        "openTrades",
        (),
    ),
    (
        "resting_stops: does the all-orders call agree with openTrades()? A "
        "disagreement is itself the finding.",
        "IB.reqAllOpenOrders()",
        "reqAllOpenOrders",
        (),
    ),
    (
        "Context for the stop question: what does the account hold?",
        "IB.positions()",
        "positions",
        (),
    ),
)


def connection_target(settings: Settings) -> tuple[str, int, int]:
    """Where to connect, refusing a live port in paper mode.

    The probe connects on its own rather than through `IBAdapter`, so W1.4's
    guard does not cover it and has to be carried here. A measurement script
    is precisely the thing run in a hurry against whatever Gateway happens to
    be open, and the failure it prevents - every `is_live` consumer reading
    'paper' while real orders are reachable - does not announce itself.

    One-directional, exactly as in `IBAdapter`: live mode against a paper port
    is the safe mismatch.
    """
    if not settings.is_live and settings.ibkr_port in _LIVE_PORTS:
        paper = ", ".join(f"{port} (paper {name})" for port, name in _PAPER_PORTS.items())
        raise LivePortInPaperModeError(
            f"trading_mode is 'paper' but ibkr_port={settings.ibkr_port} reaches a LIVE "
            f"IBKR session. The probe will not connect. Use {paper}."
        )
    return settings.ibkr_host, settings.ibkr_port, PROBE_CLIENT_ID


def check_paper_account(accounts: Sequence[str]) -> None:
    """Refuse a session whose accounts are not paper accounts.

    The port guard checks what was CONFIGURED; this checks what the socket
    actually reached, which is the same distinction W1.4 was written for.
    IBKR paper accounts are prefixed `DU`.
    """
    live = [account for account in accounts if not account.upper().startswith("DU")]
    if live:
        raise LivePortInPaperModeError(
            f"managedAccounts() answered with non-paper account(s) {live}. This Gateway is "
            "logged into a LIVE session - stop, and log into the paper session instead."
        )


def _perm_ids_in(response: Any) -> tuple[int, ...]:
    """Every permId visible in a response, in the order encountered.

    Task 3 records `permId` as the order identity because `orderId` is
    per-session, and noted that permId surviving a Gateway restart was
    assumed rather than measured. The measurement is: note these, restart the
    Gateway, run again, compare.
    """
    found: list[int] = []
    for item in response if isinstance(response, list | tuple) else [response]:
        for holder in (
            item,
            getattr(item, "order", None),
            getattr(item, "orderStatus", None),
            getattr(item, "execution", None),
        ):
            perm_id = getattr(holder, "permId", None)
            if isinstance(perm_id, int) and perm_id and perm_id not in found:
                found.append(perm_id)
    return tuple(found)


async def _call(client: Any, attribute: str, args: tuple[Any, ...]) -> tuple[Outcome, str, Any]:
    # Prefer the *Async form where ib_async has one. Its sync `reqExecutions`
    # and `reqAllOpenOrders` are wrappers that call `IB._run(...)`, which
    # raises once an event loop is already running - and this probe runs
    # inside `asyncio.run`. Calling the sync form would record OUR nested-loop
    # bug as an IBKR finding, on a Gateway session that is not cheap to
    # arrange twice. The pure accessors (`fills`, `openTrades`, `positions`,
    # `managedAccounts`) have no async twin and are read straight from
    # ib_async's local state, so the fallback is the normal path, not an edge.
    method = getattr(client, f"{attribute}Async", None) or getattr(client, attribute, None)
    if method is None:
        return "absent", f"the client has no attribute {attribute!r}", None
    try:
        response = method(*args)
        if inspect.isawaitable(response):
            # ib_async exposes sync and async forms of most requests. A
            # coroutine captured with repr() records the object rather than
            # the answer - a probe that measured nothing while appearing to.
            response = await response
    except Exception as exc:  # noqa: BLE001 - what it raised IS the measurement
        return "raised", f"{type(exc).__name__}: {exc}", None
    if response is None or (
        isinstance(response, Sequence) and not isinstance(response, str) and len(response) == 0
    ):
        return "empty", repr(response), response
    return "data", repr(response), response


async def probe(client: Any) -> list[Observation]:
    """Run every read-only probe against `client` and record what came back.

    Every probe runs even if an earlier one raises. A Gateway session is
    arranged rather than summoned, and a measurement that stops at the first
    exception spends the session to return one line.
    """
    observations: list[Observation] = []
    for question, call, attribute, args in _PROBES:
        outcome, raw, response = await _call(client, attribute, args)
        observations.append(
            Observation(
                question=question,
                call=call,
                outcome=outcome,
                raw=raw,
                count=len(response) if isinstance(response, Sequence) else None,
                perm_ids=_perm_ids_in(response) if response is not None else (),
            )
        )

    observations.append(
        Observation(
            question=(
                "announcements: is there any structured corporate-action feed? "
                "M39's ex-date gate is the piece observed working in production."
            ),
            call=ANNOUNCEMENTS,
            outcome="absent",
            raw=_NO_ANNOUNCEMENT_FEED,
        )
    )
    return observations


def observed_perm_ids(observations: Sequence[Observation]) -> list[int]:
    """Every permId seen across the run, deduplicated, in order."""
    found: list[int] = []
    for observation in observations:
        for perm_id in observation.perm_ids:
            if perm_id not in found:
                found.append(perm_id)
    return found


def render(observations: Sequence[Observation], account: str, now: datetime | None = None) -> str:
    """The report. Raw responses verbatim - a summary would reproduce exactly
    the silence this measurement exists to break."""
    stamp = (now or datetime.now(UTC)).isoformat()
    lines = [
        "# IBKR capability measurement - raw responses",
        "",
        f"- Run at: {stamp}",
        f"- Account: {account}",
        f"- clientId: {PROBE_CLIENT_ID} (read-only connection)",
        "",
        "| call | outcome | count |",
        "|---|---|---|",
    ]
    for observation in observations:
        count = "-" if observation.count is None else str(observation.count)
        lines.append(f"| `{observation.call}` | **{observation.outcome}** | {count} |")

    perm_ids = observed_perm_ids(observations)
    lines += [
        "",
        f"permIds observed: {perm_ids if perm_ids else 'none'}",
        "",
        "## Raw responses",
        "",
    ]
    for observation in observations:
        lines += [
            f"### `{observation.call}` - {observation.outcome}",
            "",
            observation.question,
            "",
            "```",
            observation.raw,
            "```",
            "",
        ]
    return "\n".join(lines)
