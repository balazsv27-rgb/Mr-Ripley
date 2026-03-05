Mr. Ripley — Layer-2 Truth Layer
What We Built & How to Use It

For: Friend / collaborator reading this on GitHub
Repo: https://github.com/balazsv27-rgb/Mr-Ripley
Last updated: March 2026


1. What Is Layer-2?
Layer-2 is the data ingestion and truth store for the Gold-First Market State Engine (Mr. Ripley).
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
├── .secrets/                          # API keys (NOT in GitHub — gitignored)
│   └── fred_api_key.txt               # Your FRED API key goes here
├── layer2/                            # Everything we built
│   ├── adapters/
│   │   ├── gold_adapter.py            # Gold price XAUUSD ingestion (Tier-1)
│   │   ├── move_adapter.py            # MOVE index ingestion (Tier-1)
│   │   ├── gld_holdings_adapter.py    # GLD ounces held (Tier-2)
│   │   ├── fred_loader.py             # FRED 20-series loader (Tier-1 + Tier-2)
│   │   └── quality_gate.py            # Staleness checker + snapshot verdict
│   ├── config/
│   │   └── series_registry.json       # Series metadata (MOVE + GLD entries)
│   └── README_LAYER2.md               # This file
├── layer2_truth.db                    # SQLite DB (local only — gitignored)
├── layer2_quality_report.json         # Quality gate output (local only — gitignored)
├── alphavangtage.json                 # AlphaVantage daily data (unused, future use)
├── fix_encoding.py                    # Utility: fixes special characters in .py files
├── fix_docstring.py                   # Utility: fixes missing docstring quotes
└── venv/                              # Python virtual environment (local only)

3. Current DB State (as of March 2026)
observations table — ~85,700 rows across 23 series

series_id                   rows    date range                    tier  status
────────────────────────────────────────────────────────────────────────────────
gold_price_proxy            3,138   2014-01-02 -> 2026-03-02     T1    PASS
rates_vol_stress_move       1,245   2021-03-06 -> 2026-03-04     T1    PASS
DFII10                      5,794   2003-01-02 -> 2026-03-03     T1    PASS
DFII5                       5,794   2003-01-02 -> 2026-03-03     T1    PASS
DGS10                       5,294   2005-01-03 -> 2026-03-03     T1    PASS
DGS2                        5,294   2005-01-03 -> 2026-03-03     T1    PASS
DGS5                        5,294   2005-01-03 -> 2026-03-03     T1    PASS
T10YIE                      5,795   2003-01-02 -> 2026-03-04     T1    PASS
T5YIE                       5,795   2003-01-02 -> 2026-03-04     T1    PASS
T5YIFR                      5,795   2003-01-02 -> 2026-03-04     T1    PASS
DFF                         7,730   2005-01-03 -> 2026-03-03     T1    PASS
EFFR                        5,315   2005-01-03 -> 2026-03-04     T1    PASS
DTWEXBGS                    5,052   2006-01-02 -> 2026-02-27     T1    PASS*
VIXCLS                      5,354   2005-01-03 -> 2026-03-04     T1    PASS
SP500                       2,513   2016-02-22 -> 2026-03-04     T1    PASS**
gld_holdings_flow_confirm   1,254   2021-03-08 -> 2026-03-04     T2    PASS
CPILFESL                      252   2005-01-01 -> 2026-01-01     T2    WARN***
FEDFUNDS                      254   2005-01-01 -> 2026-02-01     T2    PASS
PCEPI                         252   2005-01-01 -> 2025-12-01     T2    WARN***
PCU2122212122210              156   2005-01-01 -> 2017-12-01     T2    PASS****
DTWEXM                      3,775   2005-01-03 -> 2019-12-31     --    discontinued
DTWEXO                      3,775   2005-01-03 -> 2019-12-31     --    discontinued
TWEXB                         783   2005-01-03 -> 2020-01-01     --    discontinued

*    DTWEXBGS: FRED publishes with ~1 week structural lag. Threshold = 10 days.
**   SP500: FRED only has data from 2016. Known gap — fix via SPY (Yahoo) planned.
***  CPILFESL/PCEPI: BLS/BEA monthly release lag. Warnings expected and correct.
**** PCU2122212122210: Discontinued 2017. Staleness check disabled (threshold=9999d).
Quality gate verdict as of 2026-03-05: ✅ PASS — 15/15 Tier-1 series fresh

4. Series Registry
Tier-1 Series (block snapshot if stale)
series_idDescriptionSourceThresholdHistorygold_price_proxyGold spot XAUUSDStooq JSON + Yahoo3 days2014-presentrates_vol_stress_moveMOVE Index bond stressYahoo (^MOVE)3 days2021-presentDFII1010Y TIPS real yieldFRED API3 days2003-presentDFII55Y TIPS real yieldFRED API3 days2003-presentDGS1010Y Treasury nominal yieldFRED API3 days2005-presentDGS22Y Treasury nominal yieldFRED API3 days2005-presentDGS55Y Treasury nominal yieldFRED API3 days2005-presentT10YIE10Y breakeven inflationFRED API3 days2003-presentT5YIE5Y breakeven inflationFRED API3 days2003-presentT5YIFR5Y/5Y forward inflationFRED API3 days2003-presentDFFEffective fed funds rateFRED API3 days2005-presentEFFRNY Fed EFFRFRED API3 days2005-presentDTWEXBGSBroad USD index (goods)FRED API10 days2006-presentVIXCLSVIX equity implied volFRED API3 days2005-presentSP500S&P 500 indexFRED API3 days2016-present
Tier-2 Series (warn only — never block snapshot)
series_idDescriptionSourceThresholdHistorygld_holdings_flow_confirmGLD Trust ounces heldYahoo (GLD)5 days2021-presentCPILFESLCore CPIFRED API45 days2005-presentFEDFUNDSFed funds rate monthly avgFRED API45 days2005-presentPCEPIHeadline PCEFRED API45 days2005-presentPCU2122212122210PPI: Gold ore miningFRED APIdisabled2005-2017

GLD note: Yahoo gives today's shares_outstanding only — not true historical.
Applied uniformly to past dates using ounces = shares_outstanding x 0.09585.
This is an approximation. Label clearly in any backtest output.


5. Known Gaps & Issues
SeriesIssueFix neededSP500Only goes back to 2016Use SPY via Yahoo (goes to 1993)DTWEXMDiscontinued 2019, in DBBridge with DTWEXBGS or dropDTWEXODiscontinued 2019, in DBBridge with DTWEXBGS or dropTWEXBDiscontinued 2020, weeklyBridge with DTWEXBGS or dropGold historyStarts 2014, target is 2005Extend backfill via StooqGLD historyApproximation onlyAccept or find paid sourceAlphaVantagealphavangtage.json unusedWire into observations table
Backtest start date: 2014-01-02 — limited by gold JSON.
Target: extend gold to 2005 to gain 2008 crisis + 2011 peak.

6. Database Schema
Local SQLite: layer2_truth.db — not in GitHub (gitignored).
sqlCREATE TABLE observations (
    series_id       TEXT      NOT NULL,
    obs_ts          DATE      NOT NULL,
    as_of_ts        TIMESTAMP NOT NULL,
    value           REAL      NOT NULL,
    revision_seq    INTEGER   NOT NULL DEFAULT 0,
    source          TEXT      NOT NULL,
    ingested_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (series_id, obs_ts, revision_seq)
);

CREATE INDEX idx_obs_series_date ON observations (series_id, obs_ts DESC);

7. The Five Adapters
A. Gold Adapter (gold_adapter.py) — Tier-1, M0
Primary asset state. Missing or stale = NO snapshot published.
Source: Local JSON -> Stooq live -> Yahoo Finance (GC=F)
bash# First-time setup
python layer2\adapters\gold_adapter.py --load-json FRED\2014GOLD\gold_xauusd_stooq_2014_yesterday.json --live

# Daily EOD job
python layer2\adapters\gold_adapter.py --live --backfill-days 5

# Staleness check
python layer2\adapters\gold_adapter.py --staleness-check-only

B. MOVE Adapter (move_adapter.py) — Tier-1, M1
Rates-vol / bond-stress sensor. Missing = NO snapshot published.
Source: Yahoo Finance (^MOVE). Stooq unreliable on weekends.
bash# Daily EOD job
python layer2\adapters\move_adapter.py --source yahoo

# Backfill 5 years (run once after setup)
python layer2\adapters\move_adapter.py --source yahoo --backfill-days 1825

# Staleness check
python layer2\adapters\move_adapter.py --staleness-check

C. GLD Holdings Adapter (gld_holdings_adapter.py) — Tier-2, M2
Flow confirmation only. Never blocks snapshot.
Formula: ounces = shares_outstanding x 0.09585
Verified March 2026: 260,300,000 x 0.09585 = 24,949,755 oz = 776.0 tonnes
bash# Daily EOD job
python layer2\adapters\gld_holdings_adapter.py

# Backfill 5 years (run once after setup)
python layer2\adapters\gld_holdings_adapter.py --backfill-days 1825

# Staleness check
python layer2\adapters\gld_holdings_adapter.py --staleness-check-only

D. FRED Loader (fred_loader.py) — Tier-1 + Tier-2
Loads all 20 FRED series. Requires FRED API key in .secrets/fred_api_key.txt
Get a free key at: https://fredaccount.stlouisfed.org/apikeys
bash# Full history load (first time — ~20 seconds, 80,000+ rows)
python layer2\adapters\fred_loader.py --full-history

# Daily EOD top-up
python layer2\adapters\fred_loader.py --backfill-days 5

# Single series refresh
python layer2\adapters\fred_loader.py --series DGS10 DFII10 --backfill-days 30

# Status report
python layer2\adapters\fred_loader.py --status

# Dry-run
python layer2\adapters\fred_loader.py --backfill-days 5 --dry-run

E. Quality Gate (quality_gate.py) — Snapshot gatekeeper
Checks all 23 series, computes verdict, saves JSON report.
Run before any snapshot is published. Exit code: 0 = PASS, 1 = FAIL.
bash# Run quality gate (standard)
python layer2\adapters\quality_gate.py

# Override clock date (replay / testing)
python layer2\adapters\quality_gate.py --clock-date 2026-03-03

# Quiet mode (verdict only)
python layer2\adapters\quality_gate.py --quiet

# Custom report path
python layer2\adapters\quality_gate.py --report-path reports\quality.json
Expected output (healthy):
[INFO] Tier-1: 15/15 PASS | 0 FAIL
[INFO] VERDICT: ✓ PASS — snapshot may be published
[INFO] Quality report saved to: layer2_quality_report.json

layer2_quality_report.json is gitignored — generated fresh on each run.


8. Engine Clock & Alignment Rules

One clock per day: 21:00 UTC (NYSE close + FRED EOD release window)
Alignment: latest observation where obs_ts <= clock_ts
Tie-break: highest revision_seq wins. Equal -> latest ingested_at wins.
Clock never goes backwards — replays always use original clock_ts
Weekend behavior: clock ticks daily; staleness window absorbs weekend gaps


9. Quality Gate Rules
TierSeriesStaleness thresholdEffect if staleTier-1gold, MOVE, yields, USD, VIX, SP5003 days (DTWEXBGS: 10 days)Blocks snapshotTier-2GLD, CPI, PCE, FEDFUNDS5-45 daysWarning only
Fail-closed: any Tier-1 FAIL -> publish NOTHING -> Layer-3 outputs nothing.

10. What Still Needs to Be Built
ComponentStatusPriorityGold adapter✅ DONE-MOVE adapter✅ DONE-GLD holdings adapter✅ DONE-FRED loader (20 series)✅ DONE-Quality gate✅ DONE-Snapshot publisher (snapshot_publisher.py)NOT STARTEDHighDaily scheduler (Windows Task Scheduler)NOT STARTEDMediumExtend gold history to 2005NOT STARTEDMediumFix SP500 history (use SPY via Yahoo)NOT STARTEDMediumFix/replace discontinued USD seriesNOT STARTEDLowFeature Builder (Layer-3)NOT STARTEDAfter snapshotsIndex Suite (Layer-3)NOT STARTEDAfter Feature BuilderDecision Engine (Layer-3)NOT STARTEDAfter Index Suite

11. How to Set Up Locally (for your friend)
Prerequisites

Python 3.10+ installed
Git installed
Free FRED API key from https://fredaccount.stlouisfed.org/apikeys

Step-by-step
bash# Step 1: Clone
git clone https://github.com/balazsv27-rgb/Mr-Ripley.git
cd Mr-Ripley

# Step 2: Create venv
python -m venv venv
.\venv\Scripts\activate        # Windows
source venv/bin/activate       # Mac/Linux

# Step 3: Install dependencies
pip install yfinance

# Step 4: Add FRED API key
mkdir .secrets
echo your_fred_api_key_here > .secrets\fred_api_key.txt

# Step 5: Load gold backfill (first time only)
python layer2\adapters\gold_adapter.py --load-json FRED\2014GOLD\gold_xauusd_stooq_2014_yesterday.json --live

# Step 6: Load MOVE and GLD (5 year backfill)
python layer2\adapters\move_adapter.py --source yahoo --backfill-days 1825
python layer2\adapters\gld_holdings_adapter.py --backfill-days 1825

# Step 7: Load all 20 FRED series (full history — ~20 seconds)
python layer2\adapters\fred_loader.py --full-history

# Step 8: Verify everything
python layer2\adapters\quality_gate.py
You should see: VERDICT: ✓ PASS — snapshot may be published

12. Key Decisions & Why
DecisionWhySQLite for DBSimple, portable, no server. Can migrate to Postgres later.Yahoo for MOVEStooq ^move returns "No data" on weekends. Yahoo confirmed working.GLD ounces = shares x 0.09585State Street CSV broke (returns PDF). Formula verified: 776 tonnes.GLD is approximationYahoo gives today's shares only. Applied to past dates uniformly.Gold from JSON + live top-upAvoids Stooq rate limits for 12 years of history.FRED for 20 seriesSingle API, free, full history for all target series.DTWEXBGS threshold = 10 daysStructural ~1 week FRED publish lag. Not a data error.PCU2122212122210 disabledDiscontinued 2017. Staleness check meaningless.Tier-1 staleness = 3 daysCovers weekends (2 days) + 1 day FRED release lag.Fail-closed snapshotsPrevents Layer-3 deciding on stale or incomplete data.Backtest start = 2014-01-02Limited by gold JSON. Extend to 2005 when possible..secrets/ gitignoredAPI keys must never be committed to GitHub.layer2_truth.db gitignoredLocal DB. Each developer rebuilds from adapters.quality_report.json gitignoredGenerated fresh each run. Committed file would be stale.

13. Useful Links
ResourceURLGitHub Repohttps://github.com/balazsv27-rgb/Mr-RipleyFRED APIhttps://fred.stlouisfed.orgFRED API Keyshttps://fredaccount.stlouisfed.org/apikeysYahoo Finance (MOVE)https://finance.yahoo.com/quote/%5EMOVEYahoo Finance (GLD)https://finance.yahoo.com/quote/GLDYahoo Finance (Gold futures)https://finance.yahoo.com/quote/GC%3DFGLD Trust Infohttps://www.spdrgoldshares.comyfinance docshttps://ranaroussi.github.io/yfinance

14. Contact & Collaboration

Mr. Ripley repo owner: @balazsv27-rgb
Architecture decisions: Documented in architecture4.md.txt, architeture.md
Questions: Open a GitHub Issue on the repo