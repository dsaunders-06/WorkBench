"""M115: mapping the vendor's news payload, defensively.

The shape below is the one Yahoo actually returned on 20 August 2026 - a
`content` envelope with `title`, `pubDate` and a nested `provider.displayName`.
It is unofficial and undocumented, so every field is treated as optional and a
malformed item is skipped rather than raised on: a news feed must never be able
to stop a trading session starting.
"""

from __future__ import annotations

from datetime import UTC, datetime

from qat.data.news import YFinanceNewsSource


class _Fake:
    """Stands in for yfinance.Ticker, whose real call needs the network."""

    def __init__(self, payload: list[dict] | Exception) -> None:
        self.payload = payload

    def __call__(self, symbol: str) -> _Fake:
        return self

    def get_news(self, count: int = 10, tab: str = "news") -> list[dict]:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


_LIVE_SHAPE = [
    {
        "content": {
            "title": "Mirvac Group (ASX:MGR) (FY 2026) Earnings Call Highlights",
            "pubDate": "2026-08-19T09:01:46Z",
            "provider": {"displayName": "GuruFocus.com"},
            "canonicalUrl": {"url": "https://example.invalid/a"},
        }
    }
]


def test_the_live_payload_shape_maps_to_a_news_item() -> None:
    source = YFinanceNewsSource(ticker_factory=_Fake(_LIVE_SHAPE))

    items = source.fetch("MGR.AX")

    assert len(items) == 1
    item = items[0]
    assert item.symbol == "MGR.AX"
    assert item.title.startswith("Mirvac Group (ASX:MGR)")
    assert item.provider == "GuruFocus.com"
    assert item.published == datetime(2026, 8, 19, 9, 1, 46, tzinfo=UTC)
    assert item.url == "https://example.invalid/a"


def test_an_item_with_no_date_is_skipped() -> None:
    """Without a timestamp it cannot be age-checked, and age is the only defence
    against the vendor's ordering not being recency."""
    source = YFinanceNewsSource(
        ticker_factory=_Fake([{"content": {"title": "x", "provider": {"displayName": "R"}}}])
    )

    assert source.fetch("MGR.AX") == []


def test_a_malformed_item_is_skipped_and_the_good_ones_survive() -> None:
    source = YFinanceNewsSource(ticker_factory=_Fake([{"garbage": True}, *_LIVE_SHAPE]))

    assert len(source.fetch("MGR.AX")) == 1


def test_a_vendor_failure_degrades_to_no_news_and_never_raises() -> None:
    """A news feed must not be able to stop a session. The earnings calendar
    makes the same promise for the same reason."""
    source = YFinanceNewsSource(ticker_factory=_Fake(RuntimeError("rate limited")))

    assert source.fetch("MGR.AX") == []


def test_the_null_source_is_the_default_and_returns_nothing() -> None:
    from qat.data.news import NullNewsSource

    assert NullNewsSource().fetch("MGR.AX") == []
