"""Company news, surfaced only when independent sources agree (M115).

News is the one input to this system written by people who are not the operator,
and anyone can publish. Everything here follows from that.

**The rule, an operator decision recorded 20 August 2026: at least two
INDEPENDENT sources before a story is surfaced at all.** It is a quality rule and
an injection defence in one - a single planted story cannot reach the model, so
an attacker needs two outlets rather than one blog. It is deliberately applied
here, at the edge, rather than in the prompt: a model asked to be sceptical is
not a control, and `tests/safety/test_prompt_injection_in_context_is_ignored.py`
exists because the wording of a system prompt is not what protects this.

**What this does NOT claim.** Two aggregators republishing one wire story look
like two sources and are not. Detecting syndication reliably needs the article
body and a provenance chain, neither of which the vendor gives us. So this
raises the bar from one outlet to two; it does not establish independence, and
the honest description is "corroborated", never "verified".
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

logger = logging.getLogger(__name__)

# Short words carry no topical signal and would make unrelated headlines look
# similar - "the", "for", "says" appear in everything.
_STOPWORDS = frozenset("""the and for with from that this into over after says said will has have
    its it's are was were been being about than then they their there which
    while your you our but not out now new news inc ltd plc group corp
    """.split())
_WORD = re.compile(r"[a-z0-9]+")

# Titles this similar are treated as the same story.
#
# 0.50 first, then LOOSENED TO 0.40 on 20 August by operator decision, against a
# measurement rather than a preference. Best cross-outlet similarity per symbol
# on the live feed was AMC 0.57 (passed), RIO 0.44, MGR 0.08, NHF 0.00. The RIO
# pair - "Rio Tinto Ltd (Q2 2026) Earnings Call Highlights" and "Rio Tinto H1
# Earnings Call Highlights" - is one earnings call reported by two outlets, and
# 0.50 threw it away. Two outlets writing their own headline for one event share
# fewer words than they look like they should.
#
# It is a threshold, not a fix. NHF's six items came from ONE outlet, so nothing
# here can corroborate them; the binding limit is Yahoo's coverage of small ASX
# names. Loosening further would stop meaning "two outlets on ONE story" and
# start meaning "two outlets on this company", which is a much weaker claim.
_SAME_STORY = 0.40


@dataclass(frozen=True, slots=True)
class NewsItem:
    symbol: str
    title: str
    provider: str
    published: datetime
    url: str = ""


@dataclass(frozen=True, slots=True)
class CorroboratedStory:
    """One story, and the evidence that it cleared the bar.

    `providers` and `published` are carried so a reader can see WHY this passed
    without going back to the vendor. `published` is the EARLIEST report: the
    later ones are echoes, and dating a story by its last echo would make an old
    item look fresh every time another outlet picked it up.
    """

    title: str
    providers: tuple[str, ...]
    published: datetime
    items: tuple[NewsItem, ...]


def _significant(title: str) -> frozenset[str]:
    return frozenset(
        word for word in _WORD.findall(title.lower()) if len(word) > 3 and word not in _STOPWORDS
    )


def _same_story(a: frozenset[str], b: frozenset[str]) -> bool:
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= _SAME_STORY


def _outlet(provider: str) -> str:
    """A provider name reduced to its identity.

    "Simply Wall St." and "simply wall st" are one outlet. Punctuation and case
    must not buy a second vote, because the whole rule rests on counting
    outlets rather than items.
    """
    return " ".join(_WORD.findall(provider.lower()))


def corroborate(
    items: list[NewsItem],
    *,
    min_sources: int = 2,
    max_age: timedelta = timedelta(days=7),
    now: datetime | None = None,
) -> list[CorroboratedStory]:
    """Stories carried by `min_sources` or more distinct outlets, newest first.

    Age is checked rather than trusted: on 20 August a December 2025 story
    appeared in a "latest news" list, so the vendor's ordering is not recency.
    """
    moment = now or datetime.now(UTC)
    fresh = [
        item
        for item in items
        if item.title.strip() and item.provider.strip() and moment - item.published <= max_age
    ]

    clusters: list[list[NewsItem]] = []
    signatures: list[frozenset[str]] = []
    for item in sorted(fresh, key=lambda i: i.published):
        words = _significant(item.title)
        if not words:
            continue
        for index, signature in enumerate(signatures):
            if _same_story(words, signature):
                clusters[index].append(item)
                signatures[index] = signature | words
                break
        else:
            clusters.append([item])
            signatures.append(words)

    stories = []
    for cluster in clusters:
        outlets = {_outlet(item.provider) for item in cluster}
        if len(outlets) < min_sources:
            continue
        first = min(cluster, key=lambda i: i.published)
        # Distinct provider strings as the vendor spelled them, one per outlet,
        # so the reader sees the names they would recognise.
        seen: dict[str, str] = {}
        for item in cluster:
            seen.setdefault(_outlet(item.provider), item.provider)
        stories.append(
            CorroboratedStory(
                title=first.title,
                providers=tuple(seen.values()),
                published=first.published,
                items=tuple(cluster),
            )
        )
    return sorted(stories, key=lambda s: s.published, reverse=True)


# The exchange each yfinance suffix belongs to. Only the ones this application
# trades are listed; an unknown suffix means the check abstains rather than
# guessing, which is the right failure for a filter that DISCARDS.
_SUFFIX_EXCHANGE = {".AX": "ASX"}
_QUALIFIED = re.compile(r"\(([A-Z]{2,6}):([A-Z0-9.]{1,10})\)")
_BARE_TICKER = re.compile(r"\(([A-Z]{2,6})\)")


def drop_other_listings(items: list[NewsItem]) -> list[NewsItem]:
    """Remove stories about a DIFFERENT listing of the same company (M115).

    Measured on 20 August: `RIO.AX` returned two items about **LSE:RIO** and
    `MGR.AX` one about **(MRVGF)**, the US over-the-counter line. A dual-listed
    company's other line is a different security at a different price in a
    different currency, and reasoning about an ASX holding from London news is
    the kind of wrong that looks right.

    Run BEFORE `corroborate`. Two foreign-listing items corroborate each other
    perfectly well, and the live RIO.AX sample was exactly that pair.
    """
    kept = []
    for item in items:
        suffix = item.symbol[item.symbol.rfind(".") :] if "." in item.symbol else ""
        expected = _SUFFIX_EXCHANGE.get(suffix)
        if expected is None:
            kept.append(item)  # unknown market: abstain rather than discard
            continue
        root = item.symbol[: item.symbol.rfind(".")].upper()
        title = item.title

        qualified = _QUALIFIED.findall(title)
        if qualified:
            # An explicit exchange prefix is the reliable signal. Keep the item
            # only if one of them names THIS exchange.
            if not any(exchange == expected for exchange, _ in qualified):
                continue
            kept.append(item)
            continue

        # No exchange prefix. A bare parenthesised ticker that is not this one,
        # with nothing local named anywhere, is another listing - "(MRVGF)".
        # Years are excluded by requiring letters, so "(FY 2026)" cannot match.
        bare = [t for t in _BARE_TICKER.findall(title) if t != expected]
        # WORD boundaries, not substring. "RIO" appears inside "RIO TINTO", so a
        # substring test kept "Rio Tinto Ltd (RTNTF)" - the US over-the-counter
        # line - for RIO.AX. Found by measuring the live feed, not by review.
        names_local = re.search(rf"{re.escape(root)}", title.upper()) is not None
        if bare and root not in set(bare) and not names_local:
            continue
        kept.append(item)
    return kept


# --- the source ------------------------------------------------------------


class NewsSource(Protocol):
    """Company news for one symbol. Returns [] on any failure, never raises."""

    def fetch(self, symbol: str, count: int = 10) -> list[NewsItem]: ...


class NullNewsSource:
    """The default. No news is a supported state, not a degraded one - the
    application ran without any news source at all until M115."""

    def fetch(self, symbol: str, count: int = 10) -> list[NewsItem]:
        return []


class YFinanceNewsSource:
    """Yahoo company news, free and needing no key.

    A DIFFERENT endpoint from the chart API - `/xhr/ncp` rather than the quote
    and history calls - which is why it returned results on 20 August while
    chart requests were rate-limited. That is convenient and not a guarantee:
    it is the same vendor and the same goodwill.

    Every failure degrades to no news. A feed of third-party text must never be
    able to stop a trading session starting, which is the promise
    `YFinanceEarningsCalendar` already makes for the same reason.
    """

    def __init__(self, ticker_factory: object | None = None) -> None:
        self._ticker_factory = ticker_factory

    def _factory(self) -> object:
        if self._ticker_factory is not None:
            return self._ticker_factory
        import yfinance  # type: ignore[import-untyped]  # lazy: importable offline

        return yfinance.Ticker

    def fetch(self, symbol: str, count: int = 10) -> list[NewsItem]:
        try:
            raw = self._factory()(symbol).get_news(count=count)  # type: ignore[operator]
        except Exception:  # noqa: BLE001 - a news feed cannot break a session
            logger.warning("Could not fetch news for %s - continuing without it", symbol)
            return []

        items = []
        for entry in raw or []:
            content = entry.get("content", entry) if isinstance(entry, dict) else {}
            if not isinstance(content, dict):
                continue
            title = str(content.get("title") or "").strip()
            provider = content.get("provider")
            name = ""
            if isinstance(provider, dict):
                name = str(provider.get("displayName") or "").strip()
            elif provider:
                name = str(provider).strip()
            published = _parse_published(content.get("pubDate"))
            if not title or not name or published is None:
                continue
            url = ""
            canonical = content.get("canonicalUrl")
            if isinstance(canonical, dict):
                url = str(canonical.get("url") or "")
            items.append(
                NewsItem(symbol=symbol, title=title, provider=name, published=published, url=url)
            )
        return items


def _parse_published(value: object) -> datetime | None:
    """The vendor's timestamp, or None when it cannot be read.

    None is not a small loss: without a date an item cannot be age-checked, and
    age is the only defence against the vendor's ordering not being recency -
    a December 2025 story sat in a "latest news" list on 20 August.
    """
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    if isinstance(value, int | float) and value > 0:
        return datetime.fromtimestamp(float(value), tz=UTC)
    return None
