"""IBKR company news, mapped to PUBLISHERS rather than channels.

⚠️ THE WHOLE POINT OF THIS MODULE IS THE MAPPING. IBKR bills eight subscribed
provider CODES on this account, and they are two PUBLISHERS:

    BRFG, BRFUPDN                                  -> Briefing.com
    DJ-N, DJ-RTA, DJ-RTE, DJ-RTG, DJ-RTPRO, DJNL   -> Dow Jones

`news.corroborate` counts distinct outlets, so handing it raw codes would make
`DJ-N` and `DJ-RTA` two outlets for ONE wire story. Measured 4 September:
"Albermarle Hires BHP's Ragnar Udd as President, CEO" came back under both codes
on the same day.

That matters more than it sounds. `news_min_sources` was loosened from 2 to 1 on
21 August because nothing could corroborate a lone Yahoo story; restoring 2 on
top of code-counting would report corroboration for a single Dow Jones story - a
rule that LOOKS restored while being weaker than the one it replaced, because it
passes while claiming two independent outlets. Mapping here keeps `news.py`
vendor-agnostic and makes the count honest by construction.

⚠️ THE 21 AUGUST FINDING THIS CORRECTS. `config.py` recorded "IBKR measured ZERO
headlines for RIO.AX and NHF.AX over 90 days" and that drove the loosening. The
query had been sent with no provider codes, which cannot return anything. With
codes supplied, both symbols return headlines - including NHF.AX, the symbol the
two-source rule was abandoned over.

⚠️⚠️ **NOT REPRODUCIBLE ON 10 SEPTEMBER 2026 - DO NOT BUILD ON THE PARAGRAPH
ABOVE WITHOUT RE-MEASURING.** Same symbols, same 90 days, all eight codes
supplied, both `readonly=True` and `readonly=False`: **zero headlines.** And the
POSITIVE CONTROL is what makes that meaningful - AAPL and MSFT over 30 days also
returned zero, which is not credible as a true absence for US megacaps on a Dow
Jones wire. Streaming news ticks (`mdoff,292`) returned zero for BHP.AX and AAPL
alike. `reqNewsProviders` still lists all eight, and all eight are ticked in the
Gateway's API news configuration, so the ACCOUNT subscribes and the GATEWAY
permits - the retrieval path is what answers nothing.

Leading hypothesis, unproven: IBKR news does not reach PAPER accounts over the
API (`DUQ200898` is paper, and `Error 10276: News feed is not allowed` is the
canonical response). Settling it needs a live account, which was not tested.
See the 10 September section of docs/HANDOFF.md for the full measurement.

⚠️ NOT WIRED IN BY DEFAULT, AND DELIBERATELY. Dow Jones terms generally forbid
storing and redistributing headlines, and this application writes them into the
decision journal. Settle that against the actual subscription before adding
"ibkr" to `Settings.news_source`.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from qat.data.news import NewsItem

logger = logging.getLogger(__name__)

# Code -> publisher. The channel is how IBKR bills it; the publisher is who
# wrote it, and only the second is an outlet for corroboration purposes.
_PUBLISHERS = {
    "BRFG": "Briefing.com",
    "BRFUPDN": "Briefing.com",
    "DJ-N": "Dow Jones",
    "DJ-RTA": "Dow Jones",
    "DJ-RTE": "Dow Jones",
    "DJ-RTG": "Dow Jones",
    "DJ-RTPRO": "Dow Jones",
    "DJNL": "Dow Jones",
}

# IBKR wraps headlines: `{A:800015,800008:L:en,Chinese (...)}Real headline`.
# Left in, it reaches the model as text AND defeats title clustering, because
# two reports of one story carry different prefixes.
_METADATA_PREFIX = re.compile(r"^\{[^}]*\}")


def publisher_for(code: str) -> str:
    """The publisher behind an IBKR provider code.

    ⚠️ An unmapped code is RETURNED AS ITSELF rather than guessed at. A new
    provider must not silently collapse into an existing publisher - that would
    quietly merge two real outlets into one and suppress genuine corroboration.
    Standing alone, it counts as its own outlet, which is the strict direction
    until someone maps it deliberately.
    """
    return _PUBLISHERS.get(code.strip().upper(), code.strip())


class IBKRNewsSource:
    """A `news.NewsSource` over IBKR's historical news.

    Every failure degrades to no news: a feed of third-party text must never be
    able to stop a trading session, the promise `YFinanceNewsSource` and
    `YFinanceEarningsCalendar` already make.
    """

    def __init__(self, adapter: object | None = None) -> None:
        self._adapter = adapter

    @staticmethod
    def to_item(symbol: str, headline: str, code: str, published: datetime) -> NewsItem:
        """One IBKR headline as a `NewsItem`, with the publisher resolved.

        ⚠️ `primary` is never set. It means the COMPANY lodged the item with the
        exchange, and a wire service is reliable but still secondary - it
        reports on the news rather than being it. Marking one primary would let
        a single story bypass the two-source bar through the filing exception.
        """
        return NewsItem(
            symbol=symbol,
            title=_METADATA_PREFIX.sub("", headline).strip(),
            provider=publisher_for(code),
            published=(
                published.astimezone(UTC) if published.tzinfo else published.replace(tzinfo=UTC)
            ),
            primary=False,
        )

    def fetch(self, symbol: str, count: int = 10) -> list[NewsItem]:
        raise NotImplementedError(
            "IBKRNewsSource.fetch is not wired up: the Dow Jones storage licence "
            "is unresolved and this app writes headlines into the decision journal. "
            "publisher_for and to_item are usable and tested meanwhile."
        )
