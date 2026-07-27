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

VERSION_LINE = "Version 2.3  |  Milestone M20"
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
    _workbench(doc, figures)
    _walk_forward(doc)
    _regime_monitor(doc, figures)
    _risk_console(doc, figures)
    _ai_advisor(doc, figures)
    _blotter(doc, figures)
    _screener(doc, figures)
    _performance(doc, figures)
    _session_record(doc)
    _settings(doc, figures)
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
        "auto-trade mode (Section 11.6) is the single deliberate exception, is confined to "
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
                "The packaged build is now Authenticode-signed and timestamped " "(Section 12.4).",
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
                "Alpaca (paper broker and US market data), Interactive Brokers via "
                "Gateway or TWS, Anthropic's API, a local LM Studio server, and FRED for "
                "macro series.",
            ),
            (
                "Where configuration lives",
                "Non-secret settings in a .env file written by the Settings screen; API "
                "keys and secrets only ever in the Windows Credential Manager, never in "
                ".env and never in logs.",
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
                "NAV tile",
                "Net Asset Value: cash plus the market value of open positions, as "
                "reported by the connected broker.",
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
                "existing positions.",
            ),
            (
                "Portfolio VaR (95%) and (99%) tiles",
                "Historical Value-at-Risk at each confidence level, from the live return "
                "history of the current portfolio.",
            ),
            (
                "Expected Shortfall (97.5%) tile",
                "The average loss in the tail beyond the 97.5% VaR threshold - what a bad "
                "day costs when it is bad, rather than how often.",
            ),
            (
                "Single-name concentration tile",
                "The largest single position's share of total equity, against the "
                "configured cap.",
            ),
            (
                "Correlation table",
                "Pairwise trailing-return correlation across the watchlist, colour-coded. "
                "High correlation means position limits are counting exposures that are "
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
        "fundamentals source (Section 11.6); sectors are always real, from a curated map. On "
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


def _settings(doc: Any, figures: FigureSet) -> None:
    doc.add_page_break()
    doc.add_heading("11. Settings", level=1)
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

    doc.add_heading("11.6 Execution Mode", level=2)
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

    doc.add_heading("12.4 Distribution and Code Signing", level=2)
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


def _config_reference(doc: Any) -> None:
    doc.add_page_break()
    doc.add_heading("Appendix B: Configuration Reference", level=1)
    doc.add_paragraph(
        "The Settings screen writes these for you. They are listed for reference and for "
        "the settings that have no screen of their own. Secrets are never among them: API "
        "keys live only in the Windows Credential Manager."
    )
    _table(
        doc,
        ("Setting", "Default", "Meaning"),
        (
            ("QAT_TRADING_MODE", "paper", "paper or live."),
            ("QAT_EXECUTION_MODE", "recommend", "recommend or auto (Section 11.6)."),
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
            ("QAT_LOG_LEVEL", "INFO", "Logging verbosity. Written to data/logs/qat.log."),
        ),
    )
