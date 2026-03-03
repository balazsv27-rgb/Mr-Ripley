Mr. Ripley — Layer-2 Truth Layer
What We Built & How to Use It

For: Friend / collaborator reading this on GitHub
Repo: https://github.com/balazsv27-rgb/Mr-Ripley
Last updated: March 2026


1. What Is Layer-2?
Layer-2 is the data ingestion and truth store for the Gold-First Market State Engine (Mr. Ripley).
Think of it as the foundation of the whole system:
Layer-1  ->  Raw data sources (FRED, Yahoo, Stooq, State Street)
Layer-2  ->  Ingestion + validation + immutable snapshots  <- YOU ARE HERE
Layer-3  ->  Feature builder + index suite + decision engine
The golden rule of Layer-2:
Layer-3 is NEVER allowed to read "latest" data directly. It can ONLY consume a published
snapshot_id. If data is missing or stale -> no snapshot is published -> Layer-3 outputs
nothing. This is called fail-closed behavior.

2. Folder Structure
Mr-Ripley/
├── FRED/                              # Historical FRED data dumps
│   ├── 2014GOLD/                      # Gold price backfill data
│   │   ├── gold_xauusd_stooq_2014_yesterday.json  # 3,132 daily gold prices
│   │   └── backfill_gold_stooq.py                 # Script used to collect it
│   ├── all_series_merged.json         # FRED metadata catalogue (149,595 series)
│   └── gold_sereies.json              # FRED gold series metadata
│                                      # note: filename has a typo — do not rename
├── layer2/                            # Everything we built
│   ├── adapters/
│   │   ├── gold_adapter.py            # Gold price XAUUSD ingestion (Tier-1)
│   │   ├── move_adapter.py            # MOVE index ingestion (Tier-1)
│   │   └── gld_holdings_adapter.py   # GLD ounces held (Tier-2)
│   ├── config/
│   │   └── series_registry.json      # Master list of series (currently: MOVE + GLD only)
│   └── README_LAYER2.md              # This file
├── layer2_truth.db                    # SQLite database (local only, not in GitHub)
├── alphavangtage.json                 # AlphaVantage daily data (unused, future use)
├── fix_encoding.py                    # Utility: fixes special characters in .py files
├── fix_docstring.py                   # Utility: fixes missing docstring quotes
├── check_series.py                    # Utility: checks FRED series availability
├── check_local_gold.py               # Utility: inspects local gold JSON files
├── pyvenv.cfg                         # Broken original venv config — ignore
└── venv/                              # Active Python virtual environment (local only)

3. Current DB State (as of March 2026)
observations table:
  gold_price_proxy           3,138 rows  (2014-01-02 -> 2026-03-02)  Tier-1  PASS
                             (3,132 from JSON backfill + ~6 from live top-up)
  rates_vol_stress_move          3 rows  (2026-02-26 -> 2026-03-02)  Tier-1  PASS
  gld_holdings_flow_confirm      3 rows  (2026-02-26 -> 2026-03-02)  Tier-2  PASS

4. Series Registry
Located at: layer2/config/series_registry.json

Note: The registry currently contains only 2 entries (MOVE and GLD).
The 18 FRED series below are confirmed available in the FRED metadata dump
but are NOT yet in the registry. They will be added when the FRED
observation loader is built.

Tier-1 Series (block snapshot if missing/stale — staleness threshold: 3 days)
series_idDescriptionSourceFrequencyRequired forHistorygold_price_proxyGold spot price XAUUSDStooq JSON + Yahoo liveDaily EODM02014-presentrates_vol_stress_moveMOVE Index - bond stressYahoo Finance (^MOVE)Daily EODM1~2000-present
Tier-2 Series (warn only, never block snapshot — staleness threshold: 5 days)
series_idDescriptionSourceFrequencyRequired forHistorygld_holdings_flow_confirmGLD Trust ounces heldYahoo Finance (GLD)Daily EODM2See note below

GLD history note: Yahoo Finance only provides today's shares_outstanding
as a single snapshot — not a true daily historical series. The adapter applies
today's share count uniformly across all past trading dates using the formula
ounces = shares_outstanding x 0.09585. This is an approximation.
True historical daily shares outstanding would require a paid data source.
For M2 confirmation purposes this is acceptable, but label it clearly
as an approximation in any backtest output.

FRED Series (metadata confirmed — values not yet loaded into DB)
These 18 series are confirmed present in FRED/all_series_merged.json.
Their observation values need to be ingested via a FRED observation
loader (not yet built).
series_idDescriptionFrequencyHistory availableNotesDFII1010Y TIPS real yieldDaily2003-presentCore real-rate driverDFII55Y TIPS real yieldDaily2003-presentShorter real-rate regimeDGS1010Y Treasury nominal yieldDaily1962-presentNominal regimeDGS22Y Treasury nominal yieldDaily1976-presentPolicy expectationsDGS55Y Treasury nominal yieldDaily1962-presentMid-curve anchorT10YIE10Y breakeven inflationDaily2003-presentInflation expectationsT5YIE5Y breakeven inflationDaily2003-presentShort inflation expectationsT5YIFR5Y/5Y forward inflationDaily2003-presentForward inflation checkDFFEffective fed funds rateDaily1954-presentPolicy regime proxyEFFRNY Fed EFFRDaily2000-presentHigh-quality policy rateDTWEXBGSBroad USD index (goods)Daily2006-presentPrimary USD driverDTWEXMUSD vs major currenciesDaily1973-2019DISCONTINUEDDTWEXOUSD vs other partnersDaily1995-2019DISCONTINUEDTWEXBBroad USD (goods+services)Weekly1995-2020DISCONTINUED + weeklyVIXCLSVIX equity implied volDaily1990-presentEquity stress sensorSP500S&P 500 indexDaily2016-presentTOO SHORT — needs fixCPILFESLCore CPIMonthly1957-presentStructural inflationPCEPIHeadline PCEMonthly1959-presentFed inflation gauge

5. Known Gaps & Issues (to fix)
SeriesIssueFix neededSP500Only goes back to 2016 in FRED dumpUse SPY via Yahoo Finance (goes back to 1993)DTWEXMDiscontinued 2019Bridge with DTWEXBGS or drop entirelyDTWEXODiscontinued 2019Bridge with DTWEXBGS or drop entirelyTWEXBDiscontinued 2020, weekly not dailyBridge with DTWEXBGS or drop entirelyGold historyStarts 2014, target is 2005Extend backfill via Stooq to capture 2008 crisisFRED valuesMetadata only — no values in DB yetBuild FRED observation loaderGLD historyCurrent shares applied backwards — not true historicalAccept as approximation or find paid sourceAlphaVantagealphavangtage.json collected but unusedWire into observations table
Backtest start date rule:
Start = latest common start date across all required Tier-1 inputs
Currently: gold starts 2014-01-02. Engine backtest starts 2014-01-02.
Target: extend gold to 2005 to gain 2008 crisis, 2011 peak, and multiple regime cycles.

6. Database Schema
The database is a local SQLite file: layer2_truth.db
It is not committed to GitHub (too large, machine-specific).
All adapters write to the same observations table:
sqlCREATE TABLE observations (
    series_id       TEXT      NOT NULL,
    obs_ts          DATE      NOT NULL,      -- observation date (YYYY-MM-DD)
    as_of_ts        TIMESTAMP NOT NULL,      -- when the value was published/known
    value           REAL      NOT NULL,      -- the actual data value
    revision_seq    INTEGER   NOT NULL DEFAULT 0,  -- 0 = first release, 1+ = revision
    source          TEXT      NOT NULL,      -- e.g. "yahoo", "stooq_json", "fred"
    ingested_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (series_id, obs_ts, revision_seq)
);

CREATE INDEX idx_obs_series_date ON observations (series_id, obs_ts DESC);
Key rules:

obs_ts = the date the data represents (e.g. 2026-03-03)
as_of_ts = when it was published (e.g. 21:00 UTC = EOD clock)
revision_seq = 0 for first release, 1+ for revisions (FRED revises some series)
Same (series_id, obs_ts, revision_seq) = upsert (replace existing)


7. The Three Adapters
A. Gold Adapter (gold_adapter.py) — Tier-1, M0
What it does: Loads XAUUSD daily close prices into the DB.
This is the PRIMARY asset state. Without gold price, the engine
cannot form MarketState. Missing or stale = NO snapshot published.
Source strategy (in order):

Local JSON (FRED/2014GOLD/gold_xauusd_stooq_2014_yesterday.json) — 3,132 rows, 2014-2026
Stooq live (^xauusd) — attempted for daily top-up (unreliable on weekends)
Yahoo Finance (GC=F gold futures) — fallback when Stooq fails

Staleness rule: FAIL if staleness > 3 days. Blocks snapshot.
bash# First-time setup: load JSON + top up with live data
python layer2\adapters\gold_adapter.py --load-json FRED\2014GOLD\gold_xauusd_stooq_2014_yesterday.json --live

# Daily EOD job (live top-up only)
python layer2\adapters\gold_adapter.py --live --backfill-days 5

# Dry-run (no DB write)
python layer2\adapters\gold_adapter.py --load-json FRED\2014GOLD\gold_xauusd_stooq_2014_yesterday.json --dry-run

# Staleness check only
python layer2\adapters\gold_adapter.py --staleness-check-only
Expected output (success):
[INFO] JSON: loaded 3132 gold rows (2014-01-02 -> 2026-02-20)
[INFO] Wrote 3132 gold price observation(s) to DB.
[INFO] Yahoo: fetched 10 gold rows (2026-02-17 -> 2026-03-02).
[INFO] Wrote 10 gold price observation(s) to DB.
[INFO] Staleness [PASS]: latest=2026-03-02, staleness=1d, reason=fresh
[INFO] Gold adapter completed. Total rows in DB: 3138.

B. MOVE Adapter (move_adapter.py) — Tier-1, M1
What it does: Fetches the MOVE Index (ICE BofAML bond volatility)
daily and stores it in the DB.
Why MOVE matters: Rates-vol / bond-stress sensor. Feeds StressIndex
and UnknownMode governance in Layer-3. Tier-1 — missing MOVE blocks snapshot.
Source: Yahoo Finance (^MOVE) is the primary working source.
Stooq (^move) is attempted first but consistently returns "No data"
on weekends and is unreliable — treat Yahoo as primary.
Staleness rule: FAIL if staleness > 3 days. Blocks snapshot.
bash# Daily EOD job
python layer2\adapters\move_adapter.py --source yahoo

# Backfill last 30 days
python layer2\adapters\move_adapter.py --source yahoo --backfill-days 30

# Dry-run
python layer2\adapters\move_adapter.py --source yahoo --dry-run

# Staleness check only
python layer2\adapters\move_adapter.py --staleness-check
Expected output (success):
[INFO] MOVE adapter starting | range: 2026-03-02 -> 2026-03-02 | dry_run: False
[INFO] Yahoo: parsed 1 MOVE rows.
[INFO] Wrote 1 MOVE observation(s) to DB.
[INFO] Staleness [PASS]: latest=2026-03-02, staleness=1d, reason=fresh
[INFO] MOVE adapter completed. Rows written: 1.

C. GLD Holdings Adapter (gld_holdings_adapter.py) — Tier-2, M2
What it does: Calculates daily ounces of gold held in the GLD Trust
and stores it in the DB.
Why GLD ounces matter: Rising ounces = institutional inflow into gold
(bullish signal). Falling ounces = outflow (bearish signal). Tier-2
confirmation — never blocks snapshot publishing.
Source: Yahoo Finance (GLD) shares outstanding.
Formula: ounces = shares_outstanding x 0.09585
Verified March 2026: 260,300,000 x 0.09585 = 24,949,755 oz = 776.0 tonnes
This matches GLD's publicly reported holdings exactly.
Important limitation: Yahoo provides today's shares_outstanding
as a static number only — not a daily historical series. The adapter
applies this figure uniformly across all past trading dates. This is
an approximation, not true historical data. Acceptable for M2
confirmation but must be labelled as such in backtests.
Staleness rule: WARN if staleness > 5 days. Never blocks snapshot.
bash# Daily EOD job
python layer2\adapters\gld_holdings_adapter.py

# Backfill last 30 days
python layer2\adapters\gld_holdings_adapter.py --backfill-days 30

# Dry-run
python layer2\adapters\gld_holdings_adapter.py --dry-run

# Staleness check only
python layer2\adapters\gld_holdings_adapter.py --staleness-check-only
Expected output (success):
[INFO] GLD: shares_outstanding=260,300,000, oz_per_share=0.09585, ounces=24949755 (776.0 tonnes)
[INFO] GLD: built 1 daily ounces rows.
[INFO] Wrote 1 GLD holdings observation(s) to DB.
[INFO] Staleness [PASS] (Tier-2 non-blocking): latest=2026-03-02, staleness=1d, reason=fresh

8. Engine Clock & Alignment Rules

One clock per day: 21:00 UTC (covers NYSE close + FRED EOD release window)
Alignment rule: latest observation where obs_ts <= clock_ts
Tie-break: highest revision_seq wins. If equal, latest ingested_at wins.
Clock never goes backwards — replays always use the original clock_ts
Weekend behavior: clock still ticks on weekends; staleness window absorbs gaps


9. Quality Gate Rules
TierSeriesStaleness thresholdEffect if staleTier-1gold, MOVE, yields, USD, VIX> 3 days = FAILBlocks snapshot entirelyTier-2GLD holdings, CPI, PCE> 5 days = WARNLogged only, snapshot proceeds
Fail-closed rule:
data_ok = False (any Tier-1 series stale or missing)
-> publish NOTHING
-> Layer-3 receives no snapshot
-> Layer-3 must output: no action

Not yet implemented: quality_gate.py and snapshot_publisher.py
are the next components to build. Until they exist, the staleness
checks inside each adapter serve as manual verification only.


10. What Still Needs to Be Built
ComponentStatusPriorityGold adapterDONE-MOVE adapterDONE-GLD holdings adapterDONE-series_registry.json (MOVE + GLD)DONE-Extend gold history to 2005NOT STARTEDHighFRED observation loaderNOT STARTEDHighAdd FRED series to registryNOT STARTEDHighFix SP500 history (use SPY via Yahoo)NOT STARTEDHighFix/replace discontinued USD seriesNOT STARTEDMediumQuality gate (quality_gate.py)NOT STARTEDHighSnapshot publisher (snapshot_publisher.py)NOT STARTEDHighDaily scheduler (Windows Task Scheduler)NOT STARTEDMediumFeature Builder (Layer-3)NOT STARTEDAfter snapshotsIndex Suite (Layer-3)NOT STARTEDAfter Feature BuilderDecision Engine (Layer-3)NOT STARTEDAfter Index Suite

11. How to Set Up Locally (for your friend)
Prerequisites

Python 3.10+ installed
Git installed
Windows, Mac, or Linux

Step-by-step
bash# Step 1: Clone the repo
git clone https://github.com/balazsv27-rgb/Mr-Ripley.git
cd Mr-Ripley

# Step 2: Create and activate venv
python -m venv venv
.\venv\Scripts\activate        # Windows
source venv/bin/activate       # Mac/Linux

# Step 3: Install dependencies
pip install yfinance

# Step 4: Load gold backfill (first time only — takes a few seconds)
python layer2\adapters\gold_adapter.py --load-json FRED\2014GOLD\gold_xauusd_stooq_2014_yesterday.json --live

# Step 5: Load MOVE and GLD (backfill last 30 days)
python layer2\adapters\move_adapter.py --source yahoo --backfill-days 30
python layer2\adapters\gld_holdings_adapter.py --backfill-days 30

# Step 6: Verify all three pass staleness check
python layer2\adapters\gold_adapter.py --staleness-check-only
python layer2\adapters\move_adapter.py --staleness-check
python layer2\adapters\gld_holdings_adapter.py --staleness-check-only
You should see PASS for all three. If any shows FAIL, check your
internet connection and re-run that adapter.

12. Key Decisions & Why
DecisionWhySQLite for DBSimple, portable, no server needed. Can migrate to Postgres later.Yahoo Finance as primary for MOVEStooq ^move unreliable (returns "No data" on weekends). Yahoo confirmed working.GLD ounces = shares x 0.09585State Street CSV endpoint changed to PDF. Yahoo shares_outstanding is only available option. Formula verified: 776 tonnes.GLD is approximation not true historicalYahoo gives today's shares only. Applied uniformly to past dates. Acceptable for Tier-2 confirmation.Gold from JSON + live top-upAvoids hitting Stooq rate limits for 12 years of history. JSON is the truth source.Tier-1 staleness = 3 daysCovers weekends (2 days) + 1 day FRED release lag.Tier-2 staleness = 5 daysMonthly series can have natural gaps. GLD is confirmation only.Fail-closed snapshotsPrevents Layer-3 from making decisions on incomplete or stale data.Backtest start = 2014-01-02Limited by gold JSON start date. Extend to 2005 when possible.venv/ not in GitHubToo large, platform-specific. Each developer creates their own.layer2_truth.db not in GitHubLocal DB only. Each developer builds their own from adapters.

13. Useful Links
ResourceURLGitHub Repohttps://github.com/balazsv27-rgb/Mr-RipleyFRED APIhttps://fred.stlouisfed.orgYahoo Finance (MOVE)https://finance.yahoo.com/quote/%5EMOVEYahoo Finance (GLD)https://finance.yahoo.com/quote/GLDYahoo Finance (Gold futures)https://finance.yahoo.com/quote/GC%3DFGLD Trust Infohttps://www.spdrgoldshares.comyfinance docshttps://ranaroussi.github.io/yfinance

14. Contact & Collaboration

Mr. Ripley repo owner: @balazsv27-rgb
Architecture decisions: Documented in architecture4.md.txt, architeture.md
Questions: Open a GitHub Issue on the repo


This document was written to bring a new collaborator (human or AI) fully up to speed
on Layer-2 of the Mr. Ripley Gold-First Market State Engine.
Read this before touching any