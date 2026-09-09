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

import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, time
from enum import Enum
from zoneinfo import ZoneInfo

from qat.config import Settings
from qat.data.broker.ib_hours import parse_ib_hours
from qat.domain.market_calendar import (
    MARKET_TIMEZONES,
    auction_tail_minutes,
    is_trading_day,
    regular_hours,
    trading_date,
)

# (market, boundary) -> (app value, IBKR value, when measured, why accepted)
#
# A disagreement recorded here has been LOOKED AT and accepted, which is why
# each entry carries the date it was measured and the reason: an undated
# exception is indistinguishable from one nobody has re-examined.
#
# An allowlist of exactly one, NOT a tolerance band - a band would swallow the
# next disagreement too.
_ACCEPTED_HOURS_DIVERGENCES: dict[tuple[str, str], tuple[time, time, str, str]] = {
    ("ASX", "open"): (
        time(10, 0),
        time(9, 59),
        "2026-08-21",
        "IBKR reports 0959 for every ASX contract probed; 10:00 is when ASX "
        "continuous trading starts, so this reads as broker-side rounding. See "
        "docs/superpowers/specs/2026-08-21-asx-session-hours-raw.md",
    ),
}

# IBKR names some zones by their legacy aliases. Australia/NSW and
# Australia/Sydney are the same zone; the label differing is not a finding.
_IB_ZONE_ALIASES: dict[str, str] = {"Australia/NSW": "Australia/Sydney"}


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


# The four sockets an IBKR session can be behind, named (M125). A process check
# cannot tell these apart and cannot tell any of them from "not logged in".
KNOWN_IBKR_PORTS: dict[int, str] = {
    4001: "live Gateway",
    4002: "paper Gateway",
    7496: "live TWS",
    7497: "paper TWS",
}


def port_is_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """Whether something is LISTENING, which is the only question worth asking.

    A running Gateway with nobody logged into it holds its API port closed, so
    checking for the process reports healthy while every connection is refused
    - "quiet looks like healthy" again, in a new place. On 21 August that cost a
    restart four minutes before the open.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def gateway_port_check(
    settings: Settings, probe: Callable[[str, int], bool] | None = None
) -> Check:
    """Which of the four IBKR sockets is actually listening, and is ours one.

    Reports every port it found rather than only the configured one, because
    the two failures look identical from the configured port alone: "the
    Gateway is not up" and "the Gateway is up, but it is the OTHER one".
    """
    probe = probe or (lambda host, port: port_is_open(host, port))
    host = settings.ibkr_host
    open_ports = [port for port in sorted(KNOWN_IBKR_PORTS) if probe(host, port)]
    found = (
        ", ".join(f"{port} ({KNOWN_IBKR_PORTS[port]})" for port in open_ports)
        if open_ports
        else "none of the four"
    )

    if settings.ibkr_port in open_ports:
        return Check(
            "gateway port",
            Status.OK,
            f"{settings.ibkr_port} is listening on {host}. Open: {found}",
        )
    return Check(
        "gateway port",
        Status.FAIL,
        f"{settings.ibkr_port} ({KNOWN_IBKR_PORTS.get(settings.ibkr_port, 'unknown')}) is "
        f"NOT listening on {host}. Open: {found}. A Gateway that is running but not "
        f"logged in refuses its API port, so the process being up proves nothing.",
    )


def settings_checks(settings: Settings) -> list[Check]:
    """Configuration, where a session that cannot trade is usually born.

    These need no network, so they always run - which matters, because the
    failures they catch are the quiet ones. A session configured to execute
    nothing looks exactly like a session where the strategy found nothing, and
    the difference is only visible afterwards in an empty ledger.
    """
    checks: list[Check] = []

    # --- the regime engine's volatility column ------------------------------
    #
    # ⚠️ THE SILENT FAILURE THIS EXISTS FOR. `regime_vix_series` names which
    # series fills `vix_level`; nothing publishes a series it was not asked to
    # fetch. Point it at `^AXVI` without adding `^AXVI` to `bar_macro_series`
    # and the column stays at ZERO for the whole session - and the engine fits
    # happily on a flat feature, so nothing else complains. The column led the
    # raw feature spread at 85.1% in the 8 September live fit.
    published = {*settings.fred_series, *settings.bar_macro_series}
    if settings.regime_vix_series not in published:
        checks.append(
            Check(
                "regime VIX series",
                Status.FAIL,
                f"regime_vix_series={settings.regime_vix_series!r} but nothing publishes it. "
                f"Add it to fred_series (FRED) or bar_macro_series (daily bars), or the "
                f"regime engine runs the whole session with its volatility column at ZERO "
                f"and says nothing.",
            )
        )
    else:
        checks.append(
            Check(
                "regime VIX series",
                Status.OK,
                f"{settings.regime_vix_series} fills vix_level and is published.",
            )
        )

    # ⚠️ THE SECOND HALF OF THE SAME TRAP. Swapping the VIX series without
    # moving the shock level leaves the level calibrated for a different index.
    # `^AXVI` reaches 25.0 on 0.2% of ASX days, so the SHOCK regime would be off
    # for the session - and a regime that never fires looks exactly like a
    # market that never shocked.
    if settings.regime_vix_series != "VIXCLS" and settings.vix_shock_level == 25.0:
        checks.append(
            Check(
                "VIX shock level",
                Status.WARN,
                f"regime_vix_series={settings.regime_vix_series!r} but vix_shock_level is "
                f"still 25.0, the level measured for the US VIX. ^AXVI reaches 25.0 on 0.2% "
                f"of ASX days - check this is the level you meant, or the SHOCK regime "
                f"never fires.",
            )
        )

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

    # M109 widened this. A non-empty overlap only proves SOMETHING can trade,
    # and on 20 August that was true and useless: three permitted names sat
    # inside a 100-symbol watchlist, this check would have returned OK, and six
    # correct signals were refused because the three were the previous day's.
    # No structural rule separates a stale allow list from a deliberate
    # narrowing, so the check does not try to - it reports the size of what it
    # is refusing and lets a human recognise their own mistake.
    universe_split = universe.describe_tradable(
        universe.resolve_watchlist(settings), settings.entry_allow_list_set()
    )
    watched, tradable = universe_split.watched, universe_split.tradable
    shown = ", ".join(tradable[:6]) + (" ..." if len(tradable) > 6 else "")
    if not tradable:
        checks.append(
            Check(
                "tradable universe",
                Status.FAIL,
                f"the watchlist ({len(watched)} symbols) and the entry allow list "
                f"({len(universe_split.unwatched)} symbols, none of them watched) DO NOT "
                f"OVERLAP, so no entry can ever be placed. The session "
                f"would run to the close and trade nothing, which reads afterwards exactly "
                f"like a session where the strategy found nothing.",
            )
        )
    elif universe_split.refused or universe_split.unwatched:
        detail = [f"{len(tradable)} of {len(watched)} watched symbol(s) may be entered: {shown}."]
        if universe_split.refused:
            refused = ", ".join(universe_split.refused[:6]) + (
                " ..." if len(universe_split.refused) > 6 else ""
            )
            detail.append(
                f"{len(universe_split.refused)} watched symbol(s) will be polled, may "
                f"signal, and every entry will be REFUSED: {refused}."
            )
        if universe_split.unwatched:
            detail.append(
                f"{len(universe_split.unwatched)} permitted symbol(s) are not watched and "
                f"can never trade: {', '.join(universe_split.unwatched[:6])}."
            )
        detail.append(
            "Each setting is valid alone. Together they decide which signals are thrown "
            "away, and afterwards that is indistinguishable from a session where the "
            "strategy found nothing."
        )
        checks.append(Check("tradable universe", Status.WARN, " ".join(detail)))
    else:
        checks.append(
            Check(
                "tradable universe",
                Status.OK,
                f"all {len(tradable)} watched symbol(s) may be entered: {shown}",
            )
        )

    return checks


# How many symbols the feed check prices when no explicit --sample is given.
# A cap exists because IBKR paces contract resolution one request at a time, so
# a hundred symbols is slow. The cap is not the problem; a cap that silently
# excluded part of a SMALL watchlist was.
PROBE_CAP = 20


def probe_plan(watchlist: Sequence[str], sample: int | None) -> tuple[tuple[str, ...], Check]:
    """Which symbols the feed check will price, and a check that says so.

    M110. `--sample` defaulted to 5, chosen when the watchlist was a hundred.
    On the six-symbol ASX watchlist the pre-flight priced five, reported
    "all 5 priced", and never contacted the sixth - a clean-looking feed check
    of a watchlist it had not finished reading.

    Returned as a pair rather than sliced at the call site so that the number
    probed and the number claimed cannot be decided in two places. The check is
    the point: capping is fine, capping silently is not.
    """
    total = len(watchlist)
    limit = min(total, PROBE_CAP if sample is None or sample <= 0 else sample)
    probe = tuple(watchlist[:limit])
    if total == 0:
        return probe, Check(
            "feed coverage",
            Status.FAIL,
            "the watchlist is empty, so no symbol was priced. Zero of zero is not a pass.",
        )
    if limit >= total:
        return probe, Check(
            "feed coverage",
            Status.OK,
            f"all {limit} of {total} watched symbol(s) were priced",
        )
    return probe, Check(
        "feed coverage",
        Status.WARN,
        f"only {limit} of {total} watched symbol(s) were priced - the other "
        f"{total - limit} are UNVERIFIED and this check says nothing about them. "
        f"Pass --sample {total} to cover the whole watchlist.",
    )


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
    # ⚠️ WHAT THIS CHECK CANNOT SEE (item 25). `unprotected` is built by walking
    # HELD positions, so it answers "is every position protected" and never
    # "what is resting that the book does not explain". A stop resting on a
    # symbol the book does NOT hold - M141's orphan shape - is invisible here.
    #
    # Deliberately NOT widened: that question belongs to `check_resting_orders`,
    # which owns the reconciler and can act on it. Duplicating it would be a
    # second derivation of one question. What this check must stop doing is
    # implying coverage it has not got, because a clean line here reads as
    # "nothing unexpected is resting" and that was never asked.
    _LIMIT = (
        " ⚠️ This does NOT look for stops resting on symbols the book does not hold "
        "(the orphan shape); that is check_resting_orders' question, in the session."
    )
    if not held:
        checks.append(
            Check(
                "book",
                Status.OK,
                "no positions held, so nothing to protect - and nothing was checked about "
                "what may be resting." + _LIMIT,
            )
        )
    elif unprotected:
        checks.append(
            Check(
                "book",
                Status.FAIL,
                f"{len(held)} position(s) held and {len(unprotected)} carry NO resting stop "
                f"at the broker: {', '.join(unprotected)}. Starting a session over an "
                f"unprotected position is how the protection question gets answered by a "
                f"gap." + _LIMIT,
            )
        )
    else:
        checks.append(
            Check(
                "book",
                Status.OK,
                f"{len(held)} position(s), all carrying a resting stop." + _LIMIT,
            )
        )
    return checks


def compare_session_hours(
    trading_hours: str,
    liquid_hours: str,
    time_zone_id: str,
    market: str,
    days: Sequence[date],
) -> list[Check]:
    """Does the hand-maintained calendar still agree with the exchange?

    `_REGULAR_HOURS`, `asx_holidays()`, `_EARLY_CLOSE_TIMES`, `EXTRA_CLOSURES`
    and `_AUCTION_TAIL_MINUTES` are all maintained by hand. IBKR states the
    same facts per contract and per day, and this is the only thing that would
    notice if the two drifted apart. On 21 August a hand-maintained constant in
    `handoff_state.py` was found wrong for a day for want of exactly this.

    **WARN, never FAIL, and never UNKNOWN - a deliberate departure from this
    module's rule that a check which could not be performed is not a check that
    passed.** Every other check here asks whether something the session DEPENDS
    ON is true, so an unanswerable one should stop the session. This one asks
    whether a constant still matches the broker; the calendar is authoritative
    at runtime either way, so nothing about the session degrades when the
    comparison cannot be made. UNKNOWN would let an odd vendor string block
    trading over a disagreement that is cosmetic by construction.
    """
    tz = MARKET_TIMEZONES[market]  # type: ignore[index]
    trading = parse_ib_hours(trading_hours, tz)
    liquid = parse_ib_hours(liquid_hours, tz)
    if not trading or not liquid:
        return [
            Check(
                "session hours",
                Status.WARN,
                "IBKR returned trading hours this cannot read, so the calendar "
                "constants were not compared against the exchange this session",
            )
        ]

    open_time, close_time = regular_hours(market)  # type: ignore[arg-type]
    tail = auction_tail_minutes(market)  # type: ignore[arg-type]
    warnings: list[Check] = []

    for day in sorted(days):
        windows = liquid.get(day)
        if windows is None:
            continue
        if not windows:
            if is_trading_day(market, day):  # type: ignore[arg-type]
                warnings.append(
                    Check(
                        "session hours",
                        Status.WARN,
                        f"IBKR reports {day.isoformat()} CLOSED; the calendar calls it a "
                        "trading day. The holiday table is hand-maintained and this is "
                        "the exchange contradicting it",
                    )
                )
            continue
        if not is_trading_day(market, day):  # type: ignore[arg-type]
            warnings.append(
                Check(
                    "session hours",
                    Status.WARN,
                    f"IBKR reports {day.isoformat()} as trading; the calendar calls it closed",
                )
            )
            continue

        start, end = windows[0]
        if start.time() != open_time and not _accepted(market, "open", open_time, start.time()):
            warnings.append(
                Check(
                    "session hours",
                    Status.WARN,
                    f"{day.isoformat()} opens at {start.time():%H:%M} on IBKR, "
                    f"{open_time:%H:%M} in the calendar",
                )
            )
        if end.time() != close_time and not _accepted(market, "close", close_time, end.time()):
            warnings.append(
                Check(
                    "session hours",
                    Status.WARN,
                    f"{day.isoformat()} closes at {end.time():%H:%M} on IBKR, "
                    f"{close_time:%H:%M} in the calendar",
                )
            )

        trading_windows = trading.get(day)
        if trading_windows:
            measured = round((trading_windows[0][1] - end).total_seconds() / 60)
            if measured != tail:
                warnings.append(
                    Check(
                        "session hours",
                        Status.WARN,
                        f"{day.isoformat()} auction tail is {measured} minute(s) on IBKR, "
                        f"{tail} in the model",
                    )
                )

    if time_zone_id and ZoneInfo(_IB_ZONE_ALIASES.get(time_zone_id, time_zone_id)) != tz:
        warnings.append(
            Check(
                "session hours",
                Status.WARN,
                f"IBKR reports timezone {time_zone_id}, the calendar uses {tz}",
            )
        )

    if warnings:
        return warnings
    return [
        Check(
            "session hours",
            Status.OK,
            f"{market} hours, auction tail and trading days all match IBKR "
            f"across {len(days)} day(s)",
        )
    ]


def _accepted(market: str, boundary: str, app_value: time, ib_value: time) -> bool:
    entry = _ACCEPTED_HOURS_DIVERGENCES.get((market, boundary))
    return entry is not None and entry[0] == app_value and entry[1] == ib_value


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
    first: object | None = None
    for symbol in symbols:
        try:
            details = await request(to_ib_contract(symbol, market))
        except Exception:  # noqa: BLE001
            unresolved.append(symbol)
            continue
        if not details:
            unresolved.append(symbol)
        elif first is None:
            first = details[0]

    if unresolved:
        return [
            Check(
                "contracts",
                Status.FAIL,
                f"{len(unresolved)} of {len(symbols)} did not resolve: "
                f"{', '.join(unresolved)}. Entries in these cannot be placed.",
            )
        ]
    checks = [Check("contracts", Status.OK, f"all {len(symbols)} resolve on {market}")]
    if first is not None:
        today = trading_date(market)  # type: ignore[arg-type]
        checks.extend(
            compare_session_hours(
                str(getattr(first, "tradingHours", "")),
                str(getattr(first, "liquidHours", "")),
                str(getattr(first, "timeZoneId", "")),
                market,
                [today],
            )
        )
    return checks


async def feed_checks(symbols: list[str], source: object) -> list[Check]:
    """Is the price feed actually producing a price for every symbol?

    A source that returns nothing degrades to SYNTHETIC downstream, which is
    the one failure that corrupts a record rather than stopping it.
    """
    poll = getattr(source, "_poll_once", None)
    if not callable(poll):
        return [Check("feed", Status.UNKNOWN, "the source cannot be polled directly")]

    try:
        polled = await poll(list(symbols))
    except Exception as exc:  # noqa: BLE001
        return [Check("feed", Status.UNKNOWN, f"{type(exc).__name__}: {exc}")]

    # TWO SOURCES, TWO SIGNATURES. `AlpacaSource._poll_once` returns a bare
    # `list[RawTick]`; `YFinanceSource._poll_once` returns `(ticks, missing)`.
    # This was written against the first, and the second is the one
    # `QAT_MARKET_DATA_SOURCE` actually selects - so `t` bound to the inner
    # LIST and `t.price` raised AttributeError on every real run, one line
    # below the `except` that would have caught it, taking the whole script
    # down before the broker half executed.
    #
    # Found on 10 September by running the pre-flight, not by the suite: all
    # three fakes here returned the Alpaca shape, so the tests agreed with the
    # code and the code disagreed with the only source in use.
    ticks = polled[0] if isinstance(polled, tuple) else polled

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
