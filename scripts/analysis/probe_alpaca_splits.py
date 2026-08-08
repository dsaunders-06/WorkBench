"""Read-only probe, second pass. Places no orders, changes nothing.

Answers what pass one raised:
  a) Can announcements be filtered by symbol server-side? (pass one returned
     1,639 records over a year, which would be unusable unfiltered.)
  b) How reliably is `target_symbol` populated? Two of the first three records
     had none, and symbol is what any detector would match on.
  c) Has this paper account ever processed a corporate action? alpaca-py's
     TradingClient wraps no activities method, so ask the REST endpoint.
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import date, timedelta

import requests

sys.path.insert(0, r"C:\Claude Programming\src")

from alpaca.trading.client import TradingClient  # noqa: E402
from alpaca.trading.enums import CorporateActionType  # noqa: E402
from alpaca.trading.requests import GetCorporateAnnouncementsRequest  # noqa: E402

from qat.data.broker.alpaca_adapter import (  # noqa: E402
    API_KEY_SECRET_NAME,
    SECRET_KEY_SECRET_NAME,
)
from qat.security import get_secret  # noqa: E402

KEY = get_secret(API_KEY_SECRET_NAME)
SECRET = get_secret(SECRET_KEY_SECRET_NAME)
HELD = ["AMAT", "AMD", "CRWD", "CSCO", "GS", "JNJ", "MS", "UNP", "VRTX", "WFC"]

client = TradingClient(api_key=KEY, secret_key=SECRET, paper=True)
today = date.today()

print("=" * 72)
print("a) SERVER-SIDE SYMBOL FILTER, over the last 88 days")
print("=" * 72)
for symbol in HELD:
    try:
        anns = client.get_corporate_announcements(
            GetCorporateAnnouncementsRequest(
                ca_types=[CorporateActionType.SPLIT],
                since=today - timedelta(days=88),
                until=today,
                symbol=symbol,
            )
        )
        print(f"  {symbol:<6} {len(anns)} split announcement(s)")
    except Exception as exc:  # noqa: BLE001 - a probe reports its failures
        print(f"  {symbol:<6} QUERY FAILED - {type(exc).__name__}: {exc}")

print()
print("=" * 72)
print("b) IS target_symbol RELIABLE? 88-day market-wide sample")
print("=" * 72)
anns = client.get_corporate_announcements(
    GetCorporateAnnouncementsRequest(
        ca_types=[CorporateActionType.SPLIT],
        since=today - timedelta(days=88),
        until=today,
    )
)
sub_types: Counter[str] = Counter()
missing_target = Counter()
forward_examples = []
for ann in anns:
    sub = getattr(ann.ca_sub_type, "value", str(ann.ca_sub_type))
    sub_types[sub] += 1
    if not getattr(ann, "target_symbol", None):
        missing_target[sub] += 1
    old, new = float(ann.old_rate), float(ann.new_rate)
    if new > old and getattr(ann, "target_symbol", None) and len(forward_examples) < 3:
        forward_examples.append(ann)

print(f"  {len(anns)} records. By sub-type, with how many lack target_symbol:\n")
for sub, count in sub_types.most_common():
    print(f"      {sub:<18} {count:>4}   missing target_symbol: {missing_target[sub]:>4}")

print(f"\n  FORWARD splits (new_rate > old_rate) with a symbol: {len(forward_examples)} shown\n")
for ann in forward_examples:
    print(
        f"      {ann.target_symbol:<8} old_rate={float(ann.old_rate):g} "
        f"new_rate={float(ann.new_rate):g}  ratio={float(ann.new_rate)/float(ann.old_rate):g}"
        f"  ex={ann.ex_date}  payable={ann.payable_date}"
    )

print()
print("=" * 72)
print("c) ACCOUNT ACTIVITIES via REST - has paper ever processed one?")
print("=" * 72)
headers = {"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SECRET}
for activity in ("SPLIT", "MA", "NC", "SPIN", "REORG", "DIV", "FILL"):
    try:
        resp = requests.get(
            f"https://paper-api.alpaca.markets/v2/account/activities/{activity}",
            headers=headers,
            timeout=30,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  {activity:<6} REQUEST FAILED - {type(exc).__name__}: {exc}")
        continue
    if resp.status_code != 200:
        print(f"  {activity:<6} HTTP {resp.status_code}: {resp.text[:120]}")
        continue
    rows = resp.json()
    print(f"  {activity:<6} HTTP 200, {len(rows)} row(s)")
    for row in rows[:2]:
        print(f"         {row}")
