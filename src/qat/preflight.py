"""Pre-flight checks: what is true before a session, rather than after it.

Four live runs against the paper Gateway on 19 August found four defects that a
green test suite could not - the capability probe was a rubber stamp, the
bracket run found M96, the protection scan found M99, and the wiring run found
M102. That is not bad luck. The fakes and the broker disagreed, and only one of
them was real.

**The rule this module enforces on itself: a check that could not be performed
is not a check that passed.** `UNKNOWN` blocks READY exactly as `FAIL` does.
Task 1's first run was one third of a measurement because an empty answer from
an empty account was read as an answer; a pre-flight that reported READY while
quietly skipping half its checks would be a worse instance of the same thing -
an alarm that cannot fire.

Read-only throughout. It places nothing, cancels nothing and modifies nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from qat.config import Settings


class Status(Enum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"
    # Could not be established. Deliberately distinct from FAIL - "the Gateway
    # refused" and "we never asked" are different facts - and deliberately NOT
    # a pass.
    UNKNOWN = "UNKNOWN"


class Verdict(Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str


def verdict_for(checks: list[Check]) -> Verdict:
    """READY only when every check ran and none failed.

    An empty list is BLOCKED: no checks at all is the emptiest unchecked state
    there is, and a pre-flight that green-lights on having done nothing is
    exactly the instrument failure this exists to prevent.
    """
    if not checks:
        return Verdict.BLOCKED
    if any(c.status in (Status.FAIL, Status.UNKNOWN) for c in checks):
        return Verdict.BLOCKED
    return Verdict.READY


def settings_checks(settings: Settings) -> list[Check]:
    """Configuration, where a session that cannot trade is usually born.

    These need no network, so they always run - which matters, because the
    failures they catch are the quiet ones. A session configured to execute
    nothing looks exactly like a session where the strategy found nothing, and
    the difference is only visible afterwards in an empty ledger.
    """
    checks: list[Check] = []

    # --- trading mode and port ---------------------------------------------
    live_ports = {4001, 7496}
    if not settings.is_live and settings.ibkr_port in live_ports:
        checks.append(
            Check(
                "trading mode",
                Status.FAIL,
                f"trading_mode=paper but ibkr_port={settings.ibkr_port} reaches a LIVE IBKR "
                f"session. Use 4002 (Gateway) or 7497 (TWS).",
            )
        )
    elif settings.is_live:
        checks.append(
            Check(
                "trading mode",
                Status.FAIL,
                "trading_mode=live. This pre-flight is for paper sessions; a live session "
                "needs a decision nobody should reach by running a script.",
            )
        )
    else:
        checks.append(
            Check(
                "trading mode",
                Status.OK,
                f"paper, port {settings.ibkr_port}",
            )
        )

    # --- market vs broker ---------------------------------------------------
    if settings.broker == "ibkr" and settings.market != "ASX":
        checks.append(
            Check(
                "market",
                Status.WARN,
                f"broker=ibkr with market={settings.market}. Supported, but the ASX work "
                f"(contracts, costs, calendar) is what has been measured.",
            )
        )
    elif settings.broker == "alpaca" and settings.market != "US":
        checks.append(
            Check(
                "market",
                Status.FAIL,
                f"broker=alpaca with market={settings.market} - Alpaca trades US equities "
                f"only, so this watchlist cannot be traded through it.",
            )
        )
    else:
        checks.append(Check("market", Status.OK, f"{settings.market} through {settings.broker}"))

    # --- market data --------------------------------------------------------
    source = settings.market_data_source
    if source == "synthetic":
        checks.append(
            Check(
                "market data",
                Status.FAIL,
                "market_data_source=synthetic. These bars are INVENTED, not degraded - a "
                "session run on them produces expectancy from nothing.",
            )
        )
    elif source == "alpaca" and settings.market != "US":
        checks.append(
            Check(
                "market data",
                Status.FAIL,
                f"market_data_source=alpaca with market={settings.market}. Alpaca serves US "
                f"equities only, so it returns nothing and the feed degrades to SYNTHETIC.",
            )
        )
    else:
        checks.append(Check("market data", Status.OK, f"{source} for {settings.market}"))

    # --- autonomy -----------------------------------------------------------
    promoted = [s.strip() for s in settings.autonomous_strategies.split(",") if s.strip()]
    if settings.execution_mode == "auto" and not promoted:
        checks.append(
            Check(
                "autonomy",
                Status.FAIL,
                "execution_mode=auto but autonomous_strategies is EMPTY, so no strategy is "
                "cleared and nothing will ever be executed. The session would evaluate every "
                "signal and trade nothing - indistinguishable afterwards from a session where "
                "the strategy found nothing.",
            )
        )
    elif settings.execution_mode != "auto":
        checks.append(
            Check(
                "autonomy",
                Status.WARN,
                f"execution_mode={settings.execution_mode}: orders will wait for an operator "
                f"to sign them off. Correct for a supervised run, and a session that sits "
                f"waiting for a human who is not there if this was meant to be unattended.",
            )
        )
    else:
        checks.append(
            Check("autonomy", Status.OK, f"auto, strategies cleared: {', '.join(promoted)}")
        )

    # --- what is knowingly given up, DERIVED for the configured broker -----
    #
    # This asserted "IBKR publishes no corporate-action feed" unconditionally,
    # and printed it on the first real run against an ALPACA configuration -
    # where announcements are implemented and the ex-date gate works. A
    # sentence that explains and is wrong, inside the instrument written to
    # catch those. Asked of the capability register now, which is what the
    # application itself consults.
    from qat.data.broker.capabilities import KNOWN_ADAPTERS, inspect_adapter

    adapter = KNOWN_ADAPTERS().get(settings.broker)
    missing = sorted(inspect_adapter(adapter).missing_optional) if adapter is not None else []
    if "announcements" in missing:
        checks.append(
            Check(
                "corporate actions",
                Status.WARN,
                f"{settings.broker} does not implement announcements, so detection is "
                f"UNAVAILABLE: a split cannot be seen before its ex-date, entries are not "
                f"gated on pending actions and stops are not adjusted through one. Accepted "
                f"deliberately (Task 5) - listed so it is never a surprise.",
            )
        )
    elif adapter is not None:
        checks.append(
            Check(
                "corporate actions",
                Status.OK,
                f"{settings.broker} implements announcements; the ex-date entry gate has an "
                f"input. Mode is {settings.corporate_action_mode!r}"
                + (
                    " - SHADOW, so an adjustment is logged and never placed."
                    if settings.corporate_action_mode == "shadow"
                    else "."
                ),
            )
        )

    # --- two settings each valid, jointly useless --------------------------
    #
    # Caught by hand on 20 August while changing the watchlist: `curated` gave
    # STW/BHP/CBA/CSL while the allow list permitted RIO/APA/AMC/MGR/SGP/NHF.
    # Each is a fine setting. Together they describe a session that polls all
    # day and is forbidden from trading anything it can see - and afterwards
    # that is indistinguishable from a session where nothing signalled.
    from qat.data import universe

    watchlist = set(universe.resolve_watchlist(settings))
    allowed = settings.entry_allow_list_set()
    tradable = sorted(watchlist & allowed) if allowed is not None else sorted(watchlist)
    if not tradable:
        checks.append(
            Check(
                "tradable universe",
                Status.FAIL,
                f"the watchlist ({len(watchlist)} symbols) and the entry allow list "
                f"({len(allowed or ())} symbols) DO NOT OVERLAP, so no entry can ever be "
                f"placed. The session would run to the close and trade nothing, which reads "
                f"afterwards exactly like a session where the strategy found nothing.",
            )
        )
    else:
        shown = ", ".join(tradable[:6]) + (" ..." if len(tradable) > 6 else "")
        checks.append(
            Check(
                "tradable universe",
                Status.OK,
                f"{len(tradable)} symbol(s) both watched and permitted: {shown}",
            )
        )

    return checks


# --- the half that needs a Gateway and a feed ------------------------------
#
# Each of these returns UNKNOWN rather than raising when it cannot establish
# its fact, and UNKNOWN blocks READY. That is the whole discipline: the
# pre-flight is allowed to fail to check something, and is not allowed to call
# the result a pass.


async def gateway_checks(settings: Settings, ib_client: object) -> list[Check]:
    """Is the Gateway there, is it the PAPER session, and is it reachable."""
    connected = getattr(ib_client, "isConnected", None)
    if not callable(connected) or not connected():
        return [
            Check(
                "gateway",
                Status.UNKNOWN,
                "not connected, so nothing behind this could be checked. Start IB Gateway, "
                "log into the PAPER session, and tick Enable ActiveX and Socket Clients.",
            )
        ]

    checks: list[Check] = [Check("gateway", Status.OK, f"connected on port {settings.ibkr_port}")]

    accounts = list(getattr(ib_client, "managedAccounts", lambda: [])())
    if not accounts:
        checks.append(Check("account", Status.UNKNOWN, "managedAccounts() answered nothing"))
    elif not all(a.upper().startswith("DU") for a in accounts):
        checks.append(
            Check(
                "account",
                Status.FAIL,
                f"{accounts} is not a paper account - paper accounts are prefixed DU. "
                f"This Gateway is logged into a LIVE session.",
            )
        )
    else:
        checks.append(Check("account", Status.OK, f"paper account {', '.join(accounts)}"))
    return checks


async def book_checks(broker: object) -> list[Check]:
    """What the account already carries, through the APP's own adapter.

    Through the adapter rather than the raw client on purpose: this is the path
    a session uses, and it is the path that was wrong twice on 19 August.
    """
    checks: list[Check] = []

    try:
        account = await broker.account()  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 - the point is to report, not to crash
        checks.append(Check("account value", Status.UNKNOWN, f"{type(exc).__name__}: {exc}"))
    else:
        checks.append(
            Check(
                "account value",
                Status.OK if account.net_liquidation > 0 else Status.FAIL,
                f"net_liq {account.net_liquidation:,.2f}, cash {account.cash:,.2f}",
            )
        )

    try:
        positions = await broker.positions()  # type: ignore[attr-defined]
        stops = await broker.resting_stops()  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("book", Status.UNKNOWN, f"{type(exc).__name__}: {exc}"))
        return checks

    held = [p for p in positions if abs(float(p.quantity)) > 0]
    unprotected = [p.symbol for p in held if p.symbol not in stops]
    if not held:
        checks.append(Check("book", Status.OK, "no positions, no resting stops"))
    elif unprotected:
        checks.append(
            Check(
                "book",
                Status.FAIL,
                f"{len(held)} position(s) held and {len(unprotected)} carry NO resting stop "
                f"at the broker: {', '.join(unprotected)}. Starting a session over an "
                f"unprotected position is how the protection question gets answered by a gap.",
            )
        )
    else:
        checks.append(
            Check("book", Status.OK, f"{len(held)} position(s), all carrying a resting stop")
        )
    return checks


async def contract_checks(symbols: list[str], market: str, ib_client: object) -> list[Check]:
    """Does every symbol the session will trade resolve to a real contract?

    Measured on 19 August: `BHP.AX` returned error 200 in either currency until
    M96, and an unsuffixed `BHP` in USD resolved to the NYSE ADR rather than
    ASX. A symbol that does not resolve is an entry that cannot be placed, and
    that is better known now than at the moment a signal fires.
    """
    from qat.data.broker.ib_translate import to_ib_contract

    request = getattr(ib_client, "reqContractDetailsAsync", None)
    if not callable(request):
        return [Check("contracts", Status.UNKNOWN, "the client cannot resolve contracts")]

    unresolved: list[str] = []
    for symbol in symbols:
        try:
            details = await request(to_ib_contract(symbol, market))
        except Exception:  # noqa: BLE001
            unresolved.append(symbol)
            continue
        if not details:
            unresolved.append(symbol)

    if unresolved:
        return [
            Check(
                "contracts",
                Status.FAIL,
                f"{len(unresolved)} of {len(symbols)} did not resolve: "
                f"{', '.join(unresolved)}. Entries in these cannot be placed.",
            )
        ]
    return [Check("contracts", Status.OK, f"all {len(symbols)} resolve on {market}")]


async def feed_checks(symbols: list[str], source: object) -> list[Check]:
    """Is the price feed actually producing a price for every symbol?

    A source that returns nothing degrades to SYNTHETIC downstream, which is
    the one failure that corrupts a record rather than stopping it.
    """
    poll = getattr(source, "_poll_once", None)
    if not callable(poll):
        return [Check("feed", Status.UNKNOWN, "the source cannot be polled directly")]

    try:
        ticks = await poll(list(symbols))
    except Exception as exc:  # noqa: BLE001
        return [Check("feed", Status.UNKNOWN, f"{type(exc).__name__}: {exc}")]

    priced = {t.symbol for t in ticks if t.price > 0}
    missing = [s for s in symbols if s not in priced]
    if missing and not priced:
        # EVERY symbol failing is a statement about the SOURCE, not about the
        # symbols. On 20 August yfinance answered "possibly delisted" for all
        # 101 ASX names at once, megacaps included, minutes after pricing them
        # - a rate limit. Listing the symbols would send an operator to check
        # a hundred tickers instead of the one thing that was wrong.
        return [
            Check(
                "feed",
                Status.FAIL,
                f"the source priced NONE of the {len(symbols)} symbols asked for. That is a "
                f"SOURCE failure - a rate limit or an outage - not {len(symbols)} delistings. "
                f"yfinance blocks under sustained polling; wait for it to clear and reduce "
                f"the watchlist rather than investigating the symbols.",
            )
        ]
    if missing:
        return [
            Check(
                "feed",
                Status.FAIL,
                f"no price for {', '.join(missing)} ({len(priced)} of {len(symbols)} priced). "
                f"A symbol the feed cannot price is excluded from signals, and a source "
                f"returning nothing degrades to SYNTHETIC bars.",
            )
        ]
    return [Check("feed", Status.OK, f"all {len(symbols)} priced")]


def session_checks(market: str, now: object = None) -> list[Check]:
    """Is the market open, and does the app's calendar agree with the clock?"""
    from qat.domain import market_calendar as mc

    try:
        session = mc.session_for(market, now)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001
        return [Check("session", Status.UNKNOWN, f"{type(exc).__name__}: {exc}")]

    # `is_open`, NOT `phase`. `phase` is a WITHIN-session descriptor - 'Opening
    # Range', 'Midday Lull' - and is None when the market is shut, so
    # `phase == "open"` was a comparison that could never be true. The
    # pre-flight would have reported the market closed at midday: a check that
    # cannot pass, in the instrument written to catch checks that cannot fail.
    if getattr(session, "is_open", False):
        phase = getattr(session, "phase", None)
        return [Check("session", Status.OK, f"{market} is OPEN ({phase})")]
    return [
        Check(
            "session",
            Status.WARN,
            f"{market} is closed. The session stands down until it opens, which is "
            f"correct - but a machinery test run now measures nothing.",
        )
    ]


def render(checks: list[Check]) -> str:
    """The report: every check on its own line with its reason, and a verdict
    DERIVED from them rather than asserted alongside them."""
    width = max((len(c.name) for c in checks), default=0) + 2
    lines = [f"  {c.status.value:<9}{c.name:<{width}}{c.detail}" for c in checks]
    blocking = [c for c in checks if c.status in (Status.FAIL, Status.UNKNOWN)]
    lines.append("")
    lines.append(f"  VERDICT: {verdict_for(checks).value}")
    if blocking:
        names = ", ".join(f"{c.name} ({c.status.value})" for c in blocking)
        lines.append(f"  blocked by: {names}")
    return "\n".join(lines)
