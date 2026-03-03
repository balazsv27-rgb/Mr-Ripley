Mr. Ripley — Layer-2 Truth Layer

What We Built \& How to Use It



For: Friend / collaborator reading this on GitHub

Repo: https://github.com/balazsv27-rgb/Mr-Ripley

Last updated: March 2026





1\. What Is Layer-2?

Layer-2 is the data ingestion and truth store for the Gold-First Market State Engine (Mr. Ripley).

Think of it as the foundation of the whole system:

Layer-1  →  Raw data sources (FRED, Yahoo, Stooq, State Street)

Layer-2  →  Ingestion + validation + immutable snapshots  ← YOU ARE HERE

Layer-3  →  Feature builder + index suite + decision engine

The golden rule of Layer-2:

Layer-3 is NEVER allowed to read "latest" data directly. It can ONLY consume a published snapshot\_id. If data is missing or stale → no snapshot is published → Layer-3 outputs nothing. This is called fail-closed behavior.



2\. Folder Structure

Mr-Ripley/

├── FRED/                          # Historical FRED data dumps

├── layer2/                        # Everything we built

│   ├── adapters/

│   │   ├── move\_adapter.py        # MOVE index ingestion (Tier-1)

│   │   └── gld\_holdings\_adapter.py # GLD ounces held (Tier-2)

│   └── config/

│       └── series\_registry.json   # Master list of all series

├── layer2\_truth.db                # SQLite database (local only, not in GitHub)

├── fix\_encoding.py                # Utility: fixes special characters in .py files

├── fix\_docstring.py               # Utility: fixes missing docstring quotes

└── venv/                          # Python virtual environment (local only)



3\. Series Registry

Located at: layer2/config/series\_registry.json

This is the master config that defines every data series in the system.

Tier-1 Series (block snapshot if missing/stale)

series\_idDescriptionSourceFrequencyRequired forrates\_vol\_stress\_moveMOVE Index - bond stress / rates volYahoo Finance (^MOVE)Daily EODM1

Tier-2 Series (warn only, never block snapshot)

series\_idDescriptionSourceFrequencyRequired forgld\_holdings\_flow\_confirmGLD Trust - ounces of gold heldYahoo Finance (GLD)Daily EODM2

FRED Series (already in existing FRED pipeline)

These are handled by the existing FRED ingestion pipeline and stored in the same observations table:

series\_idDescriptionFrequencyDFII1010Y TIPS real yieldDailyDFII55Y TIPS real yieldDailyDGS1010Y Treasury nominal yieldDailyDGS22Y Treasury nominal yieldDailyDGS55Y Treasury nominal yieldDailyT10YIE10Y breakeven inflationDailyT5YIE5Y breakeven inflationDailyT5YIFR5Y/5Y forward inflationDailyDFFEffective fed funds rateDailyEFFRNY Fed EFFRDailyDTWEXBGSBroad USD index (goods)DailyDTWEXMUSD vs major currenciesDailyDTWEXOUSD vs other partnersDailyTWEXBBroad USD (goods+services)DailyVIXCLSVIX equity implied volDailySP500S\&P 500 indexDailyCPILFESLCore CPIMonthlyFEDFUNDSFed funds rate (monthly avg)MonthlyPCEPIHeadline PCEMonthlyPCU2122212122210PPI gold ore miningMonthly



4\. Database Schema

The database is a local SQLite file: layer2\_truth.db

All adapters write to the same observations table:

sqlCREATE TABLE observations (

&nbsp;   series\_id       TEXT      NOT NULL,

&nbsp;   obs\_ts          DATE      NOT NULL,      -- observation date (YYYY-MM-DD)

&nbsp;   as\_of\_ts        TIMESTAMP NOT NULL,      -- when the value was published

&nbsp;   value           REAL      NOT NULL,      -- the actual data value

&nbsp;   revision\_seq    INTEGER   NOT NULL DEFAULT 0,  -- 0 = first release

&nbsp;   source          TEXT      NOT NULL,      -- e.g. "yahoo", "stooq", "fred"

&nbsp;   ingested\_at     TIMESTAMP NOT NULL DEFAULT CURRENT\_TIMESTAMP,

&nbsp;   PRIMARY KEY (series\_id, obs\_ts, revision\_seq)

);

Key rules:



obs\_ts = the date the data represents (e.g. 2026-03-03)

as\_of\_ts = when it was published (e.g. 21:15 UTC = 4:15 PM ET)

revision\_seq = 0 for first release, 1+ for revisions

Same (series\_id, obs\_ts, revision\_seq) = upsert (replace)





5\. The Two Adapters

A. MOVE Adapter (move\_adapter.py)

What it does: Fetches the MOVE Index (ICE BofAML bond volatility index) daily and stores it in the DB.

Why MOVE matters: MOVE is the rates-vol / bond-stress sensor. When MOVE spikes, it signals stress in the bond market which directly affects gold regime classification in Layer-3. It is Tier-1 — if MOVE is missing or stale, NO snapshot is published.

Source: Yahoo Finance (^MOVE) — free, no login required.

Fallback: Stooq (^move) — tried first, Yahoo is backup.

Formula: Direct close price. No calculation needed.

Staleness rule: data\_ok = True if staleness <= 3 days. Fails if > 3 days.

How to run:

bash# Activate venv first (Windows)

.\\venv\\Scripts\\activate



\# Daily EOD job (fetches yesterday)

python layer2\\adapters\\move\_adapter.py --source yahoo



\# Backfill last 30 days

python layer2\\adapters\\move\_adapter.py --source yahoo --backfill-days 30



\# Dry-run (no DB write)

python layer2\\adapters\\move\_adapter.py --source yahoo --dry-run



\# Check staleness only

python layer2\\adapters\\move\_adapter.py --staleness-check

Expected output (success):

\[INFO] MOVE adapter starting | range: 2026-03-02 -> 2026-03-02 | dry\_run: False

\[INFO] Yahoo: parsed 1 MOVE rows.

\[INFO] Wrote 1 MOVE observation(s) to DB.

\[INFO] Staleness \[PASS]: latest=2026-03-02, staleness=1d, reason=fresh

\[INFO] MOVE adapter completed. Rows written: 1.



B. GLD Holdings Adapter (gld\_holdings\_adapter.py)

What it does: Fetches the daily ounces of gold held in the GLD Trust and stores it in the DB.

Why GLD ounces matter: Rising ounces = institutional inflow into gold (bullish). Falling ounces = outflow (bearish). This is a Tier-2 flow confirmation signal used in M2 validation — it never blocks snapshot publishing, but it enriches the decision context.

Source: Yahoo Finance (GLD) — shares outstanding x conversion factor.

Formula:

ounces\_held = shares\_outstanding x 0.09585

The 0.09585 is GLD's fixed oz-per-share conversion factor. Verified: gives exactly 776.0 tonnes as of March 2026, matching GLD's published holdings.

Staleness rule: Warns if staleness > 5 days. Never blocks snapshot (Tier-2).

How to run:

bash# Daily EOD job

python layer2\\adapters\\gld\_holdings\_adapter.py



\# Backfill last 30 days

python layer2\\adapters\\gld\_holdings\_adapter.py --backfill-days 30



\# Dry-run

python layer2\\adapters\\gld\_holdings\_adapter.py --dry-run



\# Staleness report only

python layer2\\adapters\\gld\_holdings\_adapter.py --staleness-check-only

Expected output (success):

\[INFO] GLD adapter starting | range: 2026-03-02 -> 2026-03-02 | dry\_run: False

\[INFO] GLD: shares\_outstanding=260,300,000, oz\_per\_share=0.09585, ounces=24949755 (776.0 tonnes)

\[INFO] GLD: built 1 daily ounces rows.

\[INFO] Wrote 1 GLD holdings observation(s) to DB.

\[INFO] Staleness \[PASS] (Tier-2 non-blocking): latest=2026-03-02, staleness=1d, reason=fresh



6\. Engine Clock \& Alignment Rules



One clock per day: 21:00 UTC (covers NYSE close + FRED EOD release)

Alignment rule: latest observation where obs\_ts <= clock\_ts

Tie-break: highest revision\_seq wins. If equal, latest ingested\_at wins.

The clock never goes backwards — replays use the original clock\_ts





7\. Quality Gate Rules

TierSeries typeStaleness thresholdEffect if staleTier-1Daily drivers (MOVE, yields, USD, VIX)> 3 days = FAILBlocks snapshotTier-2Validation overlay (GLD holdings, CPI, PCE)> 5 days = WARNLogged only

Fail-closed rule:

If data\_ok = False (any Tier-1 series stale/missing) → publish NOTHING.

Layer-3 must treat a missing snapshot as "no action."



8\. What Still Needs to Be Built

ComponentStatusPriorityMOVE adapterDONE-GLD holdings adapterDONE-series\_registry.jsonDONE-Quality gate (quality\_gate.py)NOT STARTEDHighSnapshot publisher (snapshot\_publisher.py)NOT STARTEDHighDaily scheduler (Windows Task Scheduler)NOT STARTEDMediumFeature Builder (Layer-3)NOT STARTEDAfter snapshotsIndex Suite (Layer-3)NOT STARTEDAfter Feature Builder



9\. How to Set Up Locally (for your friend)

Step 1: Clone the repo

bashgit clone https://github.com/balazsv27-rgb/Mr-Ripley.git

cd Mr-Ripley

Step 2: Create and activate venv

bashpython -m venv venv



\# Windows:

.\\venv\\Scripts\\activate



\# Mac/Linux:

source venv/bin/activate

Step 3: Install dependencies

bashpip install yfinance

Step 4: Run a test

bash# Test MOVE adapter (dry-run, no DB write)

python layer2\\adapters\\move\_adapter.py --source yahoo --dry-run --backfill-days 5



\# Test GLD adapter (dry-run)

python layer2\\adapters\\gld\_holdings\_adapter.py --dry-run --backfill-days 5

Step 5: Write to DB

bashpython layer2\\adapters\\move\_adapter.py --source yahoo --backfill-days 30

python layer2\\adapters\\gld\_holdings\_adapter.py --backfill-days 30



10\. Key Decisions \& Why

DecisionWhySQLite for DBSimple, portable, no server needed. Can migrate to Postgres later.Yahoo Finance for MOVEStooq ^move returns "No data" on weekends. Yahoo is more reliable.GLD ounces = shares x 0.09585State Street CSV endpoint changed to PDF. Yahoo gives shares\_outstanding. Formula verified: gives exactly 776 tonnes.Tier-1 staleness = 3 daysCovers weekends (2 days) + 1 day FRED lag.Tier-2 staleness = 5 daysMonthly series can gap; GLD is confirmation only.Fail-closed snapshotsPrevents Layer-3 from making decisions on stale data.venv/ not in GitHubToo large, platform-specific. Each developer creates their own.



11\. Useful Links

ResourceURLGitHub Repohttps://github.com/balazsv27-rgb/Mr-RipleyFRED APIhttps://fred.stlouisfed.orgYahoo Finance (MOVE)https://finance.yahoo.com/quote/%5EMOVEYahoo Finance (GLD)https://finance.yahoo.com/quote/GLDGLD Trust Infohttps://www.spdrgoldshares.comyfinance docshttps://ranaroussi.github.io/yfinance



12\. Contact \& Collaboration



Mr. Ripley repo owner: @balazsv27-rgb

Architecture decisions: Documented in architecture4.md.txt, architeture.md

Questions: Open a GitHub Issue on the repo





This document was written to bring a new collaborator (human or AI) up to speed on Layer-2 of the Mr. Ripley Gold-First Market State Engine. Read this first before touching any code.

