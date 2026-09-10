"""Symbol -> listed entity name for every symbol in the universe (spec M13).

Same static-snapshot caveat as data/universe.py and data/sectors.py, and it
matters slightly more here: company names change on rebrands, mergers and
delistings, and this table is a point-in-time snapshot rather than a live
vendor lookup. Known examples already in this table: Alumina Limited (AWC.AX)
was acquired by Alcoa and delisted in 2024, and Incitec Pivot (IPL.AX)
rebranded to Dyno Nobel in 2025. They are retained so the symbol lists in
universe.py resolve to *something* rather than falling back to the raw
ticker; replace this module with a real vendor lookup when one is wired up.

name_for() never raises and never returns an empty string - an unknown symbol
gets the symbol back, so callers can render the result unconditionally.
"""

from __future__ import annotations

UNKNOWN_NAME = ""

_US_NAMES: dict[str, str] = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corporation",
    "NVDA": "NVIDIA Corporation",
    "AMZN": "Amazon.com, Inc.",
    "GOOGL": "Alphabet Inc. (Class A)",
    "GOOG": "Alphabet Inc. (Class C)",
    "META": "Meta Platforms, Inc.",
    "AVGO": "Broadcom Inc.",
    "TSLA": "Tesla, Inc.",
    "BRK.B": "Berkshire Hathaway Inc. (Class B)",
    "LLY": "Eli Lilly and Company",
    "JPM": "JPMorgan Chase & Co.",
    "V": "Visa Inc.",
    "UNH": "UnitedHealth Group Incorporated",
    "XOM": "Exxon Mobil Corporation",
    "MA": "Mastercard Incorporated",
    "COST": "Costco Wholesale Corporation",
    "HD": "The Home Depot, Inc.",
    "PG": "The Procter & Gamble Company",
    "JNJ": "Johnson & Johnson",
    "NFLX": "Netflix, Inc.",
    "ABBV": "AbbVie Inc.",
    "BAC": "Bank of America Corporation",
    "KO": "The Coca-Cola Company",
    "MRK": "Merck & Co., Inc.",
    "ORCL": "Oracle Corporation",
    "CRM": "Salesforce, Inc.",
    "ADBE": "Adobe Inc.",
    "AMD": "Advanced Micro Devices, Inc.",
    "PEP": "PepsiCo, Inc.",
    "TMO": "Thermo Fisher Scientific Inc.",
    "ABT": "Abbott Laboratories",
    "CSCO": "Cisco Systems, Inc.",
    "ACN": "Accenture plc",
    "MCD": "McDonald's Corporation",
    "DHR": "Danaher Corporation",
    "LIN": "Linde plc",
    "WFC": "Wells Fargo & Company",
    "TXN": "Texas Instruments Incorporated",
    "IBM": "International Business Machines Corporation",
    "GE": "GE Aerospace",
    "CAT": "Caterpillar Inc.",
    "VZ": "Verizon Communications Inc.",
    "CMCSA": "Comcast Corporation",
    "PM": "Philip Morris International Inc.",
    "NKE": "NIKE, Inc.",
    "UNP": "Union Pacific Corporation",
    "HON": "Honeywell International Inc.",
    "QCOM": "QUALCOMM Incorporated",
    "INTU": "Intuit Inc.",
    "WMT": "Walmart Inc.",
    "DIS": "The Walt Disney Company",
    "NOW": "ServiceNow, Inc.",
    "INTC": "Intel Corporation",
    "BA": "The Boeing Company",
    "RTX": "RTX Corporation",
    "LOW": "Lowe's Companies, Inc.",
    "SBUX": "Starbucks Corporation",
    "MDT": "Medtronic plc",
    "GS": "The Goldman Sachs Group, Inc.",
    "MS": "Morgan Stanley",
    "BLK": "BlackRock, Inc.",
    "AXP": "American Express Company",
    "SPGI": "S&P Global Inc.",
    "SCHW": "The Charles Schwab Corporation",
    "C": "Citigroup Inc.",
    "PGR": "The Progressive Corporation",
    "PLTR": "Palantir Technologies Inc.",
    "AMAT": "Applied Materials, Inc.",
    "MU": "Micron Technology, Inc.",
    "ADI": "Analog Devices, Inc.",
    "LRCX": "Lam Research Corporation",
    "KLAC": "KLA Corporation",
    "PANW": "Palo Alto Networks, Inc.",
    "CRWD": "CrowdStrike Holdings, Inc.",
    "ISRG": "Intuitive Surgical, Inc.",
    "VRTX": "Vertex Pharmaceuticals Incorporated",
    "REGN": "Regeneron Pharmaceuticals, Inc.",
    "GILD": "Gilead Sciences, Inc.",
    "BMY": "Bristol-Myers Squibb Company",
    "PFE": "Pfizer Inc.",
    "CVS": "CVS Health Corporation",
    "SYK": "Stryker Corporation",
    "DE": "Deere & Company",
    "LMT": "Lockheed Martin Corporation",
    "NOC": "Northrop Grumman Corporation",
    "UPS": "United Parcel Service, Inc.",
    "MMM": "3M Company",
    "DUK": "Duke Energy Corporation",
    "SO": "The Southern Company",
    "NEE": "NextEra Energy, Inc.",
    "SHW": "The Sherwin-Williams Company",
    "FCX": "Freeport-McMoRan Inc.",
    "NEM": "Newmont Corporation",
    "TJX": "The TJX Companies, Inc.",
    "BKNG": "Booking Holdings Inc.",
    "MAR": "Marriott International, Inc.",
    "GM": "General Motors Company",
    "F": "Ford Motor Company",
    "MO": "Altria Group, Inc.",
    "SPY": "SPDR S&P 500 ETF Trust",
    "QQQ": "Invesco QQQ Trust, Series 1",
}

_ASX_NAMES: dict[str, str] = {
    "BHP.AX": "BHP Group Limited",
    "CBA.AX": "Commonwealth Bank of Australia",
    "CSL.AX": "CSL Limited",
    "NAB.AX": "National Australia Bank Limited",
    "WBC.AX": "Westpac Banking Corporation",
    "ANZ.AX": "ANZ Group Holdings Limited",
    "WES.AX": "Wesfarmers Limited",
    "WOW.AX": "Woolworths Group Limited",
    "TLS.AX": "Telstra Group Limited",
    "RIO.AX": "Rio Tinto Limited",
    "FMG.AX": "Fortescue Ltd",
    "MQG.AX": "Macquarie Group Limited",
    "GMG.AX": "Goodman Group",
    "TCL.AX": "Transurban Group",
    "WDS.AX": "Woodside Energy Group Ltd",
    "STO.AX": "Santos Limited",
    "QBE.AX": "QBE Insurance Group Limited",
    "SUN.AX": "Suncorp Group Limited",
    "ALL.AX": "Aristocrat Leisure Limited",
    "COL.AX": "Coles Group Limited",
    "XRO.AX": "Xero Limited",
    "REA.AX": "REA Group Ltd",
    "COH.AX": "Cochlear Limited",
    "RMD.AX": "ResMed Inc.",
    "APA.AX": "APA Group",
    "ORG.AX": "Origin Energy Limited",
    "AMC.AX": "Amcor plc",
    "BXB.AX": "Brambles Limited",
    "IAG.AX": "Insurance Australia Group Limited",
    "QAN.AX": "Qantas Airways Limited",
    "JHX.AX": "James Hardie Industries plc",
    "NST.AX": "Northern Star Resources Ltd",
    "S32.AX": "South32 Limited",
    "MIN.AX": "Mineral Resources Limited",
    "PLS.AX": "Pilbara Minerals Limited",
    "TWE.AX": "Treasury Wine Estates Limited",
    "SCG.AX": "Scentre Group",
    "MGR.AX": "Mirvac Group",
    "GPT.AX": "GPT Group",
    "VCX.AX": "Vicinity Centres",
    "ASX.AX": "ASX Limited",
    "SEK.AX": "Seek Limited",
    "CPU.AX": "Computershare Limited",
    "ORI.AX": "Orica Limited",
    "AGL.AX": "AGL Energy Limited",
    "BEN.AX": "Bendigo and Adelaide Bank Limited",
    "SGP.AX": "Stockland",
    "LLC.AX": "Lendlease Group",
    "IGO.AX": "IGO Limited",
    "WOR.AX": "Worley Limited",
    "WTC.AX": "WiseTech Global Limited",
    "TNE.AX": "Technology One Limited",
    "NXT.AX": "NEXTDC Limited",
    "CAR.AX": "CAR Group Limited",
    "DHG.AX": "Domain Holdings Australia Limited",
    "PME.AX": "Pro Medicus Limited",
    "RHC.AX": "Ramsay Health Care Limited",
    "SHL.AX": "Sonic Healthcare Limited",
    "FPH.AX": "Fisher & Paykel Healthcare Corporation Limited",
    "EDV.AX": "Endeavour Group Limited",
    "A2M.AX": "The a2 Milk Company Limited",
    "BKW.AX": "Brickworks Limited",
    "ILU.AX": "Iluka Resources Limited",
    "LYC.AX": "Lynas Rare Earths Limited",
    "EVN.AX": "Evolution Mining Limited",
    "WHC.AX": "Whitehaven Coal Limited",
    "NHC.AX": "New Hope Corporation Limited",
    "KAR.AX": "Karoon Energy Ltd",
    # Acquired by Alcoa and delisted in 2024 - see module docstring.
    "AWC.AX": "Alumina Limited",
    "BSL.AX": "BlueScope Steel Limited",
    "ORA.AX": "Orora Limited",
    "CIA.AX": "Champion Iron Limited",
    "DXS.AX": "Dexus",
    "CHC.AX": "Charter Hall Group",
    "ARF.AX": "Arena REIT",
    "GOZ.AX": "Growthpoint Properties Australia",
    "NSR.AX": "National Storage REIT",
    "HVN.AX": "Harvey Norman Holdings Limited",
    "JBH.AX": "JB Hi-Fi Limited",
    "SUL.AX": "Super Retail Group Limited",
    "PMV.AX": "Premier Investments Limited",
    "FLT.AX": "Flight Centre Travel Group Limited",
    "WEB.AX": "Web Travel Group Limited",
    "DMP.AX": "Domino's Pizza Enterprises Limited",
    "TAH.AX": "Tabcorp Holdings Limited",
    "LOV.AX": "Lovisa Holdings Limited",
    "BOQ.AX": "Bank of Queensland Limited",
    "BWP.AX": "BWP Trust",
    "AMP.AX": "AMP Limited",
    "MPL.AX": "Medibank Private Limited",
    "NHF.AX": "NIB Holdings Limited",
    "HUB.AX": "HUB24 Limited",
    "PNI.AX": "Pinnacle Investment Management Group Limited",
    "MFG.AX": "Magellan Financial Group Limited",
    "GQG.AX": "GQG Partners Inc.",
    "CGF.AX": "Challenger Limited",
    "AZJ.AX": "Aurizon Holdings Limited",
    "SVW.AX": "Seven Group Holdings Limited",
    # Rebranded to Dyno Nobel in 2025 - see module docstring.
    "IPL.AX": "Incitec Pivot Limited",
    "ALQ.AX": "ALS Limited",
    # The five M161 added to the megacap watchlist. Their SECTORS were fixed in
    # M162 and their NAMES were not, so the Screener rendered the ticker in the
    # Name column until 10 September - `name_for` falls back to the symbol, so
    # nothing raised and no cell was blank.
    #
    # Identities confirmed against IBKR `ContractDetails.longName`, read-only,
    # 10 September 2026. ⚠️ The broker's STRINGS were not copied: it answers
    # in upper case with abbreviated suffixes, and truncates at 28 characters -
    # "CLEANAWAY WASTE MANAGEMENT L". Checked by re-reading two symbols already
    # in this table, which came back "AURIZON HOLDINGS LTD" and "ALS LTD"
    # against the "Limited" spelled out here. So IBKR settles WHICH company;
    # the rendering follows this module's own convention.
    # No "Limited": ALX is a STAPLED security (Atlas Arteria Limited stapled to
    # Atlas Arteria International Limited), so no single entity carries the
    # name. IBKR answers bare "ATLAS ARTERIA" for the same reason. The only
    # entry here that deviates from the suffix pattern, deliberately.
    "ALX.AX": "Atlas Arteria",
    "CWY.AX": "Cleanaway Waste Management Limited",
    "SDF.AX": "Steadfast Group Limited",
    "SOL.AX": "Washington H. Soul Pattinson and Company Limited",
    "ANN.AX": "Ansell Limited",
    "STW.AX": "SPDR S&P/ASX 200 Fund",
    "IOZ.AX": "iShares Core S&P/ASX 200 ETF",
}

INSTRUMENT_NAMES: dict[str, str] = {**_US_NAMES, **_ASX_NAMES}


def name_for(symbol: str) -> str:
    """The listed entity's full name, or the symbol itself when unknown.

    Falls back to the symbol rather than an empty string so a caller can render
    this straight into a table cell without a None/blank check - an unknown
    ticker shows as itself, which is more useful than a gap.
    """
    if not symbol:
        return UNKNOWN_NAME
    return INSTRUMENT_NAMES.get(symbol.upper(), symbol)


def has_name(symbol: str) -> bool:
    """True when a real name is known, as opposed to name_for()'s symbol echo."""
    return bool(symbol) and symbol.upper() in INSTRUMENT_NAMES
