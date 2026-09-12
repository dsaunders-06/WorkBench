# The share-trading program: where it stands, in plain English

*Written 12 September 2026. It describes the version of the program installed
that morning.*

## What it is

The Quant Advisory Terminal is a program that runs on a Windows computer. It
buys and sells shares in large Australian companies on the stock exchange. It
trades through Interactive Brokers, a real broker, but in the broker's practice
account. The money is pretend: about one million dollars of it. Nothing it does
can cost anyone real money.

The long-term aim is simple to say and hard to do. The owner wants a program
that can trade shares by a fixed set of rules and make money after paying the
broker's fees. It also has to prove that on its own track record before anyone
trusts it with real savings.

## What it does now

**It watches the market.** Every minute it checks the prices of 100 large
Australian shares, such as BHP, the big banks and Woolworths. The prices come
from a free service that runs about 20 minutes behind the market.

**It reads the mood of the market.** Each day it looks at how shares have moved,
how jumpy prices are and a few wider money measures. From those it decides
whether the market looks calm, rising, falling or nervous. When the market looks
risky, it buys smaller amounts.

**It follows one set of buying rules.** The program knows fifteen different
rule sets, but the owner has switched on only one. That one waits for a share
that is climbing to dip for a few days, then buys when the dip looks over. The
rules are written down and fixed. The program does not invent new ones or
tweak its own settings.

**It says no far more often than yes.** Before every purchase it runs a long
list of checks:

- No single purchase may risk losing more than 1% of the account.
- All the shares held together may not risk more than 5%.
- It will not put too much into one company, one industry, or a group of
  shares that tend to move together.
- It never borrows money to buy shares, and it always keeps some cash back.
- It skips a trade if the broker's fees would eat too much of the likely gain.
- It buys only half as much if a company is about to report its profits, since
  share prices can jump either way on those days.

On Friday 11 September it looked at 449 possible purchases and turned down
every one. The reason is below.

**It protects every purchase.** Each time it buys, it also leaves two
instructions with the broker. One says "sell if the price falls to here". The
other says "sell if the price rises to here". Those instructions stay with the
broker, so they work even if the computer is switched off. On Friday one of
them fired: BHP fell at the opening bell and the broker sold it
straight away, as planned. The program noticed the sale a few minutes later and
recorded it correctly.

**It checks itself.** It keeps comparing what it thinks it owns with what the
broker says it owns. If the two ever disagree, it stops all trading until a
person looks. That alarm has caught real problems more than once.

**It writes everything down.** Every purchase, every sale, every refusal and
the reason for it goes into a file. The owner can go back and see why the
program did what it did.

**It has a helper that explains things.** A small AI program on the same
computer can describe what the market is doing in ordinary words. The helper
can only talk. It has no way to buy or sell anything.

## How it has done so far

The program started trading Australian shares on 24 August. Since then it has
finished eight trades. Two made money and six lost money. Together they are
down about $3,500 on the pretend million, after fees of about $700.

Eight trades tell you very little. A coin tossed eight times can easily land
heads six times. The owner set the bar at 30 finished trades before anyone reads
the results as meaningful. The program sits a long way short of that.

At the moment it holds shares in nine companies, and every holding has its
"sell if it falls" instruction in place with the broker.

## Why it has stopped buying

The program adds up how much it would lose if every share it holds fell to its
"sell" price at the same time. On Friday that came to about 7.6% of the account.
The owner's limit is 5%. Until some of those nine holdings are sold and the
total drops under 5%, the program will not buy anything new. That limit works as
designed. It also means no new trades are finishing, so the track record has
stopped growing.

## What still needs doing

**Get it trading again.** The owner needs to decide whether to wait for the
current holdings to sell on their own, or to change the limits.

**Build a proper track record.** It needs 20 finished trades before it starts
sizing purchases from its own results instead of starting guesses. At 30,
someone can judge whether the rules make money after fees.

**Watch a few things happen for the first time.** Some safety features have
passed every test on the computer but haven't yet run for real. One example is
the program selling a share on its own decision, rather than the broker's
"sell if it falls" instruction doing it. Another is a new check, installed
today, that compares the fee the broker charged with the fee the program
expected.

**Close the gaps that could hurt with real money:**

- *Trading halts.* Sometimes the exchange stops trading in a company. The
  program can't tell yet, and a share you can't sell can't be protected.
- *Share splits.* When a company changes its number of shares, the price jumps.
  The broker doesn't send warnings about these, so the program can't see one
  coming.
- *Profit announcements.* The program buys less before one, but nobody has
  decided whether it should sell before the announcement or hold on.
- *Buying and selling well.* It buys and sells at whatever price the market
  offers at that moment. Once, a share fell straight past the "sell" price and
  the loss came out larger than planned. The program records the difference on
  every trade, but nobody has studied those figures yet.
- *Australian information.* Its reading of the market mood leans on American
  figures, because timely Australian ones are hard to get.

**Only after all that, real money.** The plan is to open the locks one at a
time. At first a person would approve every single order by hand. Today real
trading can't happen by accident: turning it on needs a change to the program
itself, not just a setting.

## In one paragraph

The program's safety machinery works, and it has been tested against a real
broker with pretend money. It protects what it buys, notices when things go
wrong, and keeps honest records. What it hasn't done yet is show that its
buying rules make money. It has only eight finished trades, and it can't add
more until the shares it holds are sold. Until it reaches 30 trades and passes
its own test, nobody should trust it with real money.
