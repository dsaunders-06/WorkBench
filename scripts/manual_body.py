"""Prose and tables for the user manual; see scripts/build_manual.py.

Split out purely for length. The rule for everything here: if a sentence makes
a claim about behaviour, that behaviour is in the code and the claim names it
concretely enough to be checked. A manual that describes an intention rather
than the build is worse than no manual, because it is trusted.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

if TYPE_CHECKING:  # pragma: no cover - typing only
    from scripts.build_manual import FigureSet

VERSION_LINE = "Version 3.0  |  Milestone M37"
FIGURE_WIDTH = Inches(6.2)
ACCENT = RGBColor(0x1B, 0x3A, 0x5F)
CAPTION_GREY = RGBColor(0x55, 0x5F, 0x6D)
WARNING_RED = RGBColor(0xB7, 0x1C, 0x1C)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def style_document(doc: Any) -> None:
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    for level, size in ((1, 18), (2, 13), (3, 11.5)):
        style = doc.styles[f"Heading {level}"]
        style.font.size = Pt(size)
        style.font.color.rgb = ACCENT
        style.font.name = "Calibri"


def _callout(doc: Any, title: str, body: str, *, danger: bool = False) -> None:
    table = doc.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    cell = table.rows[0].cells[0]
    run = cell.paragraphs[0].add_run(title)
    run.bold = True
    run.font.color.rgb = WARNING_RED if danger else ACCENT
    cell.add_paragraph(body)
    doc.add_paragraph()


def _table(doc: Any, headers: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Light Grid Accent 1"
    for index, header in enumerate(headers):
        cell = table.rows[0].cells[index]
        cell.text = ""
        cell.paragraphs[0].add_run(header).bold = True
    for row in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            cells[index].text = value
    doc.add_paragraph()


def _figure(doc: Any, figures: FigureSet, key: str) -> None:
    figure = figures[key]
    doc.add_picture(str(figure.path), width=FIGURE_WIDTH)
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption = doc.add_paragraph()
    caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = caption.add_run(figure.caption)
    run.italic = True
    run.font.size = Pt(9)
    run.font.color.rgb = CAPTION_GREY


def _toc_field(doc: Any) -> None:
    """A real Word TOC field rather than a hand-typed list.

    A typed contents list with hand-written page numbers goes stale the moment
    a paragraph is added, and nothing warns you. Word populates this on open
    (or on F9), so it is either correct or visibly unpopulated - never
    confidently wrong.
    """
    paragraph = doc.add_paragraph()
    run = paragraph.add_run()

    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = r'TOC \o "1-2" \h \z \u'
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    placeholder = OxmlElement("w:t")
    placeholder.text = "Right-click here and choose 'Update Field' to build the contents."
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")

    for element in (begin, instr, separate, placeholder, end):
        run._r.append(element)


def title_page(doc: Any) -> None:
    for text, size, bold in (("QUANT ADVISORY TERMINAL", 30, True), ("User Manual", 20, False)):
        para = doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = para.add_run(text)
        run.bold = bold
        run.font.size = Pt(size)
        run.font.color.rgb = ACCENT

    for text in (
        "AI-Assisted, Multi-Strategy Share-Trading Advisory & Paper-Trading Desktop " "Application",
        VERSION_LINE,
        datetime.now().strftime("%Y-%m-%d"),
    ):
        para = doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.add_run(text).font.size = Pt(11)

    doc.add_paragraph()
    _callout(
        doc,
        "SAFETY NOTICE",
        "This application defaults to Paper Trading mode, and in its default configuration "
        "it cannot place, modify or cancel an order without an explicit, human-attributed "
        "sign-off. It also ships an optional auto-trade mode that removes the per-order "
        "confirmation on paper accounts only; that mode is off by default, and switching it "
        "on requires a separate confirmation dialog. This is educational and research "
        "software. Nothing it displays is investment advice. Read Section 12, Safety "
        "Architecture Reference, before enabling anything beyond the defaults.",
        danger=True,
    )
    doc.add_page_break()

    doc.add_heading("Contents", level=1)
    _toc_field(doc)
    doc.add_page_break()


# ---------------------------------------------------------------------------
# Body
# ---------------------------------------------------------------------------


def write_body(doc: Any, figures: FigureSet) -> None:
    _introduction(doc)
    _getting_started(doc, figures)
    _dashboard(doc, figures)
    _market_session(doc)
    _balances(doc)
    _adopted_positions(doc)
    _workbench(doc, figures)
    _walk_forward(doc)
    _regime_monitor(doc, figures)
    _risk_console(doc, figures)
    _ai_advisor(doc, figures)
    _blotter(doc, figures)
    _position_protection(doc)
    _screener(doc, figures)
    _performance(doc, figures)
    _session_record(doc)
    _metrics_panel(doc)
    _settings(doc, figures)
    _interface_level(doc)
    _storage_location(doc)
    _safety(doc)
    _glossary(doc)
    _config_reference(doc)


def _introduction(doc: Any) -> None:
    doc.add_heading("1. Introduction", level=1)

    doc.add_heading("1.1 About This Application", level=2)
    doc.add_paragraph(
        "Quant Advisory Terminal (QAT) is a Windows desktop application that combines market "
        "data, a market-regime detector, fifteen rules-based trading strategies, a vectorised "
        "backtester, a risk engine, a broker connection and an AI research assistant into a "
        "single advisory and paper-trading workstation. It is built around one governing "
        "principle: the software proposes, and a human disposes. No strategy, no risk "
        "calculation and no AI response can reach a broker on its own."
    )
    doc.add_paragraph(
        "The application is a single main window with a colour-coded mode banner and nine "
        "tabbed screens, every one of which reads live data from the application's internal "
        "engines. Sections 3 to 11 document them in the order they appear."
    )

    doc.add_heading("1.2 Core Safety Principles", level=2)
    doc.add_paragraph(
        "Six principles hold across every screen in this manual and are restated wherever "
        "they apply directly:"
    )
    for principle in (
        "Paper by default - the application always starts in Paper trading mode unless Live "
        "mode is configured deliberately beforehand, and the top banner makes the active "
        "mode unmistakable at all times.",
        "Human sign-off by default - a signal can become a pending order, but only an "
        "explicit, confirmed action on the Order Blotter transmits it. The optional "
        "auto-trade mode (Section 11.8) is the single deliberate exception, is confined to "
        "paper accounts, and is off unless you turn it on.",
        "An always-available kill-switch - the Risk Console exposes one control that halts "
        "all new order flow immediately, and five separate conditions can trip it "
        "automatically.",
        "Cash is never fully spent and the account is never leveraged - a buy can never "
        "exceed available cash, and never spend below your configured reserve. This is "
        "enforced twice, and cannot be switched off (Section 12.2).",
        "An AI that only advises - the AI Advisor and every AI-generated note can recommend, "
        "explain and flag risk, but have no code path to a broker. Every recommendation is "
        "independently re-checked against the Risk Engine before it is shown to you.",
        "Claims are measured, not asserted - the Performance screen reports realised results "
        "per strategy against a fixed promotion bar, so 'this strategy works' is a "
        "falsifiable statement rather than an impression.",
    ):
        doc.add_paragraph(principle, style="List Bullet")

    doc.add_heading("1.3 What Changed Since Version 1.0", level=2)
    doc.add_paragraph(
        "Version 1.0 of this manual documented milestone M9, at which six screens were live "
        "and two were placeholders. This edition covers M17. The substantive changes:"
    )
    _table(
        doc,
        ("Area", "What is new"),
        (
            (
                "Screener and Settings",
                "Both are fully built and are no longer placeholders (Sections 9 and 11).",
            ),
            (
                "Performance screen",
                "New ninth tab: realised trades, per-strategy promotion status, and "
                "generated daily and weekly reports (Section 10).",
            ),
            (
                "Real market data",
                "Prices can come from Yahoo or from your Alpaca account instead of the "
                "simulated random walk (Section 11.4).",
            ),
            (
                "Alpaca paper broker",
                "Real positions, cash and fills against your own Alpaca paper account "
                "(Section 11.3).",
            ),
            (
                "AI provider selection",
                "Anthropic, a local LM Studio server, or the built-in demo engine, "
                "selectable per request type (Section 11.1).",
            ),
            (
                "Real company fundamentals",
                "Reported EPS growth, PEG, ROE and dividend figures instead of generated "
                "ones, with strategies abstaining where a figure does not exist "
                "(Section 11.5).",
            ),
            (
                "Cash and no-leverage rule",
                "A hard limit no configuration can disable (Section 12.2).",
            ),
            (
                "Optional auto-trade",
                "Per-strategy unattended execution on paper accounts, off by default and "
                "gated by an explicit confirmation (Sections 11.6 and 12.3).",
            ),
            (
                "You are told when prices stop",
                "A market-data outage now appears on the banner instead of being "
                "silent, one unknown ticker can no longer block the whole feed, and "
                "a dropped feed reconnects by itself.",
            ),
            (
                "Positions you did not open",
                "The Dashboard now says when holdings that were already in the account "
                "are consuming the risk budget, and what to do about it (Section 3.4).",
            ),
            (
                "A halt you cannot miss",
                "Every kill-switch trip and reset now changes the execution banner on "
                "every screen and writes a line to the log, whichever path tripped it "
                "(Section 6).",
            ),
            (
                "Metrics tab",
                "Expectancy, average win against average loss, holding period, exposure, "
                "trade frequency and recovery factor on the Performance screen and in "
                "the reports (Section 10.5).",
            ),
            (
                "Stable storage location",
                "Settings and records live in one per-user directory instead of beside "
                "whatever folder the application was launched from, and are migrated "
                "there on first run (Section 11.10).",
            ),
            (
                "Balances panel",
                "The Dashboard leads with the broker's own balance sheet, and account "
                "reads are shared and throttled to respect the broker's rate limit "
                "(Section 3.3).",
            ),
            (
                "Market session panel",
                "The Dashboard shows which market is in play with countdowns to the open "
                "and close, and the application now follows market hours (Section 3.2).",
            ),
            (
                "Walk-forward analysis",
                "Out-of-sample evaluation across rolling windows on the Workbench "
                "(Section 4.2).",
            ),
            (
                "Session record",
                "An application log file, a decision journal covering every execution mode, "
                "a persisted risk audit trail, and a one-click session export "
                "(Section 10.4).",
            ),
            (
                "Order Blotter rework",
                "Status filtering, multi-row selection and bulk sign-off, so a long order "
                "history stays workable (Section 8).",
            ),
            (
                "Signed executable",
                "The packaged build is now Authenticode-signed and timestamped " "(Section 12.6).",
            ),
        ),
    )

    doc.add_heading("1.4 System Requirements and Installation", level=2)
    doc.add_paragraph(
        "QAT targets Windows. The packaged executable needs no Python installation; running "
        "from source requires Python 3.12."
    )
    _table(
        doc,
        ("Topic", "Details"),
        (
            (
                "Running the packaged build",
                "Unzip the distribution and run QuantAdvisoryTerminal\\"
                "QuantAdvisoryTerminal.exe. Everything it needs is inside the folder.",
            ),
            (
                "Running from source",
                'python -m venv .venv, then pip install -e ".[dev]", then invoke run. '
                "invoke package rebuilds the executable.",
            ),
            (
                "Defaults on first launch",
                "Paper mode, the built-in simulated broker, simulated prices, the demo AI "
                "engine, and human sign-off on every order. The application is fully "
                "usable with no keys, no accounts and no network.",
            ),
            (
                "Optional integrations",
                "Interactive Brokers via Gateway or TWS (the ASX configuration), Alpaca "
                "(paper broker and US market data), Anthropic's API, a local LM Studio "
                "server, and FRED for macro series.",
            ),
            (
                "Where configuration lives",
                "One per-user directory - %LOCALAPPDATA%\\QuantAdvisoryTerminal - holding a "
                ".env of non-secret settings and a data folder of records. API keys are never "
                "in either: they live only in the Windows Credential Manager. The Settings "
                "screen names the directory. See Section 11.10.",
            ),
        ),
    )


def _getting_started(doc: Any, figures: FigureSet) -> None:
    doc.add_page_break()
    doc.add_heading("2. Getting Started", level=1)

    doc.add_heading("2.1 Launching the Application", level=2)
    doc.add_paragraph(
        "Start the application by running QuantAdvisoryTerminal.exe, or with invoke run from "
        "a source checkout. The main window opens on the Dashboard tab and every engine "
        "starts immediately."
    )

    doc.add_heading("2.2 The Main Window", level=2)
    doc.add_paragraph(
        "Every screen shares the same frame: a mode banner fixed to the top of the window "
        "and a row of nine tabs beneath it. Switching tabs interrupts nothing - all engines "
        "keep running and every screen keeps updating whether or not it is visible."
    )
    _table(
        doc,
        ("#", "Tab", "Purpose"),
        (
            (
                "1",
                "Dashboard",
                "Portfolio overview: NAV, headline risk figures, equity curve, positions "
                "and the current regime note.",
            ),
            (
                "2",
                "Strategy Workbench",
                "Backtest a strategy and, once vetted, deploy it to the live signal " "pipeline.",
            ),
            (
                "3",
                "Regime Monitor",
                "The full regime probability distribution, its drivers, and transition " "history.",
            ),
            ("4", "Risk Console", "Live risk tiles, the correlation table, and the kill-switch."),
            ("5", "AI Advisor", "Free-text research questions against the AI advisory service."),
            ("6", "Order Blotter", "Every order the system knows about, and the sign-off gate."),
            (
                "7",
                "Screener",
                "Fundamental and technical screening of the candidate universe.",
            ),
            (
                "8",
                "Performance",
                "Realised results, per-strategy promotion status, and generated reports.",
            ),
            (
                "9",
                "Settings",
                "AI provider, market and watchlist, broker and cash, market data source, "
                "and execution mode.",
            ),
        ),
    )

    doc.add_heading("2.3 Paper versus Live Mode", level=2)
    doc.add_paragraph(
        "The banner across the top of the window is the most important safety indicator in "
        "the application. It is always visible, cannot be hidden, and its colour carries the "
        "meaning: solid green reads MODE: PAPER, solid red reads MODE: LIVE. The Order "
        "Blotter repeats the same banner directly above its order table, because that is the "
        "screen where the distinction matters at the moment of action."
    )
    _figure(doc, figures, "banner_paper")
    _figure(doc, figures, "banner_live")

    doc.add_heading("2.4 Recommended First-Run Sequence", level=2)
    doc.add_paragraph(
        "The defaults are safe but deliberately inert - simulated prices against a simulated "
        "broker. To reach something meaningful, work through Settings in this order, "
        "restarting once at the end:"
    )
    for step in (
        "Settings > Broker & Cash: choose your broker and enter its keys, then use Test "
        "Broker Connection to confirm the account it reads is the one you expect.",
        "Settings > Market Data: switch the price source off Simulated. Auto-trading against "
        "simulated prices is a loop that trades noise.",
        "Settings > AI Provider: pick a provider per request type and use Test Connection. "
        "The demo engine always answers 'hold' with zero confidence; it is a placeholder, "
        "not an analyst.",
        "Settings > Market & Watchlist: set the market and the symbols to follow.",
        "Restart the application. Every setting on this screen is applied at startup.",
        "Strategy Workbench: backtest before deploying anything. No strategy is active on "
        "launch.",
        "Order Blotter: review and sign off the first orders by hand, whatever you intend to "
        "do later.",
    ):
        doc.add_paragraph(step, style="List Number")


def _dashboard(doc: Any, figures: FigureSet) -> None:
    doc.add_page_break()
    doc.add_heading("3. The Dashboard", level=1)
    doc.add_paragraph(
        "The Dashboard is the home screen and default landing tab: account value, headline "
        "risk and performance figures, an equity curve, current holdings, and a "
        "plain-language note on the current market regime. Figures refresh every two "
        "seconds; the AI regime note refreshes whenever the Regime Engine detects a change."
    )
    _figure(doc, figures, "dashboard")

    doc.add_heading("3.1 Screen Elements", level=2)
    _table(
        doc,
        ("Element", "Description"),
        (
            (
                "Market session panel",
                "Which market is in play, a countdown to the next open or to the close, and "
                "whether the trading session is running. The countdown turns amber inside 30 "
                "minutes of an open or a close. Holidays and early closes are named. See "
                "Section 3.2.",
            ),
            (
                "Regime header",
                "The current regime label and its exposure scalar - the portfolio-wide "
                "position-sizing multiplier the regime implies.",
            ),
            (
                "Balances panel",
                "The broker's own balance sheet: portfolio value, today's P/L, cash, "
                "buying power, market values, margin, day-trade count and account "
                "status. See Section 3.3.",
            ),
            (
                "Portfolio VaR (95%) tile",
                "One-period, 95%-confidence historical Value-at-Risk across the current "
                "portfolio.",
            ),
            (
                "Realised Sharpe (naive) tile",
                "An annualised Sharpe ratio from the live NAV history sampled every two "
                "seconds. Naive because that sampling is not a daily return series; treat "
                "it as a direction, not a measurement.",
            ),
            (
                "Drawdown vs limit tile",
                "Current drawdown from the highest NAV observed this session, against the "
                "configured maximum-drawdown limit that trips the kill-switch.",
            ),
            (
                "Equity Curve chart",
                "A live line chart of NAV over time, up to the most recent 500 samples.",
            ),
            (
                "Positions table",
                "Every open position reported by the broker: symbol, quantity and average "
                "price.",
            ),
            (
                "AI Regime Note",
                "A plain-language summary generated whenever the regime changes. If the "
                "AI provider fails, the error is shown here rather than silently leaving "
                "a stale note in place.",
            ),
            (
                "Review & Apply button",
                "Acknowledges that you have read the note. It is a user-interface action "
                "only: it changes no position, no order and no setting.",
            ),
        ),
    )


def _market_session(doc: Any) -> None:
    doc.add_heading("3.2 The Market Session Panel", level=2)
    doc.add_paragraph(
        "The panel at the top of the Dashboard answers three questions at a glance: which "
        "market is in play, how long until it opens or closes, and whether the application "
        "is actually trading."
    )
    _table(
        doc,
        ("Element", "Description"),
        (
            (
                "Market headline",
                "The configured market and its state, shown as a filled green banner while "
                "the market is open and amber when an open or close is imminent, so the "
                "state reads at a glance. A closure with a reason - a public "
                "holiday, a weekend - is named rather than left as a bare 'closed'.",
            ),
            (
                "Countdown",
                "Time to the close while open, or to the next open while shut, as HH:MM:SS. "
                "It turns amber inside 30 minutes of either, and an early close is labelled.",
            ),
            (
                "Second market line",
                "Appears only when the other market is trading - both can be open at once, "
                "and a permanent 'ASX closed' row would be noise.",
            ),
            (
                "Session status",
                "Whether the feed and strategies are live, standing by, or always on.",
            ),
            (
                "Start session now",
                "Runs the session against a closed market until the next close. Shown only "
                "when it would do something.",
            ),
        ),
    )
    _callout(
        doc,
        "What starting a session does and does not do",
        "Starting a session starts the market data feed and lets deployed strategies emit "
        "signals. It does not place an order, and it does not change who approves one: "
        "execution mode, the risk engine, the cash rule and the sign-off gate all behave "
        "exactly as configured. Outside market hours the application stands the feed down "
        "and stops emitting signals, because a signal computed at 3am from the previous "
        "day's closing price is not analysis - and because a closed market would otherwise "
        "trip the data-staleness rail within a minute of every close.",
    )


def _balances(doc: Any) -> None:
    doc.add_heading("3.3 The Balances Panel", level=2)
    doc.add_paragraph(
        "The panel is laid out like the broker's own balances page, and for the most part "
        "it simply repeats what the broker says. Today's profit is the broker's equity "
        "against its own previous close, not a figure computed here - when two screens "
        "disagree about money, you have to work out which one is lying, and that is a worse "
        "position than one number with a caveat."
    )
    _table(
        doc,
        ("Figure", "Meaning"),
        (
            ("Portfolio value", "Equity: cash plus the market value of open positions."),
            (
                "Today's P/L",
                "Equity against the previous close, in cash and percent, coloured by sign.",
            ),
            ("Cash", "Settled cash held at the broker."),
            (
                "Spendable here",
                "Cash less your minimum reserve - what this application will actually let a "
                "buy spend. See the note below.",
            ),
            (
                "Broker buying power",
                "What the broker would allow, including margin, with the multiplier in "
                "brackets.",
            ),
            ("Long / short market value", "Market value of long and short positions."),
            (
                "Initial / maintenance margin",
                "Margin required to open and to keep the current positions.",
            ),
            (
                "Day trades (5d)",
                "Day-trade count, with a PDT marker when the pattern-day-trader flag is set.",
            ),
            ("Account", "Broker account status, or BLOCKED if trading is restricted."),
        ),
    )
    _callout(
        doc,
        "Spendable here will be far below buying power, and that is correct",
        "A margin account is typically offered four times its cash as buying power. This "
        "application uses none of it: the no-leverage rule caps a buy at cash less your "
        "reserve. On a funded paper account that can read as $365,206 of buying power beside "
        "$69,844 spendable - the two sit next to each other precisely so an order refused "
        "for insufficient cash does not come as a surprise.",
    )
    _callout(
        doc,
        "A dash means the broker did not report it",
        "Not that the value is zero. An Alpaca paper account returns nothing for the "
        "day-trade count or the pattern-day-trader flag, and showing 0 would be a quiet "
        "claim about your day-trading status rather than an absence of one. The line "
        "beneath the panel gives the age of the reading; if the broker stops answering, the "
        "last good figures stay on screen with their real timestamp and the error beside "
        "them, rather than silently ageing as though current.",
    )


def _adopted_positions(doc: Any) -> None:
    doc.add_heading("3.4 Positions You Did Not Open", level=2)
    doc.add_paragraph(
        "When the application starts it takes note of whatever the account already holds - "
        "positions from a previous session, from another program, or bought by hand. It has "
        "to: comparing an application that has traded nothing against an account that "
        "already holds shares would read a perfectly healthy account as a discrepancy and "
        "halt trading on every launch."
    )
    doc.add_paragraph(
        "Those holdings have a cost that is easy to miss. A position whose protection the "
        "application cannot see is treated as having none at all, and its whole value counts "
        "against the risk budget rather than the distance down to a stop. Seven inherited "
        "holdings in a hundred-thousand-dollar account were enough to put risk-at-stop at "
        "thirty percent against a five percent limit - which is to say every new trade was "
        "refused, all day, and nothing on screen said so."
    )
    doc.add_paragraph(
        "The panel distinguishes two situations that look identical from the outside. A "
        "holding this application opened in an EARLIER SESSION reads as 'resumed after "
        "restart': it is the normal case, since every launch re-adopts what the "
        "strategies opened before. A holding it has no record of reads as 'not opened "
        "by this app', which is the case the panel exists for. Before they were "
        "separated the panel said the second for both, and a warning that fires on every "
        "ordinary restart is one an operator learns to scroll past."
    )
    doc.add_paragraph(
        "Protection is checked against the broker rather than assumed, so a resumed position "
        "with its stop and target still resting is counted at the distance to its stop, not "
        "at full value. Section 8A covers what happens when that protection has gone."
    )
    doc.add_paragraph(
        "A panel now appears beneath the market session banner whenever this is happening. "
        "It names the holdings, largest first, and states how much of the budget they are "
        "using. Amber means they are consuming it; red means it is exhausted and nothing new "
        "is being opened. When there is nothing to report the panel is not there at all."
    )
    _callout(
        doc,
        "Two ways to clear it",
        "Attach a stop to each inherited position, which reduces its counted risk from the "
        "whole value to the distance down to the stop; or close them and let the strategies "
        "open positions the application has a full record of. Either way the panel "
        "disappears on the next refresh - it follows what you actually hold, so it can never "
        "outlive the situation it is describing. If you are starting a test and want clean "
        "figures, closing them is the better option: every performance measure keys off an "
        "entry the application recorded, and an inherited position has none.",
    )


def _workbench(doc: Any, figures: FigureSet) -> None:
    doc.add_page_break()
    doc.add_heading("4. The Strategy Workbench", level=1)
    doc.add_paragraph(
        "The Workbench is where a strategy is vetted before it is allowed to run. It "
        "backtests any of the fifteen built-in strategies, reports a full performance and "
        "risk panel, runs a Monte Carlo resample of the resulting trades, and produces an AI "
        "commentary - all before the one consequential action on the screen: deploying the "
        "strategy to the live signal pipeline."
    )
    _callout(
        doc,
        "Where the backtest data comes from",
        "Backtests use whatever price source is configured in Settings. On the default "
        "simulated source they run against a seeded random walk: reproducible run to run, "
        "but illustrative only - they say nothing about real historical performance. On a "
        "real source they use real daily bars, subject to that source's own limits "
        "(Section 11.4). The status line above the chart tells you which you are looking at.",
    )
    _figure(doc, figures, "workbench")

    doc.add_heading("4.1 Screen Elements", level=2)
    _table(
        doc,
        ("Element", "Description"),
        (
            ("Strategy dropdown", "Which of the fifteen built-in strategies to backtest."),
            ("Symbol dropdown", "Which watchlist symbol to backtest it against."),
            (
                "Run Backtest button",
                "Fetches daily history for the symbol, replays the strategy bar by bar, "
                "and populates every panel below.",
            ),
            (
                "Warnings line",
                "Guardrail warnings raised by the backtester itself - too few trades, a "
                "zero-variance return series, an implausible Sharpe. Read these before "
                "reading the metrics.",
            ),
            (
                "Equity vs Benchmark chart",
                "Yellow: the strategy's simulated equity. Cyan: buy-and-hold in the same "
                "symbol over the same window.",
            ),
            (
                "Ten-metric panel",
                "CAGR, annualised volatility, Sharpe, Sortino, maximum drawdown, Calmar, "
                "win rate, profit factor, beta and alpha.",
            ),
            (
                "Monte Carlo Outcome Cone",
                "A 1,000-simulation bootstrap resample of the backtest's own trade "
                "returns. A wide cone means the result depended heavily on trade order.",
            ),
            (
                "AI Robustness Note",
                "Commentary generated from the metrics, not from the price series. If the "
                "AI provider fails, the failure is shown here.",
            ),
            (
                "Deploy to Paper button",
                "The one real action. Enabled once a backtest has run; makes the strategy "
                "eligible to emit live signals.",
            ),
        ),
    )
    _callout(
        doc,
        "What Deploy to Paper does not do",
        "No strategy is active on launch - the live Strategy Engine starts empty. Deploying "
        "only makes a strategy eligible to generate signals. Every signal still passes "
        "through the Risk Engine's sizing and limit checks, and lands on the Order Blotter "
        "as pending sign-off. Deploying does not enable auto-trade; that is a separate "
        "setting requiring its own confirmation, and it applies only to strategies you list "
        "explicitly.",
    )


def _walk_forward(doc: Any) -> None:
    doc.add_heading("4.2 Walk-Forward Analysis", level=2)
    doc.add_paragraph(
        "The backtest above and its Monte Carlo cone share a weakness: both are computed "
        "from one pass over one period. A strategy that worked in a single favourable "
        "stretch and nowhere else looks the same as one that worked throughout. "
        "Walk-forward replays the strategy across rolling, non-overlapping out-of-sample "
        "windows and reports each separately."
    )
    _table(
        doc,
        ("Element", "Description"),
        (
            (
                "In-sample / out-of-sample bars",
                "Window sizes in daily bars, defaulting to 120 and 60 - roughly six months "
                "tested against the following three.",
            ),
            (
                "Run Walk-Forward",
                "Replays the selected strategy and symbol across every complete window.",
            ),
            (
                "Results table",
                "One row per out-of-sample window: dates, CAGR, Sharpe, maximum drawdown "
                "and trade count. Sharpe is colour-coded by sign.",
            ),
            (
                "Headline",
                "How many windows were profitable, the mean Sharpe and its spread, and a "
                "plain-language verdict.",
            ),
        ),
    )
    _callout(
        doc,
        "Why the headline leads with the window count",
        "It reports how many windows were profitable before it reports the average, because "
        "a strategy can post a strong average off one exceptional window while losing money "
        "in every other - and the average is precisely what conceals that. The panel also "
        "flags when the spread between windows exceeds the average, and refuses to draw a "
        "conclusion from fewer than three windows rather than scoring noise. A strategy "
        "that fails here should not be deployed on the strength of the backtest above.",
    )


def _regime_monitor(doc: Any, figures: FigureSet) -> None:
    doc.add_page_break()
    doc.add_heading("5. The Regime Monitor", level=1)
    doc.add_paragraph(
        "The Regime Monitor is the detail behind the short summary on the Dashboard. The "
        "application classifies the market into one of seven regimes - bull, bear, sideways, "
        "high_vol, low_vol, recession and recovery - using a Gaussian Hidden Markov Model "
        "blended with a macro and technical rules overlay, then passed through a hysteresis "
        "gate so the label does not flicker on noisy data. This screen shows the full "
        "probability distribution, the inputs driving it, and every actual regime change."
    )
    doc.add_paragraph(
        "The distribution matters more than the label, because the label is not what gates a "
        "strategy. Each strategy declares the regimes it suits, and it is permitted on the "
        "TOTAL PROBABILITY across those regimes rather than on whichever single regime "
        "happens to be most likely. A strategy suited to sideways, bull and recovery holding "
        "sixty percent of the probability between them keeps trading even when high "
        "volatility is the headline label at thirty-five percent."
    )
    doc.add_paragraph(
        "This is why a strategy can be active in a regime it does not list. Reading only the "
        "header will occasionally suggest the application is trading something it should have "
        "refused; reading the distribution shows why it did not."
    )
    _figure(doc, figures, "regime")

    doc.add_heading("5.1 Screen Elements", level=2)
    _table(
        doc,
        ("Element", "Description"),
        (
            (
                "Regime header",
                "The current label and its exposure scalar, the portfolio-wide sizing "
                "multiplier applied to every signal while the regime holds.",
            ),
            (
                "Probability bars",
                "One bar per regime. A distribution with no clear peak means the model is "
                "genuinely uncertain, which is itself information.",
            ),
            (
                "Feature drivers table",
                "The live values feeding the model: the macro series it tracks and the "
                "technical features derived from price.",
            ),
            (
                "Transition history",
                "A newest-first, timestamped log of every actual regime change. An entry "
                "appears only when the label changes after the hysteresis gate, not on "
                "every model update.",
            ),
        ),
    )


def _risk_console(doc: Any, figures: FigureSet) -> None:
    doc.add_page_break()
    doc.add_heading("6. The Risk Console", level=1)
    doc.add_paragraph(
        "The Risk Console is the control room for portfolio risk. It surfaces the same "
        "figures the Risk Engine uses to size and gate every order, shows how correlated the "
        "watchlist currently is, and hosts the kill-switch - the single control that "
        "overrides every strategy and the AI layer and halts new order flow immediately."
    )
    _figure(doc, figures, "risk_console")

    doc.add_heading("6.1 Screen Elements", level=2)
    _table(
        doc,
        ("Element", "Description"),
        (
            (
                "Kill-switch button",
                "Always visible at the top. Green when inactive, red when tripped. "
                "Tripping it halts all new order flow at once; it does not liquidate "
                "existing positions. Clicking it also changes the execution banner at "
                "the top of every screen, so a halt made here is visible from wherever "
                "you happen to be looking.",
            ),
            (
                "Portfolio VaR (95%) and (99%) tiles",
                "Historical Value-at-Risk at each confidence level, from the live return "
                "history of the current portfolio. Each of the four risk tiles reads the "
                "book you hold right now, sampled on a timer, and shows a dash - never a "
                'zero - when it cannot be measured, so "no reading" is never mistaken '
                'for "no risk". A second, smaller line appears beneath a tile only when '
                "the last sizing decision recorded the same figure; when there is no such "
                "decision the line is absent rather than blank.",
            ),
            (
                "Expected Shortfall (97.5%) tile",
                "The average loss in the tail beyond the 97.5% VaR threshold - what a bad "
                "day costs when it is bad, rather than how often.",
            ),
            (
                "Largest single name tile",
                "The largest single position's share of total equity, in the book you "
                'hold right now. Renamed from "Single-name concentration": the figure '
                "underneath it, when one is shown, is the CANDIDATE's share from the "
                "last sizing decision, which is a different measurement - so the two "
                "carry different labels rather than inviting you to read a coincidence "
                "as agreement.",
            ),
            (
                "Correlation table",
                "Pairwise trailing-return correlation across the watchlist, colour-coded. "
                "Since M33 this is not only a display: holdings whose returns track a "
                "candidate at or above the configured threshold are capped TOGETHER as a "
                "cluster, so the table shows the relationships the limit is actually acting "
                "on. High correlation means position limits are counting exposures that are "
                "not actually independent.",
            ),
        ),
    )

    doc.add_heading("6.2 What Trips the Kill-Switch Automatically", level=2)
    _table(
        doc,
        ("Trigger", "Condition"),
        (
            ("Manual", "An operator clicks the button. Recorded with the operator's name."),
            ("Daily loss", "The day's loss reaches the configured daily-loss limit."),
            ("Drawdown", "Drawdown from the peak reaches the configured maximum."),
            (
                "Data staleness",
                "No fresh market data within the staleness window - the feed died, and "
                "trading on the last known price is worse than not trading.",
            ),
            (
                "Reconciliation mismatch",
                "The broker's reported positions disagree with the application's own " "record.",
            ),
        ),
    )
    doc.add_paragraph(
        "A tripped kill-switch stays tripped until it is reset deliberately. It blocks new "
        "orders; it never sells anything on your behalf."
    )
    _callout(
        doc,
        "You will always be told",
        "However the switch trips, three things happen together: the Risk Console button "
        "turns red, the execution banner across the top of every screen changes to "
        "EXECUTION HALTED and names the cause, and a line is written to the log. If two "
        "causes arrive at once the banner keeps the first, because that is the one that "
        "stopped you - a later staleness warning must not overwrite 'daily loss limit "
        "reached'. Resetting the switch clears all three.",
    )


def _ai_advisor(doc: Any, figures: FigureSet) -> None:
    doc.add_page_break()
    doc.add_heading("7. The AI Advisor", level=1)
    doc.add_paragraph(
        "The AI Advisor is a free-text research interface into the same advisory service "
        "that generates the regime notes and backtest commentary elsewhere in the "
        "application. It is an analyst, never a trader: this screen holds no reference to "
        "the Order Management System or to a broker, so there is no code path from a "
        "question typed here to an order placed anywhere."
    )
    _figure(doc, figures, "ai_advisor")

    doc.add_heading("7.1 Screen Elements", level=2)
    _table(
        doc,
        ("Element", "Description"),
        (
            (
                "Symbol dropdown",
                "The symbol context sent with the next question, including your current "
                "position in it.",
            ),
            ("Question input", "A free-text research question. Enter or Ask sends it."),
            (
                "Ask button",
                "Sends the question together with the current regime, positions and risk " "state.",
            ),
            (
                "Conversation pane",
                "A running, read-only transcript. Each answer carries the advisor's "
                "recommendation, a confidence figure and any risk flags. Provider failures "
                "appear here as errors rather than as silence.",
            ),
        ),
    )
    _callout(
        doc,
        "How your question is handled",
        "The text you type is passed to the model as clearly-labelled, untrusted 'fetched' "
        "context - the same channel used for any other external text the system quotes - "
        "never as part of the instruction-bearing system prompt. This is a structural "
        "defence against prompt injection: nothing typed here, or found in any fetched data "
        "elsewhere in the application, can make the model act outside its fixed role as an "
        "analyst. Every recommendation is also re-checked against the Risk Engine before it "
        "is displayed.",
    )
    _callout(
        doc,
        "Which provider answers",
        "Requests are routed into one of two slots, each with its own configured provider "
        "(Section 11.1). Anything touching your positions or portfolio goes to the "
        "position-sensitive slot, which can be kept local-only even when general requests "
        "use Anthropic's cloud API. With no provider configured, the built-in demo engine "
        "answers - always 'hold', zero confidence, flagged demo_mode_no_real_llm - so the "
        "application is usable out of the box without pretending to give analysis.",
    )


def _blotter(doc: Any, figures: FigureSet) -> None:
    doc.add_page_break()
    doc.add_heading("8. The Order Blotter", level=1)
    doc.add_paragraph(
        "The Order Blotter is where every order in the system can be reviewed, and the only "
        "screen that can send one to the broker. It repeats the paper/live banner directly "
        "above the order table, since that is the moment the distinction matters most."
    )
    _figure(doc, figures, "blotter")

    doc.add_heading("8.1 Screen Elements", level=2)
    _table(
        doc,
        ("Element", "Description"),
        (
            ("Mode banner", "Repeats the main window's paper/live indicator above the table."),
            (
                "Show filter",
                "Filters by status: Pending sign-off (the default), All, Filled, Rejected "
                "or Cancelled. Pending is the default because it is the only actionable "
                "set, and it keeps the view short even against a long history.",
            ),
            (
                "Orders table",
                "Order ID, symbol, side, quantity, status and creation time. Rows are "
                "multi-selectable; the rendered view is capped while the underlying order "
                "history is never truncated.",
            ),
            (
                "Sign Off Selected",
                "Enabled when at least one selected order is awaiting sign-off. Opens a "
                "confirmation dialog that itemises every order it is about to transmit.",
            ),
            (
                "Reject Selected",
                "Enabled under the same condition, with the same style of itemised "
                "confirmation.",
            ),
            (
                "Select All Pending",
                "Selects every visible order awaiting sign-off, for review as a batch.",
            ),
        ),
    )

    doc.add_heading("8.2 Order Status Lifecycle", level=2)
    _table(
        doc,
        ("Status", "Meaning"),
        (
            ("new", "Created; not yet evaluated by the Risk Engine."),
            (
                "pending_signoff",
                "Passed the Risk Engine and is awaiting an explicit sign-off or rejection.",
            ),
            ("transmitted", "Sign-off confirmed; sent to the broker and awaiting a fill."),
            ("filled", "The broker reports the order as executed."),
            ("cancelled", "Cancelled before it filled."),
            (
                "rejected",
                "Rejected either by the Risk Engine, by the cash rule at sign-off, or by " "you.",
            ),
        ),
    )

    doc.add_heading("8.3 Bulk Sign-Off", level=2)
    doc.add_paragraph(
        "Selecting many orders and signing them off in one action is supported, but the "
        "confirmation dialog still lists every order it is about to transmit, so approving a "
        "batch stays an informed decision rather than one blind click. Each order is still "
        "individually transmitted only after that confirmation, and each is re-checked "
        "against current cash at that moment - ten orders that were each affordable when "
        "created cannot collectively overspend when approved together."
    )
    _callout(
        doc,
        "The safety invariant behind this screen",
        "No code path in the application calls the broker directly from a signal or a risk "
        "decision. Submitting an order only ever creates a pending record. In the default "
        "Recommend mode, only the explicit, operator-attributed sign-off confirmed through "
        "this screen moves an order to transmitted. In the optional auto-trade mode "
        "(Section 12.3) the autonomy gate performs that sign-off instead, for listed "
        "strategies on paper accounts only, and writes every decision it takes or blocks to "
        "the autonomy journal.",
    )


def _position_protection(doc: Any) -> None:
    doc.add_page_break()
    doc.add_heading("8A. Position Protection and Self-Healing", level=1)
    doc.add_paragraph(
        "Every position this application opens is protected at the broker, not in this "
        "process. The distinction is the whole point: a stop held only in memory disappears "
        "the moment the application does, leaving the position naked through a crash, a "
        "dropped connection or a Windows update."
    )

    doc.add_heading("8A.1 How a Position Is Protected", level=2)
    doc.add_paragraph(
        "A new entry is submitted as a bracket: one order carrying the buy, a protective "
        "stop below it and a profit target above it. The two exit legs are linked as an OCO "
        "(one-cancels-other), so whichever is reached first executes and the broker cancels "
        "the other. Without that link the two are independent, and a price that runs to the "
        "target and later falls through the stop would sell the position twice."
    )
    doc.add_paragraph(
        "Bracketed entries are submitted Good-Til-Cancelled. Submitted for the day instead, "
        "the target leg expires at the close and the broker cancels the paired stop with it - "
        "which is exactly how six positions spent a weekend unprotected on 31 July 2026."
    )

    doc.add_heading("8A.2 What Happens When Protection Disappears", level=2)
    doc.add_paragraph(
        "Protection can vanish for reasons this application does not control: an expiry, a "
        "broker-side cancellation, or a manual cancellation in the broker's own interface. "
        "Three mechanisms cover it."
    )
    _table(
        doc,
        ("Mechanism", "When it runs", "What it does"),
        (
            (
                "Verification",
                "Every reconciliation poll",
                "Asks the broker what is actually resting and drops any stop this "
                "application believes in that is not there. A position whose protection is "
                "unknown counts its FULL VALUE against the risk budget.",
            ),
            (
                "Re-arm at startup",
                "Every launch",
                "Proposes a replacement OCO for each held position the broker is not "
                "protecting, using the stop and target the position was originally sized "
                "against.",
            ),
            (
                "Protection sweep",
                "Every five minutes",
                "The same repair on a timer, so a stop lost mid-session is replaced without "
                "waiting for a restart.",
            ),
        ),
    )
    doc.add_paragraph(
        "The replacement level always comes from the recorded entry, never from a fresh "
        "calculation. The risk budget was spent on the distance the position was sized "
        "against, so protecting it at any other distance protects an amount nobody approved. "
        "A position with no recorded entry stop gets nothing and is logged as unprotected - "
        "an invented level would look identical to a real one on every screen."
    )
    _callout(
        doc,
        "Protective orders are not gated on market hours",
        "A resting stop executes nothing until its level trades, so a closed market is the "
        "right time to place one rather than a reason to wait. Every other autonomous order "
        "remains blocked outside session hours. The kill-switch, recommend mode and the "
        "live-account rule all still take precedence.",
    )

    doc.add_heading("8A.3 When a Protective Order Fires", level=2)
    doc.add_paragraph(
        "A stop or target executing closes the position entirely at the broker: no order "
        "leaves this application, so nothing here observes it directly. Each reconciliation "
        "poll therefore asks the broker for executions it did not send, records them as "
        "closed trades with their real fill prices, and updates its own position tracking "
        "before comparing anything."
    )
    doc.add_paragraph(
        "Without that step a stop doing its job would read as a discrepancy between tracked "
        "and actual holdings, trip the kill-switch and halt the session - and the closed "
        "trade would never reach the Performance screen at all."
    )


def _screener(doc: Any, figures: FigureSet) -> None:
    doc.add_page_break()
    doc.add_heading("9. The Screener", level=1)
    doc.add_paragraph(
        "The Screener narrows a candidate universe to the names worth taking to the "
        "Workbench. It is read-only by design: it never edits the tradable watchlist. "
        "Promoting a screened symbol is a deliberate step - add it to the curated list in "
        "Settings and restart."
    )
    _figure(doc, figures, "screener")

    doc.add_heading("9.1 Filters", level=2)
    _table(
        doc,
        ("Filter", "Description"),
        (
            ("Market", "US or ASX. Determines which candidate lists are searched."),
            (
                "Category",
                "curated (your own list from Settings), etf, or megacap - the built-in "
                "universes.",
            ),
            ("Sector", "Restricts results to one GICS-style sector, or All."),
            ("Min EPS growth", "Minimum year-on-year earnings-per-share growth."),
            ("Max PEG", "Maximum price/earnings-to-growth ratio."),
            ("Min dividend yield", "Minimum trailing dividend yield."),
            (
                "Min average volume",
                "Minimum average daily volume - the liquidity floor, applied before "
                "anything else.",
            ),
        ),
    )

    doc.add_heading("9.2 Result Columns", level=2)
    _table(
        doc,
        ("Column", "Description"),
        (
            ("Symbol", "The ticker, matching the field name used by both supported brokers."),
            ("Name", "The instrument's name."),
            ("Sector", "Its sector, from a curated map covering US and ASX listings."),
            ("Price", "The most recent close from the configured price source."),
            ("Avg Volume", "Average daily volume."),
            ("EPS Growth, PEG, Div Yield, ROE", "The fundamental figures the filters act on."),
            (
                "Trend",
                "Up, Down or Flat, from the close against its 20-period simple moving "
                "average over a 40-bar window. A dash means there was not enough history.",
            ),
        ),
    )
    _callout(
        doc,
        "Which figures here are real",
        "Every column follows its configured source. Price and trend come from the market "
        "data source (Section 11.4); EPS growth, PEG, dividend yield and ROE come from the "
        "fundamentals source (Section 11.8); sectors are always real, from a curated map. On "
        "the simulated settings those figures are invented, and screening on them exercises "
        "the workflow rather than picking stocks. A dash means the figure does not exist - "
        "an index ETF has no return on equity - which is not the same as a measured zero.",
    )


def _performance(doc: Any, figures: FigureSet) -> None:
    doc.add_page_break()
    doc.add_heading("10. The Performance Screen", level=1)
    doc.add_paragraph(
        "Every other screen shows what the system is doing or intends to do. This one shows "
        "whether any of it worked. It is built entirely on realised, closed trades - never "
        "on signals or intentions - because a decision journal tells you what the system "
        "chose, never whether the choice was right."
    )
    _figure(doc, figures, "performance")

    doc.add_heading("10.1 Promotion Status", level=2)
    doc.add_paragraph(
        "The promotion table leads the screen because its most important row is the easiest "
        "to miss: a strategy trading unattended on a record that no longer supports it. Each "
        "strategy is scored against a fixed bar and given one of four statuses."
    )
    _table(
        doc,
        ("Status", "Meaning"),
        (
            ("promoted", "Cleared to trade unattended, and its record still supports that."),
            (
                "promoted-below-bar",
                "Cleared to trade unattended but no longer meeting the bar. Shown in red. "
                "This is the row to act on.",
            ),
            ("eligible", "Meets the bar but has not been listed for auto-trade."),
            ("not-eligible", "Does not meet the bar. The Blocking column says which test failed."),
        ),
    )
    doc.add_paragraph(
        "The gate advises rather than enforces by default: you may list a strategy it has "
        "not cleared, and this table then shows you having done so. Setting "
        "QAT_ENFORCE_PROMOTION_EVIDENCE makes the bar binding, so a strategy that degrades "
        "stops trading unattended without anyone having to notice. It is off by default only "
        "because a fresh install has no trade history and would otherwise block everything "
        "for a reason that looks like a bug."
    )

    doc.add_heading("10.2 The Promotion Bar", level=2)
    _table(
        doc,
        ("Test", "Default requirement", "Why"),
        (
            (
                "Minimum trades",
                "30 closed trades",
                "Below this, the other figures are noise.",
            ),
            (
                "Average R",
                "At least +0.2",
                "Average outcome per unit of risk taken, which is the figure position "
                "sizing is built on.",
            ),
            ("Win rate", "At least 40%", "A sanity floor, not a target."),
            (
                "Worst loss vs average win",
                "No worse than 3x",
                "A good average hides a single catastrophic trade. This is the test that "
                "catches it.",
            ),
        ),
    )

    _callout(
        doc,
        "Trade history accumulates across sessions",
        "The trade count on this screen is the running total, not this session's. Closed "
        "trades are read back from closed_trades.csv at every launch, and positions opened in "
        "an earlier session are restored into the ledger at startup from the recorded entry, "
        "so a stop firing weeks after the entry still produces a complete trade with its "
        "correct entry price, stop and holding period. A position held when this application "
        "first met it has no recorded entry, and is named in the log at startup: its eventual "
        "exit is still handled correctly at the broker, but it cannot produce a closed trade, "
        "because nothing here knows what it cost or when it was opened.",
    )

    doc.add_heading("10.3 Closed Trades and Reports", level=2)
    _table(
        doc,
        ("Element", "Description"),
        (
            (
                "Headline",
                "Trade count, net P&L, win rate and average R across all strategies, plus "
                "maximum drawdown and Sharpe from the recorded equity curve.",
            ),
            (
                "Closed trades tab",
                "Newest first: close time, symbol, name, strategy, quantity, entry, exit, "
                "P&L and R multiple. Profits and losses are colour-coded.",
            ),
            (
                "Daily reports tab",
                "The generated end-of-day report, written after each market close.",
            ),
            ("Weekly reports tab", "The same for the week's last close."),
            ("Refresh button", "Re-reads the ledger, the equity curve and the report files."),
        ),
    )
    doc.add_paragraph(
        "Trades are matched entry to exit as positions close. A sell with no matching entry - "
        "a position adopted from a previous session that this application never saw opened - "
        "is logged and skipped rather than assigned an invented P&L."
    )


def _session_record(doc: Any) -> None:
    doc.add_heading("10.4 What a Session Leaves Behind", level=2)
    doc.add_paragraph(
        "Everything needed to reconstruct a session afterwards is written to the data "
        "directory rather than held in memory, so a post-mortem can be done the next "
        "morning without the application running."
    )
    _table(
        doc,
        ("File", "Answers"),
        (
            ("closed_trades.csv", "What was traded, and what it made."),
            ("equity_curve.csv", "How the account value moved through the session."),
            (
                "decision_journal.csv",
                "Every order decision and its reason - proposed, signed off, rejected - "
                "in every execution mode, with the operator who acted.",
            ),
            (
                "risk_decisions.csv",
                "How the risk engine sized or refused each order, including the inputs " "it used.",
            ),
            (
                "daily_reports.md / weekly_reports.md",
                "The close-triggered reports, including the AI analyst notes.",
            ),
            ("logs/qat.log", "The application log. Rotating, ten files of five megabytes."),
        ),
    )
    doc.add_paragraph(
        "Export Session, at the top of this screen, gathers all of the above plus a "
        "manifest into a single zip under data/exports. It copies rather than moves, so "
        "the running session keeps writing to the originals."
    )
    _callout(
        doc,
        "Why a quiet day is still worth reading",
        "The journal records what was decided, not only what was done. A day with no "
        "orders and a day where the cash floor blocked eleven of them look identical in "
        "the trade ledger and are completely different states of the world. If nothing "
        "traded, the journal is where you find out whether that was because nothing "
        "qualified or because something kept refusing.",
    )


def _metrics_panel(doc: Any) -> None:
    doc.add_heading("10.5 What Each Closed Trade Records", level=2)
    doc.add_paragraph(
        "Every closed trade carries more than its result. The extra columns exist so that a "
        "completed trial can answer WHY an outcome happened rather than only what it was, "
        "and none of them can be reconstructed afterwards - the price path is gone by the "
        "time a trade closes, and the regime has usually moved on."
    )
    _table(
        doc,
        ("Column", "What it tells you"),
        (
            (
                "Regime at entry",
                "Which market state the position was opened in, with that regime's "
                "probability at the time. The regime at EXIT is deliberately not recorded: a "
                "position held for weeks closes in a different state from the one it was "
                "taken in, and attributing the result to the exit would answer the wrong "
                "question.",
            ),
            (
                "Exposure scalar",
                "The regime multiplier applied when the position was sized, so a small "
                "position taken in a defensive regime is not mistaken for a small signal.",
            ),
            (
                "Exit reason",
                "stop, target, time_stop, signal or delever. Set by whatever caused the "
                "exit rather than inferred, because after the fact the price alone cannot "
                "separate a time stop from a strategy signal.",
            ),
            (
                "Holding days",
                "Calendar days from entry to exit.",
            ),
            (
                "Entry slippage",
                "What the entry actually cost against the price it was sized on. The cost "
                "model ASSUMES a slippage figure; this is the only way to find out whether "
                "that assumption holds.",
            ),
            (
                "MAE (R)",
                "Maximum adverse excursion - how far the trade went against the entry "
                "before it resolved, in units of the risk taken on it. A winner that spent "
                "its life at -0.9R was very nearly a loser, and an average result hides "
                "that completely.",
            ),
            (
                "MFE (R)",
                "Maximum favourable excursion. A loser that reached +2R first says "
                "something about the exit rule, not the entry.",
            ),
        ),
    )
    doc.add_paragraph(
        "All of it is written to closed_trades.csv alongside the P&L columns, and read back "
        "at every launch. None of these diagnostic columns influences a decision - sizing and "
        "the promotion bar read the P&L figures, not the excursion ones - but the file as a "
        "whole is now load-bearing rather than a passive record."
    )

    doc.add_heading("10.6 The Metrics Tab", level=2)
    doc.add_paragraph(
        "The trade list says what the system did. This tab says what the system is, which "
        "is the question a promotion decision actually turns on. Every row carries a "
        "one-line note on what it tells you."
    )
    _table(
        doc,
        ("Metric", "What it tells you"),
        (
            (
                "Expectancy",
                "Expected profit per trade. The most decision-relevant figure here: a high "
                "win rate with a negative expectancy is a losing system that feels good.",
            ),
            (
                "Win rate",
                "Share of closed trades that made money. Read it beside expectancy or not "
                "at all.",
            ),
            (
                "Avg win / avg loss",
                "What a winner makes against what a loser costs. The promotion gate already "
                "judges on this ratio.",
            ),
            (
                "Average R",
                "Outcome per unit of risk, over the trades that had a measurable stop. The "
                "row states how many that was, because it is usually fewer than the total.",
            ),
            (
                "Holding period",
                "Mean time from entry to exit. Decides whether the session-phase and "
                "daily-loss rails bind constantly or barely at all.",
            ),
            (
                "Trades per week",
                "Turnover over the period actually traded - the read on whether the system "
                "is doing anything.",
            ),
            (
                "Average and peak exposure",
                "Share of equity held in positions rather than cash. Two percent on ten "
                "percent deployed is not two percent on ninety-five.",
            ),
            (
                "Recovery factor",
                "Net profit against the worst drawdown that produced it. Preferred to Calmar "
                "on short samples because it does not annualise.",
            ),
            (
                "Max drawdown, Sharpe, profit factor",
                "The conventional risk-adjusted figures, unchanged.",
            ),
        ),
    )
    _callout(
        doc,
        "A dash is not a zero",
        "Every metric here reports a dash until there are enough closed trades to support "
        "it, and rates additionally need a day of elapsed history. This is deliberate: a "
        "figure computed from three trades is noise with a decimal point, and a dash saying "
        "'not enough to tell you yet' is more use than a confident number that means "
        "nothing. 'Measured, and it is zero' and 'not enough trades to say' are different "
        "claims, and the panel never confuses them.",
    )


def _settings(doc: Any, figures: FigureSet) -> None:
    doc.add_page_break()
    doc.add_heading("11. Settings", level=1)
    doc.add_paragraph(
        "The screen scrolls: it carries more than fits a window. Save and the status line "
        "stay fixed below the scrolling area so they cannot be scrolled out of reach. Every "
        "field on this screen is restart-required - Save writes the configuration file and "
        "the change takes effect on the next launch, which is the conservative choice for "
        "numbers a running risk engine has already sized positions against."
    )
    doc.add_paragraph(
        "Settings configures the application's five external-facing decisions: which AI "
        "provider answers, which market and symbols to follow, which broker holds the "
        "account, where prices come from, and whether orders need your confirmation."
    )
    _callout(
        doc,
        "Every setting here takes effect at the next restart",
        "Nothing on this screen reconfigures the running application. The entire engine "
        "graph - market data feed, regime engine, strategy engine, broker connection and "
        "every screen that references the watchlist - is built once at startup around these "
        "values. Live-rewiring that mid-session would be a far larger and riskier change "
        "than a restart. Save writes non-secret values to .env and secrets to the Windows "
        "Credential Manager, then tells you to restart.",
    )
    _figure(doc, figures, "settings")

    doc.add_heading("11.1 AI Provider", level=2)
    doc.add_paragraph(
        "Requests land in one of two slots, each with an independently selectable provider. "
        "This is deliberately not a single application-wide toggle: the position-sensitive "
        "slot can stay local-only even when general requests use Anthropic's cloud API."
    )
    _table(
        doc,
        ("Field", "Description"),
        (
            (
                "General requests",
                "Regime narrative and backtest commentary - nothing about your positions. "
                "Anthropic, Local (LM Studio) or Demo.",
            ),
            (
                "Position-sensitive requests",
                "Anything touching your positions or portfolio. Choosing Anthropic here "
                "displays a red warning that portfolio data will be sent to a cloud API. "
                "Local is listed first.",
            ),
            (
                "Anthropic API key",
                "Masked and write-only. Stored in the Windows Credential Manager, never "
                "in .env and never in logs. Blank leaves the existing key untouched.",
            ),
            (
                "LM Studio base URL",
                "The OpenAI-compatible endpoint, typically http://localhost:1234/v1. The "
                "/v1 segment matters: without it the server answers some requests with an "
                "error body that looks like success.",
            ),
            ("LM Studio model name", "The model identifier as LM Studio reports it."),
            (
                "Test Connection",
                "Runs a real one-token completion rather than only checking that the "
                "server answers. A reachability-only check reports success for "
                "configurations that then fail on every actual request.",
            ),
        ),
    )
    doc.add_paragraph(
        "The same LM Studio configuration works with any OpenAI-compatible local server, "
        "including Ollama, by pointing the base URL at it instead."
    )

    doc.add_heading("11.2 Market and Watchlist", level=2)
    _table(
        doc,
        ("Field", "Description"),
        (
            ("Market", "US or ASX."),
            ("Watchlist category", "curated, etf or megacap."),
            (
                "US / ASX curated tickers",
                "Comma-separated symbol lists. ASX symbols carry the .AX suffix.",
            ),
            ("Max symbols", "Caps how many symbols the live engines follow at once."),
            ("Min average daily volume", "The liquidity floor applied when building the list."),
        ),
    )

    doc.add_heading("11.3 Broker and Cash", level=2)
    _table(
        doc,
        ("Field", "Description"),
        (
            (
                "Broker",
                "Simulated (built-in, no credentials), Alpaca paper account, or "
                "Interactive Brokers.",
            ),
            (
                "Alpaca API key / secret key",
                "Masked and write-only, stored in the Windows Credential Manager. The "
                "same credentials serve Alpaca market data (Section 11.4).",
            ),
            (
                "Test Broker Connection",
                "Fetches the account and reports its actual cash and equity, so you can "
                "confirm the application is reading the account you think it is.",
            ),
            (
                "Minimum cash reserve",
                "The cash floor a buy may never spend below. Default $1.00; the minimum "
                "accepted value is $0.01, so the rule cannot be switched off. See "
                "Section 12.2.",
            ),
        ),
    )
    doc.add_paragraph(
        "Alpaca trades US equities only. Selecting it while Market is set to ASX shows an "
        "inline warning, because that combination cannot trade anything."
    )

    doc.add_heading("Connecting Interactive Brokers", level=3)
    doc.add_paragraph(
        "Interactive Brokers is what the ASX configuration trades through. The application "
        "speaks to IB Gateway or TWS over a local socket; it never contacts IBKR directly "
        "and never handles your IBKR password. Install Gateway rather than TWS if you plan "
        "to leave it running - it is the headless one - and log in with the PAPER username, "
        "which is a separate username from the live one rather than a toggle on the same "
        "credentials."
    )
    doc.add_paragraph(
        'In Gateway, open Configure then Settings then API then Settings, tick "Enable '
        'ActiveX and Socket Clients", set the socket port, and add 127.0.0.1 to Trusted '
        "IPs. The application connects on client ID 1."
    )
    _table(
        doc,
        ("Port", "What it reaches", "Setting"),
        (
            ("4002", "IB Gateway - PAPER", "QAT_IBKR_PORT=4002, the default"),
            ("7497", "TWS - PAPER", "QAT_IBKR_PORT=7497"),
            ("4001", "IB Gateway - LIVE MONEY", "Refused while trading mode is paper"),
            ("7496", "TWS - LIVE MONEY", "Refused while trading mode is paper"),
        ),
    )
    doc.add_paragraph(
        "Pointing a paper configuration at a live port is REFUSED rather than allowed - the "
        "application will not start. This is deliberate and is the one lock the US path has "
        'no equivalent of: every banner and every record would read "paper" while real '
        "orders were reachable, which is the most expensive mislabelling the system could "
        "make. The safe mismatch - live mode against a paper port - is permitted."
    )
    doc.add_paragraph(
        "Two limitations are worth knowing before you rely on this broker. Interactive "
        "Brokers is used for EXECUTION ONLY here: market data still comes from the sources "
        "in Section 11.4, so the prices the strategy reads and the venue it trades at are "
        "not the same feed. And IBKR publishes no corporate-action announcements to this "
        "application, so a share split cannot be seen before its ex-date; the application "
        "says so once at startup rather than failing quietly per symbol. Section 12 covers "
        "what that leaves unprotected."
    )

    doc.add_heading("11.4 Market Data", level=2)
    _table(
        doc,
        ("Source", "Description"),
        (
            (
                "Simulated (random walk)",
                "The default. A seeded random walk, so the application works offline. A "
                "standing amber warning is displayed while it is selected: nothing "
                "observed in this mode tells you how a strategy behaves on real prices.",
            ),
            (
                "Real market data (Yahoo)",
                "Free, unofficial, typically delayed about 15 minutes and rate-limited. "
                "Covers US and ASX.",
            ),
            (
                "Real market data (Alpaca, US only)",
                "Your own Alpaca account's feed, for live ticks and daily bars, using the "
                "broker's credentials. Choosing Alpaca for both broker and data means the "
                "prices you trade on and the account you trade into come from the same "
                "venue.",
            ),
        ),
    )
    doc.add_paragraph(
        "With Alpaca selected, a feed picker appears. It is hidden for the other sources, "
        "where it would mean nothing."
    )
    _table(
        doc,
        ("Alpaca feed", "Latency", "Coverage", "Account required"),
        (
            (
                "IEX (default)",
                "Real time",
                "A single exchange, carrying a small share of US consolidated volume",
                "Any, including a free paper account",
            ),
            (
                "SIP",
                "Real time",
                "The full consolidated tape",
                "Paid Algo Trader Plus subscription",
            ),
            ("Delayed SIP", "15 minutes", "The full consolidated tape", "Free tier"),
        ),
    )
    doc.add_paragraph(
        "IEX is the default because it is the only real-time option a free paper account can "
        "use. It is a genuine trade print, but from one exchange, so less liquid names can "
        "look sparse compared with the consolidated tape. Requesting SIP without the "
        "subscription fails outright rather than quietly degrading - you find out "
        "immediately instead of trading on data you did not get."
    )
    _callout(
        doc,
        "How a dead feed behaves",
        "Any real feed can return nothing without warning. The application degrades to "
        "simulated data with a logged warning rather than stopping - but never silently. A "
        "persistently dead feed ends the price stream deliberately, which raises a staleness "
        "event and trips the kill-switch, rather than leaving the application looking alive "
        "while trading on a price that stopped updating an hour ago.",
    )

    doc.add_heading("11.5 Company Fundamentals", level=2)
    doc.add_paragraph(
        "Nine of the fifteen strategies select on company fundamentals, so this setting "
        "decides whether their picks carry any information about the companies at all."
    )
    _table(
        doc,
        ("Source", "Description"),
        (
            (
                "Simulated (default)",
                "Every EPS growth, PEG, ROE and dividend figure is generated. A standing "
                "amber warning is displayed while it is selected.",
            ),
            (
                "Real company fundamentals (Yahoo)",
                "Reported figures, cached for seven days by default. Free and unofficial, "
                "with the same caveats as the Yahoo price feed.",
            ),
        ),
    )
    _callout(
        doc,
        "Expect fewer signals on real fundamentals",
        "A real source cannot answer every field for every symbol, and that is usually "
        "correct rather than a failure - an index ETF has no return on equity, and some "
        "listings publish no PEG. A strategy that needs a figure which does not exist "
        "abstains on that symbol instead of scoring it against a substitute. Measured on the "
        "shipped watchlist, SPY produced fundamentals-driven buy recommendations under eight "
        "of twelve simulated configurations; on real data it produces none, at any threshold, "
        "because the figures genuinely are not there. A quieter Order Blotter is the setting "
        "working, not failing.",
    )

    doc.add_heading("11.6 Risk Limits", level=2)
    doc.add_paragraph(
        "The caps that decide which trades happen and how large they are. Until M36 these "
        "were editable only by hand in the configuration file and appeared on no screen, so "
        "the limits actually in force could not be read anywhere in the application."
    )
    _callout(
        doc,
        "Percentages on screen, fractions in the file",
        "The screen shows 15%; the configuration file stores 0.15. The conversion happens in "
        "both directions so you never handle the stored form. Every field is bounded to what "
        "the application will accept, so the screen cannot write a value the next launch "
        "would refuse to start on.",
        danger=False,
    )
    _table(
        doc,
        ("Setting", "Default", "What it bounds"),
        (
            ("Risk per trade", "1%", "Equity risked between entry and stop on one trade."),
            ("Stop distance", "2.5 x ATR", "How far the protective stop sits from entry."),
            (
                "Aggregate risk-at-stop",
                "5%",
                "Total loss if every open position stopped out at once.",
            ),
            ("Single-name concentration", "15%", "One ticker as a share of equity."),
            ("Sector concentration", "30%", "One sector as a share of equity."),
            (
                "Correlated-cluster concentration",
                "30% at 0.70",
                "Holdings whose returns track a candidate at or above the threshold, capped "
                "together. Sector is a label; this is measured.",
            ),
            (
                "Overnight-gap budget",
                "5% at a 6% gap",
                "Loss allowed from a gap opening THROUGH the stops rather than trading to "
                "them. Measured on position value, because that is what a gap moves.",
            ),
            ("Max concurrent positions", "10", "How thinly the portfolio may be spread."),
            ("Portfolio Expected Shortfall", "3%", "Average loss in the tail beyond VaR."),
            ("Daily loss limit", "3%", "Halts new autonomous buys for the day."),
            ("Max drawdown limit", "20%", "Peak-to-trough decline before the rails engage."),
            (
                "Kelly fraction",
                "0.50",
                "Full Kelly assumes the win rate and payoff ratio are exactly right and "
                "sizes violently when they are not.",
            ),
            (
                "Max cost as a share of risk",
                "10%",
                "Refuses a trade whose commission and slippage would eat this much of the "
                "amount being risked.",
            ),
        ),
    )
    doc.add_paragraph(
        "Every limit except the position count is enforced by TRIMMING an order to what fits "
        "rather than refusing it. A cap that refuses instead of resizing stops a strategy "
        "trading altogether, which is how a 15% single-name limit would behave against a "
        "sizing chain that lands near 20%."
    )
    _callout(
        doc,
        "The de-lever sweep is the one rail that sells",
        "Every limit above blocks NEW risk, which unwinds a breach passively as positions "
        "close. The de-lever sweep instead trims every position proportionally to get back "
        "under the cap. It is off by default, because a rail that sells uninvited is a much "
        "larger delegation than one that declines to buy. Disabled, a breach is still "
        "measured, logged and blocking.",
        danger=True,
    )
    doc.add_paragraph(
        "Lowering a limit does not close anything already held. It governs what may be "
        "opened from that point, and an existing breach unwinds as positions close."
    )

    doc.add_heading("11.7 Holding, Churn and Protection", level=2)
    doc.add_paragraph(
        "Commission is charged per transaction, so how OFTEN the account trades matters as "
        "much as how much it risks. Ten positions turned over weekly costs several percent "
        "of a hundred-thousand-dollar account a year before a single losing trade."
    )
    _table(
        doc,
        ("Setting", "Default", "What it does"),
        (
            (
                "Minimum hold",
                "10 trading days",
                "How long a position is held before a signal may close it.",
            ),
            (
                "Loss escape",
                "0.5 R",
                "The minimum hold must not trap a losing position. A trade this far against "
                "its entry may be closed regardless.",
            ),
            (
                "Time stop",
                "30 trading days",
                "Forces an exit on a thesis that never resolved. This is doing more work "
                "than it appears to: a strategy whose own exit signal rarely fires closes "
                "most of its positions this way.",
            ),
            (
                "Max new positions per week",
                "10",
                "A turnover budget, bounding commission drag directly.",
            ),
            (
                "Re-check protection every",
                "300 seconds",
                "How often held positions are checked for a missing stop or target, and a "
                "replacement proposed. See Section 8A.",
            ),
            (
                "Size on measured edge after",
                "20 closed trades",
                "Until a strategy has this many results of its own, position sizing uses "
                "documented defaults rather than its measured win rate and payoff ratio. "
                "Lowering it lets a small and possibly lucky sample set the risk.",
            ),
        ),
    )

    doc.add_heading("11.8 Execution Mode", level=2)
    _table(
        doc,
        ("Field", "Description"),
        (
            (
                "Mode",
                "Recommend (default): every order waits in the Order Blotter for your "
                "sign-off. Auto-trade: qualifying orders are signed off without "
                "per-order confirmation. Paper accounts only.",
            ),
            (
                "Strategies cleared to auto-trade",
                "A dropdown listing every built-in strategy, each with a checkbox, and a "
                "summary of what is currently cleared. Empty means none. Autonomy is granted per "
                "strategy and never inherited by all of them because one proved out; a "
                "strategy not listed still produces recommendations for your sign-off.",
            ),
        ),
    )
    doc.add_paragraph(
        "Selecting Auto-trade opens a confirmation dialog that spells out what the rails do "
        "and do not do, and whose default button is No, so an accidental Enter keypress "
        "declines. While the mode is selected, a red warning panel stays on screen. Section "
        "12.3 documents the rails in full."
    )


def _interface_level(doc: Any) -> None:
    doc.add_heading("11.9 Interface Level", level=2)
    doc.add_paragraph(
        "QAT_UI_LEVEL chooses how much of the interface is shown. It is not a cosmetic "
        "preference: two of the levels withhold controls, so changing it changes what you can "
        "do, not only what you can see."
    )
    _table(
        doc,
        ("Level", "What it shows, and what it withholds"),
        (
            (
                "Guided",
                "Every figure carries a plain-English caption. The Strategy Workbench is "
                "absent entirely, and so are the advanced diagnostics - a screen that is "
                "absent is one level away, and this selector is what says so.",
            ),
            (
                "Standard",
                "The default. Captions are still shown. The Workbench appears, and the "
                "Blotter's bulk sign-off becomes available. The Workbench's DEPLOY control "
                "is still withheld.",
            ),
            (
                "Professional",
                "Captions are dropped in favour of density, the correlation matrix and the "
                "audit log appear, and the Workbench's deploy control becomes available.",
            ),
        ),
    )
    _callout(
        doc,
        "Resetting configuration can remove a control you were using",
        "The default is Standard, and the deploy control is Professional-only. So a "
        "configuration reset on a machine that was set to Professional silently takes that "
        "button away. If a control you used yesterday is missing, check this setting before "
        "anything else.",
        danger=True,
    )


def _storage_location(doc: Any) -> None:
    doc.add_heading("11.10 Where Settings and Records Are Stored", level=2)
    doc.add_paragraph(
        "Everything the application owns lives in one per-user directory, named at the "
        "bottom of the Settings screen so it is never a guess:"
    )
    _table(
        doc,
        ("Location", "Contents"),
        (
            (
                "%LOCALAPPDATA%\\QuantAdvisoryTerminal\\.env",
                "Every non-secret setting the Settings screen writes.",
            ),
            (
                "%LOCALAPPDATA%\\QuantAdvisoryTerminal\\data",
                "Trade ledger, equity curve, decision journal, risk decisions, reports, "
                "logs and session exports.",
            ),
            (
                "Windows Credential Manager",
                "API keys and secrets. These are never written to .env and never to a log.",
            ),
        ),
    )
    doc.add_paragraph(
        "The location does not move when the application does, so upgrading to a new build "
        "keeps every setting and every record. Setting the QAT_HOME environment variable "
        "relocates all of it, which is what a portable installation would do."
    )
    _callout(
        doc,
        "Upgrading from an earlier build",
        "Earlier versions kept settings and records beside whichever folder the application "
        "was started from, so the same installation could read different settings depending "
        "on how it was launched. On first run, a .env and a data folder found in the working "
        "directory are copied into the new location. They are copied and never moved, an "
        "existing file at the destination is never overwritten, and what happened is written "
        "to the log. Once you are satisfied the new location has everything, the old folders "
        "can be deleted by hand - the application no longer reads them.",
    )


def _safety(doc: Any) -> None:
    doc.add_page_break()
    doc.add_heading("12. Safety Architecture Reference", level=1)
    doc.add_paragraph(
        "This section consolidates the mechanisms referenced throughout the manual, since "
        "they are the most important thing to understand about this application before using "
        "it - in Paper mode or otherwise."
    )

    doc.add_heading("12.1 Defence in Depth", level=2)
    _table(
        doc,
        ("Layer", "What it guarantees"),
        (
            (
                "Paper-only default",
                "The application always starts in Paper mode. Live mode requires a "
                "deliberate configuration change and an in-application confirmation.",
            ),
            (
                "Submission never transmits",
                "Submitting an order only ever creates a pending record. No signal path "
                "and no risk decision calls the broker directly.",
            ),
            (
                "Sign-off gate",
                "Only an explicit, operator-attributed sign-off transmits an order, and "
                "the user interface never reaches that call except from inside a confirmed "
                "dialog branch.",
            ),
            (
                "Risk Engine gating",
                "Every order candidate, whichever strategy produced it, is sized and "
                "checked against per-trade risk, portfolio Expected Shortfall, "
                "single-name and sector concentration, aggregate risk-at-stop and a "
                "maximum open-position count.",
            ),
            (
                "Real company fundamentals",
                "Reported EPS growth, PEG, ROE and dividend figures instead of generated "
                "ones, with strategies abstaining where a figure does not exist "
                "(Section 11.5).",
            ),
            (
                "Cash and no-leverage rule",
                "A buy can never exceed available cash and never spend below the reserve. "
                "Checked twice, and not disableable. See 12.2.",
            ),
            (
                "Kill-switch",
                "One always-visible control halts new order flow; five conditions trip it "
                "automatically (Section 6.2).",
            ),
            (
                "Reconciliation",
                "The broker's positions are polled and compared against the application's "
                "own record; a mismatch trips the kill-switch.",
            ),
            (
                "AI as analyst only",
                "The advisory layer holds no reference to the Order Management System, and "
                "every recommendation is re-checked against the Risk Engine before display.",
            ),
            (
                "Prompt-injection defence",
                "All free text and fetched data enters the model as labelled untrusted "
                "context, never as instructions.",
            ),
            (
                "Deploy, do not auto-run",
                "The Strategy Engine starts with no strategies active.",
            ),
            (
                "Secrets never in files or logs",
                "API keys live only in the Windows Credential Manager, and log output is "
                "scrubbed before it is written.",
            ),
        ),
    )

    doc.add_heading("12.2 The Cash and No-Leverage Rule", level=2)
    doc.add_paragraph(
        "Two separate guarantees, both hard-coded rather than advisory: the account can "
        "never be leveraged - a buy's notional can never exceed available cash - and cash "
        "can never be fully depleted, because a buy can never spend below the reserve."
    )
    doc.add_paragraph("They are enforced at two points, deliberately:")
    for point in (
        "At sizing: the Risk Engine caps the quantity at what the available cash less the "
        "reserve affords, and rejects the order outright if that is less than one share. "
        "The decision is written to the risk audit trail like every other.",
        "At sign-off: the order is re-checked against current cash immediately before "
        "transmission. This is load-bearing rather than belt-and-braces, because bulk "
        "sign-off means ten orders each affordable on their own can collectively overspend "
        "when approved together. Sign-off rejects rather than resizing - silently changing a "
        "quantity you just approved would defeat the point of the approval.",
    ):
        doc.add_paragraph(point, style="List Bullet")
    doc.add_paragraph(
        "The reserve is configurable but its minimum accepted value is one cent. That is "
        "what makes 'cash is never fully depleted' structurally true rather than a default "
        "someone can switch off. Sells are never blocked by this rule: they raise cash."
    )

    doc.add_heading("12.3 Autonomous Trading", level=2)
    _callout(
        doc,
        "AUTO-TRADE PLACES ORDERS WITH NO PER-ORDER CONFIRMATION",
        "It is off by default, applies only to strategies you list explicitly, and is "
        "confined to paper accounts. Reaching unattended live trading would require a code "
        "change, not a configuration change: there is no supported configuration in which "
        "this application trades real money with no human in the loop.",
        danger=True,
    )
    doc.add_paragraph("When auto-trade is enabled, an order must still pass every one of these:")
    _table(
        doc,
        ("Rail", "Condition"),
        (
            ("Strategy allow-list", "The originating strategy is listed as cleared."),
            (
                "Promotion evidence",
                "Optionally, the strategy must still meet the promotion bar on its own "
                "realised trades (Section 10.2).",
            ),
            (
                "Session phase",
                "The market is open, and outside the opening and midday windows.",
            ),
            (
                "Daily P&L rails",
                "Order size is halved once the day is roughly 2% under water, and new "
                "unattended buys stop entirely at roughly 4%. Protective sells are never "
                "gated - they reduce risk.",
            ),
            (
                "Price drift",
                "The price has not moved more than about 3% from the price the order was "
                "sized against; beyond that the sizing, stop and target are all stale.",
            ),
            (
                "Risk Engine, cash rule, kill-switch",
                "Unchanged and fully in force.",
            ),
        ),
    )
    doc.add_paragraph(
        "Every decision, taken or blocked, is written to the autonomy journal. These rails "
        "bound the damage; they do not make a strategy correct. Review the journal and the "
        "Performance screen regularly."
    )

    doc.add_heading("12.4 When Something Outside the Application Changes a Position", level=2)
    doc.add_paragraph(
        "The application tracks what it believes it holds and compares that against the "
        "broker on a timer. A difference it cannot account for trips the kill-switch, which "
        "is the correct response: a view of the account that cannot be trusted is not a "
        "basis for trading."
    )
    doc.add_paragraph(
        "Some differences have a cause, though, and halting the session for a known cause is "
        "its own kind of failure - an operator who is trained to dismiss the one signal "
        'meaning "my view of the account is wrong" will dismiss the real one too. So a '
        "difference can be DECLARED explained from the Risk Console, and the position is then "
        "quarantined instead of halting the session."
    )
    _callout(
        doc,
        "Declaring is containment, not repair",
        "A quarantine stops the ordinary path acting on a position. It does NOT correct the "
        "quantity, the entry record, the resting protection or the trade ledger - all four are "
        'still manual. The Risk Console says so permanently, because reading "declared" as '
        '"fixed" is the one mistake this mechanism could invite.',
        danger=True,
    )
    _table(
        doc,
        ("While a position is quarantined", "What happens"),
        (
            ("A new entry in that symbol", "Refused."),
            (
                "A de-lever trim",
                "Refused - a trim sized against a wrong quantity is the trim " "doing the damage.",
            ),
            (
                "An ordinary exit",
                "ALLOWED, and re-sized from the broker rather than from the tracked "
                "quantity. Selling 16 of 64 shares would leave three quarters of a position "
                "nobody intended to keep.",
            ),
            (
                "Re-arming lost protection",
                "Refused. The recorded stop predates whatever caused the quarantine.",
            ),
            (
                "An exit when the broker cannot be read",
                "Refused, as a rejected order carrying a reason. Selling a quantity already "
                "known to be untrustworthy is worse than not selling.",
            ),
        ),
    )
    doc.add_paragraph(
        "An explanation is bound to the quantity the broker reported when it was declared. A "
        "difference declared at 16 shares becoming 64 does not explain a later 64 becoming "
        "128 - the position stops being explained while remaining quarantined, because it is "
        "no less suspect for having moved again."
    )

    doc.add_heading("12.5 Corporate Actions", level=2)
    doc.add_paragraph(
        "A share split changes the share count and the per-share price of a position you "
        "already hold. The resting protective stop does not change with it, and that is not "
        "a reporting problem."
    )
    _callout(
        doc,
        "What an unadjusted stop through a split actually costs",
        "Measured on this account on 11 August 2026. A 2-for-1 split on a held position: the "
        "broker halved the price to about $46 and never delivered the extra shares. The "
        "resting stop stayed at $72.68, roughly $26 above the market, and it executed at the "
        "open in three partials. The position closed for a real net loss of $375.23 - down "
        "51.4% on a position that should have been roughly flat.",
        danger=True,
    )
    doc.add_paragraph(
        "The application therefore reads the broker's corporate-action announcements for "
        "every symbol it holds, and re-prices the resting stop before the ex-date open. Two "
        "things about how it does that are worth knowing."
    )
    _table(
        doc,
        ("Rule", "Why"),
        (
            (
                "Only the stop is adjusted",
                "The share count and the recorded entry price are left alone until the "
                "broker actually reports the new shares. In the case measured above the "
                "shares never arrived, and halving the recorded entry price would have made "
                "a real loss look like a rounding artefact.",
            ),
            (
                "An adjustment that would tighten the stop is refused",
                "The new stop must sit below the market and no closer to it, in percentage "
                "terms, than the old one was. A wrong ratio can then leave a stop too far "
                "away, which costs more if the position runs against you - but it can never "
                "liquidate the position on contact.",
            ),
            (
                "A split announced before you bought is ignored",
                "A position opened after a split is already sized correctly. Adjusting it "
                "again would divide a correct stop by the ratio a second time.",
            ),
            (
                "New entries in that symbol are refused while it is pending",
                "The price and share count a size would be computed from are about to " "change.",
            ),
        ),
    )
    _callout(
        doc,
        "It ships in shadow mode",
        "QAT_CORPORATE_ACTION_MODE defaults to shadow: the split is detected, the adjustment "
        "is calculated, and the exact change it WOULD make is written to the log - but no "
        "order is touched. Read those log lines before setting it to act. Splits only; other "
        "corporate actions are logged and not adjusted.",
    )
    doc.add_paragraph(
        "The Dashboard shows a banner whenever an action is pending on a held position, and "
        "it says which mode is in force. The Risk Console shows the current stop, the "
        "adjusted stop, and whether the change was placed or only calculated. Both wordings "
        'are deliberate: "adjusted" and "would be adjusted" are different facts, and only '
        "one of them means the broker is holding a different order."
    )

    doc.add_heading("12.6 Distribution and Code Signing", level=2)
    doc.add_paragraph(
        "The packaged Windows build is Authenticode-signed with a timestamped signature, so "
        "Windows can verify its publisher and the signature remains valid after the signing "
        "certificate expires. If the build you have was produced without a certificate "
        "available, it will be unsigned and SmartScreen will warn on first launch; the "
        "project README documents the signing step."
    )


def _glossary(doc: Any) -> None:
    doc.add_page_break()
    doc.add_heading("Appendix A: Glossary", level=1)
    _table(
        doc,
        ("Term", "Definition"),
        (
            ("NAV", "Net Asset Value - cash plus the market value of open positions."),
            (
                "VaR",
                "Value-at-Risk - the loss a portfolio is not expected to exceed over one "
                "period at a stated confidence level.",
            ),
            (
                "Expected Shortfall (ES)",
                "The average loss in the tail beyond the VaR threshold.",
            ),
            ("Sharpe ratio", "Annualised excess return divided by annualised volatility."),
            ("Sortino ratio", "As Sharpe, but penalising only downside volatility."),
            ("CAGR", "Compound Annual Growth Rate."),
            ("Calmar ratio", "CAGR divided by the magnitude of maximum drawdown."),
            ("Maximum drawdown", "The largest peak-to-trough decline in an equity curve."),
            ("Win rate", "The percentage of closed trades that were profitable."),
            ("Profit factor", "Gross profit divided by gross loss across closed trades."),
            (
                "R multiple",
                "A trade's result expressed in units of the risk taken on it: +2R means "
                "twice the amount that was at risk if the stop had been hit.",
            ),
            ("Average R", "The mean R multiple across a strategy's closed trades."),
            ("Beta", "A strategy's sensitivity to the benchmark's returns."),
            ("Alpha", "Return in excess of what beta and the benchmark explain."),
            (
                "Monte Carlo cone",
                "A range of simulated equity paths from resampling a backtest's own trade "
                "returns, to show how much the result depended on trade order.",
            ),
            (
                "Regime",
                "One of seven classified market states: bull, bear, sideways, high_vol, "
                "low_vol, recession, recovery.",
            ),
            (
                "Exposure scalar",
                "The portfolio-wide position-sizing multiplier associated with the current "
                "regime.",
            ),
            (
                "Hysteresis gate",
                "A filter requiring a new regime to persist before the label changes, so it "
                "does not flicker on noisy data.",
            ),
            (
                "Kill-switch",
                "A control that immediately halts all new order flow; manual or "
                "automatically tripped.",
            ),
            (
                "Sign-off",
                "The explicit, human-attributed confirmation required before an order is "
                "transmitted.",
            ),
            (
                "Promotion",
                "Clearing a strategy to trade unattended, judged against the bar in "
                "Section 10.2.",
            ),
            ("Paper trading", "Simulated trading; no real money and no real orders."),
            (
                "Live trading",
                "Trading against a real connected broker; requires an explicit "
                "configuration change and confirmation.",
            ),
            (
                "SIP / IEX",
                "US market data feeds: SIP is the full consolidated tape, IEX a single "
                "exchange carrying a small share of consolidated volume.",
            ),
        ),
    )

    doc.add_heading("A.1 Order and Protection Terms", level=2)
    _table(
        doc,
        ("Term", "Definition"),
        (
            (
                "Bracket",
                "One submission carrying an entry plus both of its exits - a protective stop "
                "below and a profit target above. The exits attach at the broker in the same "
                "message, so there is no window in which the position exists unprotected.",
            ),
            (
                "OCO (one-cancels-other)",
                "Two linked orders where filling one automatically cancels the other. Used "
                "to put a stop and a target back on a position already held, where a bracket "
                "cannot be used because there is no entry left to attach to.",
            ),
            (
                "Protective stop",
                "A resting sell order that executes if the price falls to a set level. It "
                "bounds the loss on a position, and is held AT THE BROKER so that it "
                "survives this application closing.",
            ),
            (
                "Take-profit / target",
                "A resting sell order that executes if the price rises to a set level. "
                "Without one, a position can only be closed by its stop, its time stop, or a "
                "strategy exit signal.",
            ),
            (
                "GTC / DAY",
                "Good-Til-Cancelled and Day. A DAY order expires at the close; a GTC order "
                "rests until filled or cancelled. Protective orders are always GTC - a stop "
                "that expires overnight protects nothing overnight.",
            ),
            (
                "Held (order status)",
                "A broker status meaning an order is linked into an advanced order set and "
                "is waiting rather than working independently. An OCO stop leg typically "
                "shows as held while its partner is live. It is still real protection.",
            ),
            (
                "Resting order",
                "An order sitting at the broker waiting for its price condition. It consumes "
                "no cash and executes nothing until triggered.",
            ),
            (
                "Broker-side fill",
                "An execution the broker performed without this application sending an order "
                "- a resting stop or target being hit. It must be fetched deliberately, "
                "because nothing in this process observes it happening.",
            ),
            (
                "Adopted position",
                "A holding already in the account when a session started. Either something "
                "else put it there, or this application opened it in an earlier session and "
                "is resuming - the screen distinguishes the two.",
            ),
            (
                "Re-arm",
                "Replacing protection that has disappeared, using the stop and target the "
                "position was originally sized against.",
            ),
            (
                "Reconciliation",
                "Comparing this application's record of what it holds against what the "
                "broker reports. A mismatch it cannot explain trips the kill-switch, because "
                "a wrong view of the account makes every other calculation wrong too.",
            ),
        ),
    )

    doc.add_heading("A.2 Risk and Sizing Terms", level=2)
    _table(
        doc,
        ("Term", "Definition"),
        (
            (
                "ATR (Average True Range)",
                "How far an instrument typically moves in a period. Stop distances are set "
                "as a multiple of it, so a volatile name gets a wider stop and a "
                "correspondingly smaller position.",
            ),
            (
                "Risk-at-stop",
                "What a position would lose if it hit its stop - not what it is worth. A "
                "position whose protection is unknown counts its entire value instead.",
            ),
            (
                "Aggregate risk-at-stop",
                "The same figure summed across every open position: what the account loses "
                "if everything stops out at once. A per-trade limit says nothing about ten "
                "trades each individually within budget.",
            ),
            (
                "Gap budget",
                "A separate allowance for an overnight gap opening THROUGH a stop rather "
                "than trading to it. Measured on notional, because a gap moves the price "
                "past a level that never traded.",
            ),
            ("Single-name concentration", "The share of account equity in one ticker."),
            (
                "Sector concentration",
                "The share of account equity in one sector - a proxy for correlation that "
                "fails in a crisis, when apparently different sectors move together.",
            ),
            (
                "Correlated cluster",
                "Holdings whose returns actually track a candidate at or above a threshold, "
                "capped together. Measured rather than labelled: eight positions at high "
                "pairwise correlation are one position taken eight times.",
            ),
            (
                "Trim (versus reject)",
                "Reducing an order to the size a limit allows instead of refusing it. A cap "
                "that refuses rather than resizes stops a strategy trading entirely.",
            ),
            (
                "Kelly fraction",
                "A position size derived from win rate and payoff ratio. Used at a fraction "
                "of full Kelly, because full Kelly assumes the inputs are exactly right and "
                "reacts violently when they are not.",
            ),
            (
                "Edge estimate",
                "The win rate and win/loss ratio a strategy is sized on. Documented defaults "
                "until it has enough closed trades of its own, then its measured results, "
                "clamped so a small sample cannot set the risk.",
            ),
            (
                "Minimum holding period",
                "A floor on how long a position is held before a signal may close it, to "
                "stop commission costs accumulating on churn.",
            ),
            (
                "Time stop",
                "A forced exit on a position whose thesis never resolved, after a set number "
                "of trading days.",
            ),
            ("Turnover budget", "A cap on how many new positions may be opened in a week."),
            (
                "Commission floor",
                "A fixed minimum charge per transaction. Trivial on a large position and "
                "ruinous on a small one, which is why it must be modelled rather than "
                "approximated as a percentage.",
            ),
            (
                "Slippage",
                "The difference between the price a decision assumed and the price actually "
                "obtained.",
            ),
        ),
    )

    doc.add_heading("A.3 Data, Regime and Validation Terms", level=2)
    _table(
        doc,
        ("Term", "Definition"),
        (
            (
                "Warm start",
                "Seeding the rolling buffers from historical daily bars at launch, so the "
                "regime detector and the strategies work immediately instead of waiting days "
                "for live bars to accumulate.",
            ),
            (
                "Probability-mass gating",
                "Permitting a strategy on the total probability across the regimes it suits, "
                "rather than on the single most likely label. A strategy suited to three "
                "regimes holding 60 percent of the probability is not idle because a fourth "
                "holds 35 percent.",
            ),
            (
                "Staleness rail",
                "A check that a quote is recent enough to size a trade against. Applied per "
                "symbol - a thin or halted ticker is a reason to stop trading that symbol, "
                "never the whole account.",
            ),
            (
                "HMM (Hidden Markov Model)",
                "The statistical model behind regime classification: it infers which "
                "unobserved market state best explains the observed features.",
            ),
            (
                "Breadth",
                "The share of tracked symbols advancing - one of the features the regime "
                "detector reads.",
            ),
            (
                "Walk-forward",
                "Testing a strategy on consecutive out-of-sample windows to see whether a "
                "result holds up across periods rather than only in aggregate.",
            ),
            (
                "In-sample / out-of-sample",
                "Data a method was developed on versus data it has not seen. Only the second "
                "is evidence.",
            ),
            (
                "FIFO matching",
                "First-in-first-out pairing of sells against earlier buys, which determines "
                "which entry a closed trade's profit is measured from.",
            ),
            (
                "Decision journal",
                "The record of what was proposed and why, including refusals. Distinct from "
                "the trade ledger, which records only what actually happened.",
            ),
            (
                "Promotion gate",
                "The evidence bar a strategy must clear to trade unattended: a minimum "
                "number of closed trades, positive net P&L, and floors on win rate and "
                "average R. Always enforced on a live account.",
            ),
        ),
    )


def _config_reference(doc: Any) -> None:
    doc.add_page_break()
    doc.add_heading("Appendix B: Configuration Reference", level=1)
    doc.add_paragraph(
        "The Settings screen writes these for you - including every risk limit, which "
        "Section 11 covers. They are listed for reference and for the few settings that "
        "have no screen of their own. Secrets are never among them: API keys live only in "
        "the Windows Credential Manager."
    )
    _table(
        doc,
        ("Setting", "Default", "Meaning"),
        (
            ("QAT_TRADING_MODE", "paper", "paper or live."),
            ("QAT_EXECUTION_MODE", "recommend", "recommend or auto (Section 11.8)."),
            ("QAT_AUTONOMOUS_STRATEGIES", "(empty)", "Strategies cleared to auto-trade."),
            (
                "QAT_ALLOW_AUTONOMOUS_LIVE_TRADING",
                "false",
                "No screen exposes this. Kept separate from the trading mode so that "
                "unattended live trading needs a code change, not a configuration edit.",
            ),
            ("QAT_BROKER", "mock", "mock, alpaca or ibkr."),
            ("QAT_MIN_CASH_RESERVE", "1.00", "The cash floor a buy may never spend below."),
            ("QAT_MARKET_DATA_SOURCE", "synthetic", "synthetic, yfinance or alpaca."),
            ("QAT_FUNDAMENTALS_SOURCE", "mock", "mock or yfinance (Section 11.5)."),
            (
                "QAT_FUNDAMENTALS_CACHE_DAYS",
                "7",
                "How long a fetched fundamentals figure stays current.",
            ),
            ("QAT_ALPACA_DATA_FEED", "iex", "iex, sip or delayed_sip."),
            ("QAT_MARKET", "US", "US or ASX."),
            ("QAT_WATCHLIST_CATEGORY", "curated", "curated, etf or megacap."),
            ("QAT_WATCHLIST_MAX_SYMBOLS", "10", "How many symbols the live engines follow."),
            ("QAT_GENERAL_REQUEST_PROVIDER", "demo", "anthropic, local or demo."),
            ("QAT_SENSITIVE_REQUEST_PROVIDER", "demo", "local, anthropic or demo."),
            ("QAT_DAILY_LOSS_LIMIT_PCT", "0.03", "Daily loss that trips the kill-switch."),
            ("QAT_MAX_DRAWDOWN_LIMIT_PCT", "0.20", "Drawdown that trips the kill-switch."),
            ("QAT_PER_TRADE_RISK_PCT", "0.01", "Risk budget per trade, as a share of equity."),
            (
                "QAT_MAX_AGGREGATE_RISK_AT_STOP_PCT",
                "0.05",
                "Total loss if every open position hit its stop at once.",
            ),
            ("QAT_MAX_CONCURRENT_POSITIONS", "10", "Cap on open positions plus pending orders."),
            (
                "QAT_ENFORCE_PROMOTION_EVIDENCE",
                "false",
                "Makes the promotion bar binding for auto-trade (Section 10.1).",
            ),
            (
                "QAT_SESSION_FOLLOWS_MARKET_HOURS",
                "true",
                "Feed and strategies follow market hours (Section 3.2). Ignored on "
                "simulated prices.",
            ),
            (
                "QAT_WALK_FORWARD_IN_SAMPLE_BARS",
                "120",
                "Default in-sample window on the Workbench (Section 4.2).",
            ),
            ("QAT_WALK_FORWARD_OUT_SAMPLE_BARS", "60", "Default out-of-sample window."),
            (
                "QAT_HOME",
                "(per-user)",
                "Relocates settings and records wholesale (Section 11.10).",
            ),
            (
                "QAT_ACCOUNT_POLL_SECONDS",
                "5",
                "How often the shared account poller re-reads the broker (Section 3.3).",
            ),
            ("QAT_LOG_LEVEL", "INFO", "Logging verbosity. Written to data/logs/qat.log."),
            (
                "QAT_DEPLOYED_STRATEGIES",
                "(empty)",
                "Strategies evaluated at startup. Distinct from AUTONOMOUS_STRATEGIES: this "
                "decides whether a strategy runs at all, that one whether its orders may "
                "self-sign.",
            ),
            (
                "QAT_PER_TRADE_RISK_PCT",
                "0.01",
                "Share of equity risked between entry and stop on one trade.",
            ),
            (
                "QAT_MAX_AGGREGATE_RISK_AT_STOP_PCT",
                "0.05",
                "Total loss allowed if every open position stopped out at once.",
            ),
            (
                "QAT_MAX_SINGLE_NAME_CONCENTRATION_PCT",
                "0.15",
                "Cap on one ticker as a share of equity. Trimmed to, not refused at.",
            ),
            (
                "QAT_MAX_SECTOR_CONCENTRATION_PCT",
                "0.30",
                "Cap on one sector as a share of equity.",
            ),
            (
                "QAT_CORRELATION_CLUSTER_THRESHOLD",
                "0.70",
                "Return correlation at or above which a holding counts in a candidate's "
                "cluster.",
            ),
            (
                "QAT_MAX_CORRELATED_CLUSTER_PCT",
                "0.30",
                "Cap on a correlated cluster as a share of equity.",
            ),
            (
                "QAT_MAX_GAP_RISK_AT_SHOCK_PCT",
                "0.05",
                "Loss allowed from an overnight gap of GAP_SHOCK_PCT across all holdings.",
            ),
            ("QAT_GAP_SHOCK_PCT", "0.06", "The overnight gap size the budget is measured at."),
            (
                "QAT_MIN_HOLDING_TRADING_DAYS",
                "10",
                "Trading days before a signal may close a position.",
            ),
            (
                "QAT_TIME_STOP_TRADING_DAYS",
                "30",
                "Trading days after which an unresolved position is exited.",
            ),
            (
                "QAT_PROTECTION_SWEEP_SECONDS",
                "300",
                "How often held positions are re-checked for missing protection " "(Section 8A.2).",
            ),
            (
                "QAT_IBKR_CALL_TIMEOUT_SECONDS",
                "60",
                "How long any single request to IBKR may take before it is abandoned. The "
                "adapter previously had no timeout on any of its calls, so a lost response "
                "hung whatever rail made it for the life of the process - which is what "
                "silently stopped reconciliation for a whole session on 25 August.",
            ),
            (
                "QAT_IBKR_PERMID_WAIT_SECONDS",
                "5",
                "How long placing an order waits for TWS to report the order's permanent "
                "id before giving up and keeping the app's own id. IBKR's own placeOrder "
                "call returns before TWS has acknowledged, so the permId is briefly absent; "
                "without this wait the app's own id stayed on the order and its fill later "
                "arrived under the permId instead, unrecognised - the cause of the 26 August "
                "double-count. Zero switches the wait off entirely.",
            ),
            (
                "QAT_RECONCILIATION_POLL_TIMEOUT_SECONDS",
                "120",
                "How long one reconciliation poll may take before it is declared hung. A "
                "healthy poll takes about a second. On 25 August the poll wedged and "
                "completed none of the twenty due in the next seven hours, saying nothing, "
                "because a hung await raises nothing - and every rail behind it was off "
                "meanwhile, including the absorbing of broker-side fills.",
            ),
            (
                "QAT_RESTING_ORDER_RECONCILE_ENABLED",
                "true",
                "Whether orders resting at the broker are checked against what the book "
                "justifies. On 24 August sixteen orphaned bracket legs rested against a FLAT "
                "position and nothing was watching. Observes and quarantines; cancels nothing.",
            ),
            (
                "QAT_RESTING_ORDER_CANCEL_ENABLED",
                "false",
                "Whether that check may CANCEL what it finds, and only where the book holds "
                "none of the symbol. Off by default: acting on the account unattended is not "
                "granted implicitly. A held symbol is never trimmed.",
            ),
            (
                "QAT_EDGE_MIN_TRADES",
                "20",
                "Closed trades a strategy needs before its own results size its trades "
                "rather than the defaults.",
            ),
            (
                "QAT_BROKER_MIN_COMMISSION",
                "6.60",
                "Fixed minimum charge per transaction, applied in backtests and live cost "
                "estimates alike.",
            ),
            # --- the interface's own level ---------------------------------
            (
                "QAT_UI_LEVEL",
                "standard",
                "guided, standard or professional. Not cosmetic: the Workbench's deploy "
                "button is professional-only and the Blotter's bulk sign-off is standard "
                "and above, so a reset to the default REMOVES controls that were there "
                "before. Section 11.9 covers what each level shows.",
            ),
            # --- corporate actions -----------------------------------------
            (
                "QAT_CORPORATE_ACTION_MODE",
                "shadow",
                "shadow or act. In shadow a split is detected and the adjustment it WOULD "
                "make is written to the log, and no order is touched. In act the resting "
                "stop is re-priced before the ex-date open. See Section 12.5 - an "
                "unadjusted stop through a split cost this account $375.23.",
            ),
            # --- the churn rails, which decide when a position may leave ----
            (
                "QAT_ENFORCE_MIN_HOLDING_PERIOD",
                "true",
                "Whether MIN_HOLDING_TRADING_DAYS binds at all. Only signal-driven exits "
                "are held back; a resting stop, the de-lever sweep and the kill-switch "
                "take other paths and are never delayed.",
            ),
            (
                "QAT_MIN_HOLDING_LOSS_ESCAPE_R",
                "0.50",
                "How far down, in R, a position may be before the minimum hold stops "
                "applying. Without this the rail would sit through a broken thesis to "
                "save a commission.",
            ),
            (
                "QAT_ENFORCE_TIME_STOP",
                "true",
                "Whether TIME_STOP_TRADING_DAYS binds at all.",
            ),
            (
                "QAT_MAX_ENTRIES_PER_WEEK",
                "10",
                "Turnover budget. Ten positions turned over weekly costs about 6.2% of a "
                "$100k account in commission before a single losing trade.",
            ),
            (
                "QAT_NEWS_SOURCE",
                "yfinance",
                "Where company news for the AI Advisor and the Strategy Workbench comes "
                "from: none, or yfinance (free, no key). ON by default since M126 - IBKR "
                "returned zero headlines for ASX names over 90 days, listcorp refuses "
                "bots and ASX ComNews is licensed, so Yahoo is the only free source that "
                "returns anything on .AX at all. Set to none to stop fetching entirely; "
                "the screen then says so, rather than showing an empty list that could "
                "mean either.",
            ),
            (
                "QAT_NEWS_MIN_SOURCES",
                "1",
                "How many INDEPENDENT outlets must carry a story before it is shown to "
                "the model. Set to 2 to require corroboration, which is what shipped "
                "before 21 August; it was loosened to 1 because on ASX names it was "
                "surfacing nothing at all - Yahoo's coverage, not the threshold, is the "
                "binding limit. At 1, a single planted story can reach the model, so "
                "read the outlet names the screen prints beside each story. Either way "
                "the check runs in code before the text is sent, never by asking the "
                "model whether its sources agree, and a company's own exchange filing "
                "has never been held to this bar.",
            ),
            (
                "QAT_MAX_ORDER_PCT_OF_CASH",
                "0.10",
                "The largest share of AVAILABLE CASH one order may spend, 0 to 1. A buy "
                "above it is TRIMMED to fit, not refused - the same way the single-name "
                "concentration cap has worked since M31c. EXITS ARE EXEMPT: a cap that "
                "refused a sell meant a position bigger than the cap could not be closed "
                "at all, and a trimmed sell would leave a residual you believe is closed. "
                "A FRACTION rather than a sum on purpose - it replaced a flat $50,000 that "
                "never grew with the account and refused every entry once the balance "
                "passed about $333,000. Cash rather than equity because on a live account "
                "cash is what actually constrains a purchase, and liquidity bites long "
                "before the balance does. Set 0 to stop opening new positions while "
                "letting the existing book run off; set 1 to disable the cap. If the "
                "broker does not report cash the order is REFUSED, not waved through.",
            ),
            (
                "QAT_MACRO_GROWTH_SERIES",
                "(empty)",
                "The FRED series the macro regime matrix reads its GROWTH axis from - for "
                "example GDPC1 for US real GDP, or INDPRO for US industrial production. "
                "EMPTY BY DEFAULT, AND DELIBERATELY: every regime in that matrix keys on "
                "growth, and this application has never measured any. What it has is PRICE "
                "TREND against a 50-day average, which describes a share index rather than "
                "an economy, and reading one as the other would put a market's momentum "
                "where a country's output belongs. Until a series is named there is NO "
                "growth axis, and the matrix REFUSES the regimes that need one rather than "
                "approximating them - so a blank here costs you the recession and recovery "
                "readings and nothing else. CHOOSING THIS ALSO CHOOSES AN ECONOMY: this "
                "account trades the ASX, and every FRED series already polled is American, "
                "so a US growth reading steering an Australian book is a decision to make "
                "on purpose rather than inherit. AND EVERY CANDIDATE IS LAGGED - real GDP "
                "is quarterly and published a month or more after the quarter closes, "
                "Australian GDP later still, so a reading can be five months old before it "
                "moves at all. The screen reports how old the figure is; read that before "
                "acting on it.",
            ),
            (
                "QAT_MACRO_RISK_MANDATE",
                "moderate",
                "Risk appetite for the MACRO REGIME MATRIX, the deterministic read that "
                "proposes an exposure target from volatility and market conditions. Three "
                "named mandates, each fixing the RISK SCALING UNIT the matrix scales "
                "its proposed exposure shifts by: CONSERVATIVE (0.10) for wealth "
                "preservation or a regulated client account; MODERATE (0.20), the balanced "
                "baseline and the default; AGGRESSIVE (0.35) for absolute-return mandates "
                "using heavy leverage or large cash swings. THIS IS A SCALING UNIT, NOT A "
                "CAP. It sets how hard the portfolio leans into a given deviation from "
                "normal volatility - a higher unit means a larger shift for the same "
                "signal - and total swings are DYNAMIC and CAN EXCEED it under extreme "
                "market stress, deliberately, so that downside protection stays adequate "
                "when it matters most. In practice a bear-market cut is unbounded above, "
                "the recovery case adds a further 5%, the volatility-shock case is a flat "
                "10% regardless, and the recession case halves the baseline outright. Read "
                "the figure the screen reports rather than assuming a boundary. A NAMED "
                'MANDATE rather than a free number on purpose - "why is the unit 0.27?" '
                'has no answer anyone can audit afterwards, where "the account is on a '
                'conservative mandate" does. AN UNRECOGNISED VALUE IS A STARTUP ERROR, '
                "not a silent fallback to the default: an account running at a "
                "responsiveness nobody chose is the failure this refuses. ADVISORY ONLY - "
                "the matrix computes and the OPERATOR decides whether to act. Nothing it "
                "produces reaches the risk engine, the sizer or any order path, and that "
                "is a standing instruction rather than a current limitation.",
            ),
            (
                "QAT_BROKER_MAX_ORDER_SHARES",
                "(unset)",
                "The largest SHARE COUNT the broker will accept without holding the order "
                "for manual confirmation. An order above it is TRIMMED to it, the same way "
                "the cash cap trims. UNSET BY DEFAULT, and unset means nothing is trimmed - "
                "a shipped default would impose one particular TWS installation's "
                "configuration on every other one. This limit is NOT queryable through the "
                "IBKR API: it lives in TWS's own Precautionary Settings, so the application "
                "cannot discover it and has to be told. It matters because exceeding it does "
                "not produce a clean refusal - on 3 September a 790-share order was STAGED "
                "for confirmation rather than transmitted, while the application booked a "
                "position the exchange never took. DO NOT SIMPLY COPY THE NUMBER OUT OF THE "
                "TWS DIALOG: on 4 September that dialog read 20,000 while the broker "
                "accepted a 64,229-share order, so the figure on screen is not always the "
                "one enforced, and setting it here would have cut a legitimate position by "
                "69%. The number to trust is the one in IBKR's own Error 383 text, which the "
                "application reads back and warns about whenever it disagrees with this "
                "setting - or when the broker enforces a limit and this is unset.",
            ),
            (
                "QAT_ENTRY_ALLOW_LIST",
                "(empty)",
                "Symbols that may be newly ENTERED. Empty means no restriction. Distinct "
                "from the symbol allow list, which governs holding as well.",
            ),
            (
                "QAT_ALLOW_SHORT_SELLING",
                "false",
                "Long-only by default: a sell signal in a symbol not held is dropped "
                "rather than opening a short.",
            ),
            # --- sizing ------------------------------------------------------
            (
                "QAT_ATR_STOP_MULTIPLE",
                "2.5",
                "ATR multiples below entry for the stop a strategy did not propose one "
                "for. The stop distance sets the position size, so this scales every "
                "trade.",
            ),
            (
                "QAT_KELLY_FRACTION",
                "0.25",
                "The fraction of the Kelly criterion sizing uses. Full Kelly is far too "
                "aggressive for a real book.",
            ),
            (
                "QAT_REGIME_ELIGIBILITY_MASS",
                "0.50",
                "Combined probability a strategy's suitable regimes must carry before it "
                "may trade. Gates on the distribution rather than on the single most "
                "likely label.",
            ),
            # --- the cost rails ---------------------------------------------
            (
                "QAT_MAX_COST_TO_RISK_PCT",
                "0.10",
                "Round-trip cost as a share of the dollars at risk, above which a trade "
                "is refused for being too small to carry its fees. Measured against risk "
                "rather than notional, because every order has a stop.",
            ),
            (
                "QAT_COMMISSION_BPS",
                "1.0",
                "Modelled commission. Applies in paper too - see APPLY_COSTS_IN_PAPER.",
            ),
            (
                "QAT_SLIPPAGE_BPS",
                "5.0",
                "Modelled slippage, flat regardless of size, spread or time of day. Every "
                "closed trade records what the gap actually was, so the assumption can be "
                "checked rather than trusted.",
            ),
            (
                "QAT_APPLY_COSTS_IN_PAPER",
                "true",
                "Alpaca paper charges nothing, so without this a commission-free strategy "
                "could be measured and promoted onto a broker with a minimum charge, "
                "where the same trades lose money.",
            ),
            # --- event risk ---------------------------------------------------
            (
                "QAT_ENFORCE_EARNINGS_EVENT_RISK",
                "true",
                "Whether the earnings rail binds. A scheduled print is not a draw from "
                "the usual distribution.",
            ),
            (
                "QAT_EARNINGS_BLACKOUT_DAYS",
                "5",
                "Trading days either side of a print within which a trade is sized down.",
            ),
            (
                "QAT_EARNINGS_EVENT_SIZE_SCALAR",
                "0.50",
                "What a trade inside the blackout window is sized at.",
            ),
            (
                "QAT_DATA_STALENESS_SECONDS",
                "900",
                "How old a symbol's last print may be before that symbol is dropped from "
                "signal generation, measured BEYOND the feed's own delay below. It never "
                "halts the account - only the stale symbol stops being traded.",
            ),
            (
                "QAT_MARKET_DATA_DELAY_SECONDS",
                "1200",
                "How far behind the market the price feed structurally is. This is a claim "
                "about the vendor, not a tolerance: Yahoo publishes ASX intraday about "
                "twenty minutes late, measured on 21 August 2026 when the market opened at "
                "10:00 and the first bars appeared at 10:22. Staleness is measured beyond "
                "it, so raising it BLINDS the staleness rail by exactly that much, and "
                "lowering it below the real delay makes every symbol read as permanently "
                "stale and stops the system trading at all. Change it only if the vendor's "
                "delay is re-measured and found to have changed.",
            ),
            # --- the de-lever sweep -----------------------------------------
            (
                "QAT_DELEVER_SWEEP_ENABLED",
                "false",
                "Whether the sweep may TRIM positions on its own. Off by default: "
                "unwinding on its own judgement is a larger authority than refusing to "
                "add, and it is not granted implicitly.",
            ),
            (
                "QAT_DELEVER_TARGET_FRACTION_OF_CAP",
                "0.90",
                "What the sweep trims back to. Landing exactly on the cap re-triggers it "
                "on the next tick.",
            ),
            (
                "QAT_PORTFOLIO_ES_LIMIT_PCT",
                "0.06",
                "Expected-shortfall limit for the whole book.",
            ),
            (
                "QAT_BOOK_RISK_POLL_SECONDS",
                "60",
                "How often portfolio risk is re-measured over the holdings actually held. "
                "Matches the equity poll interval; the monitor reads the shared, throttled "
                "account poller rather than the broker, so changing this does not increase "
                "broker traffic.",
            ),
            (
                "QAT_BOOK_RISK_MIN_OBSERVATIONS",
                "30",
                "Overlapping daily return observations required before VaR and Expected "
                "Shortfall are reported as actual figures. Below this they read as UNKNOWN "
                "with a note. A floor of 2 is always enforced: the underlying computation "
                "returns 0.0 below two observations, and a zero reaching the AI advisory "
                "reads as 'no tail risk' about a book that could not be measured. Not a "
                "tuning knob.",
            ),
            (
                "QAT_BOOK_RISK_MAX_AGE_SECONDS",
                "180",
                "A risk measurement older than this is treated exactly as a missing one. "
                "The age is measured against the measurement's own timestamp, not the "
                "moment of computation, so a stale broker snapshot cannot be re-dated as "
                "current. Three polls at the default interval.",
            ),
            # --- the promotion gate, which the trial exists to satisfy -------
            (
                "QAT_PROMOTION_MIN_TRADES",
                "30",
                "Closed trades a strategy needs, PER STRATEGY, before its evidence counts. "
                "A trade with no strategy attribution counts towards nothing.",
            ),
            (
                "QAT_PROMOTION_MIN_AVERAGE_R",
                "0.20",
                "Average R a strategy must achieve to stay promoted.",
            ),
            (
                "QAT_PROMOTION_MIN_WIN_RATE",
                "0.40",
                "Win rate a strategy must achieve to stay promoted.",
            ),
            (
                "QAT_PROMOTION_MAX_LOSS_TO_AVG_WIN",
                "3.0",
                "How large the worst single loss may be against the average win.",
            ),
            # --- autonomy's own thresholds ----------------------------------
            (
                "QAT_AUTONOMOUS_PAUSE_BUYS_BELOW_DAY_PNL_PCT",
                "-0.04",
                "Day P&L at or below which unattended BUYS stop. Exits are never paused.",
            ),
            (
                "QAT_AUTONOMOUS_HALVE_SIZE_BELOW_DAY_PNL_PCT",
                "-0.02",
                "Day P&L at or below which an unattended buy is halved rather than " "blocked.",
            ),
            (
                "QAT_AUTONOMOUS_PRICE_DRIFT_LIMIT_PCT",
                "0.03",
                "How far price may move from the level an order was sized against before "
                "sign-off refuses it as stale.",
            ),
        ),
    )
