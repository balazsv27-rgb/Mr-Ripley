"""
run_backfill.py
---------------
Layer-2 backfill orchestrator for Mr. Ripley.

Runs all six data adapters in the correct dependency order and reports
a consolidated result. Designed for both first-time setup (--full-history)
and daily EOD maintenance (default).

Adapter execution order (dependency-safe):
    1. gold_adapter          — Tier-1, primary asset state
    2. move_adapter          — Tier-1, rates-vol / bond-stress
    3. spy_adapter           — Tier-1, SP500_PROXY long-history equity proxy
    4. gld_holdings_adapter  — Tier-2, flow confirmation
    5. fred_loader           — Tier-1 + Tier-2, 20 FRED series

Usage:
    # Daily EOD top-up (last 5 days, safe to run repeatedly)
    python layer2/run_backfill.py

    # Full history — first-time setup or complete rebuild
    python layer2/run_backfill.py --full-history

    # Full history including gold JSON bulk load
    python layer2/run_backfill.py --full-history --gold-json FRED/2014GOLD/gold_xauusd_stooq_2014_yesterday.json

    # Dry-run — fetch and parse everything, no DB writes
    python layer2/run_backfill.py --dry-run

    # Specific date window across all adapters
    python layer2/run_backfill.py --start-date 2026-01-01 --end-date 2026-03-07

    # Skip specific adapters (e.g. if FRED key not yet set up)
    python layer2/run_backfill.py --skip fred

    # Run only specific adapters
    python layer2/run_backfill.py --only gold move spy

Environment variables:
    L2_DB_PATH          Path to SQLite DB (default: layer2_truth.db)
    L2_LOG_LEVEL        Log verbosity: DEBUG | INFO | WARNING (default: INFO)
    L2_FRED_KEY_PATH    Path to FRED API key file (default: .secrets/fred_api_key.txt)
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_PATH: str = os.getenv("L2_DB_PATH", "layer2_truth.db")
LOG_LEVEL: str = os.getenv("L2_LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] run_backfill: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Adapter registry — defines order, keys, and defaults
# ---------------------------------------------------------------------------

# All adapters relative to the repo root. Each entry defines the adapter key,
# the script path (relative to repo root), and default daily args. Full-history
# and date-window args are composed at runtime.

_ADAPTERS = [
    {
        "key":         "gold",
        "label":       "Gold price (XAUUSD)",
        "script":      "layer2/adapters/gold_adapter.py",
        "tier":        1,
        "daily_args":  ["--live", "--backfill-days", "5"],
        # --full-history args are built dynamically (needs --load-json optionally)
    },
    {
        "key":         "move",
        "label":       "MOVE index (^MOVE)",
        "script":      "layer2/adapters/move_adapter.py",
        "tier":        1,
        "daily_args":  ["--source", "yahoo", "--backfill-days", "5"],
        "full_history_args": ["--source", "yahoo", "--backfill-days", "1825"],
    },
    {
        "key":         "spy",
        "label":       "SP500 proxy (SPY)",
        "script":      "layer2/adapters/spy_adapter.py",
        "tier":        1,
        "daily_args":  ["--backfill-days", "5"],
        "full_history_args": ["--backfill-start", "2005-01-03"],
    },
    {
        "key":         "gld",
        "label":       "GLD Trust holdings",
        "script":      "layer2/adapters/gld_holdings_adapter.py",
        "tier":        2,
        "daily_args":  [],   # adapter defaults to last 30 days
        "full_history_args": ["--start-date", "2021-03-08"],  # registry full_history_start
    },
    {
        "key":         "fred",
        "label":       "FRED loader (20 series)",
        "script":      "layer2/adapters/fred_loader.py",
        "tier":        "1+2",
        "daily_args":  ["--backfill-days", "5"],
        "full_history_args": ["--full-history"],
    },
]

_ADAPTER_KEYS = [a["key"] for a in _ADAPTERS]

# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _run_adapter(
    adapter: dict,
    extra_args: List[str],
    db_path: str,
    dry_run: bool,
    python: str,
) -> int:
    """
    Invoke one adapter as a subprocess using the same Python interpreter.
    Returns the exit code (0 = success).
    """
    cmd = [python, adapter["script"], "--db", db_path] + extra_args
    if dry_run:
        cmd.append("--dry-run")

    log.info("  CMD: %s", " ".join(cmd))
    t0 = time.monotonic()
    result = subprocess.run(cmd, check=False)
    elapsed = time.monotonic() - t0
    log.info(
        "  → exit_code=%d  elapsed=%.1fs",
        result.returncode, elapsed,
    )
    return result.returncode


def run_all(
    adapters_to_run: List[dict],
    mode: str,                        # "daily" | "full_history" | "window"
    db_path: str,
    dry_run: bool,
    python: str,
    gold_json: Optional[str],
    start_date: Optional[date],
    end_date: Optional[date],
) -> Dict[str, int]:
    """
    Run each adapter and return {key: exit_code}.
    """
    results: Dict[str, int] = {}

    for adapter in adapters_to_run:
        key   = adapter["key"]
        label = adapter["label"]

        log.info("=" * 60)
        log.info("Adapter [%s]: %s", key.upper(), label)
        log.info("=" * 60)

        # --- Compose args for this adapter + mode ---
        if mode == "window":
            extra = _window_args(adapter, start_date, end_date)
        elif mode == "full_history":
            extra = _full_history_args(adapter, gold_json)
        else:  # daily
            extra = list(adapter["daily_args"])
            # Gold always needs --live in daily mode; --load-json only if provided
            if key == "gold" and gold_json:
                extra = ["--load-json", gold_json] + extra

        rc = _run_adapter(adapter, extra, db_path, dry_run, python)
        results[key] = rc

        # Small pause between adapters to avoid hammering APIs
        if adapter is not adapters_to_run[-1]:
            time.sleep(1.0)

    return results


def _window_args(adapter: dict, start: Optional[date], end: Optional[date]) -> List[str]:
    """Build date-window args tailored to each adapter's CLI flags."""
    key = adapter["key"]
    args: List[str] = []

    if key == "gold":
        # gold_adapter uses --live for live fetch; JSON not needed for window mode
        args += ["--live"]
        if start:
            # gold_adapter's live mode uses --backfill-days; convert window to days
            days = (end - start).days + 1 if end else 30
            args += ["--backfill-days", str(days)]
        return args

    if key == "move":
        args += ["--source", "yahoo"]
        if start:
            args += ["--start-date", start.isoformat()]
        if end:
            args += ["--end-date", end.isoformat()]
        return args

    if key == "spy":
        if start:
            args += ["--backfill-start", start.isoformat()]
        if end:
            args += ["--end-date", end.isoformat()]
        return args

    if key == "gld":
        if start:
            args += ["--start-date", start.isoformat()]
        if end:
            args += ["--end-date", end.isoformat()]
        return args

    if key == "fred":
        if start:
            args += ["--start-date", start.isoformat()]
        if end:
            args += ["--end-date", end.isoformat()]
        return args

    return args


def _full_history_args(adapter: dict, gold_json: Optional[str]) -> List[str]:
    """Build full-history args for each adapter."""
    key = adapter["key"]

    if key == "gold":
        args: List[str] = []
        if gold_json:
            args += ["--load-json", gold_json]
        args += ["--live", "--backfill-days", "5"]
        return args

    return list(adapter.get("full_history_args", adapter["daily_args"]))


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _print_summary(results: Dict[str, int], elapsed_total: float, dry_run: bool) -> int:
    """Print final summary table. Returns 0 if all passed, 1 if any failed."""
    tier_map = {a["key"]: a for a in _ADAPTERS}

    log.info("")
    log.info("=" * 60)
    log.info("BACKFILL SUMMARY%s", "  [DRY-RUN]" if dry_run else "")
    log.info("=" * 60)

    failures = []
    warnings = []

    for key, rc in results.items():
        cfg   = tier_map.get(key, {})
        tier  = cfg.get("tier", "?")
        label = cfg.get("label", key)

        if rc == 0:
            status = "✓ PASS"
        elif rc == 4:
            # exit code 4 = stale but Tier-2 (non-blocking)
            status = "⚠ WARN (stale)"
            warnings.append(key)
        else:
            status = f"✗ FAIL (exit={rc})"
            failures.append(key)

        log.info("  [T%-3s] %-30s %s", tier, label, status)

    log.info("-" * 60)
    log.info(
        "  %d adapter(s) run | %d failed | %d warned | %.1fs total",
        len(results), len(failures), len(warnings), elapsed_total,
    )

    if failures:
        log.error("FAILED adapters: %s", failures)
        log.error(
            "Check logs above for details. "
            "Tier-1 failures will block snapshot publishing."
        )
        return 1

    if warnings:
        log.warning(
            "Stale Tier-2 series: %s — snapshot publishing is NOT blocked.", warnings
        )

    log.info("All adapters completed successfully.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Layer-2 backfill orchestrator — runs all Mr. Ripley data adapters "
            "in dependency order."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes (mutually exclusive):
  default              Daily top-up — last 5 days for all adapters (safe to re-run)
  --full-history       Full history load — use for first-time setup or complete rebuild
  --start-date / --end-date  Explicit date window (all adapters use the same window)

Examples:
  # Daily EOD job
  python layer2/run_backfill.py

  # First-time setup (with gold JSON bulk load)
  python layer2/run_backfill.py --full-history --gold-json FRED/2014GOLD/gold_xauusd_stooq_2014_yesterday.json

  # Dry-run preview
  python layer2/run_backfill.py --dry-run

  # Repair specific window
  python layer2/run_backfill.py --start-date 2026-01-01 --end-date 2026-02-28

  # Run only gold, SPY, and FRED (skip MOVE and GLD)
  python layer2/run_backfill.py --only gold spy fred

  # Run everything except FRED (no API key yet)
  python layer2/run_backfill.py --skip fred
        """
    )

    p.add_argument(
        "--db", default=DB_PATH,
        help=f"SQLite DB path (default: {DB_PATH} or L2_DB_PATH env).",
    )
    p.add_argument(
        "--full-history", action="store_true",
        help="Load full history for all adapters. Use for first-time setup.",
    )
    p.add_argument(
        "--gold-json", type=str, default=None,
        metavar="PATH",
        help=(
            "Path to gold_xauusd_stooq_2014_yesterday.json for bulk gold history load. "
            "Used with --full-history or daily mode."
        ),
    )
    p.add_argument(
        "--start-date", type=str, default=None,
        metavar="YYYY-MM-DD",
        help="Start of explicit date window (all adapters). Overrides --full-history.",
    )
    p.add_argument(
        "--end-date", type=str, default=None,
        metavar="YYYY-MM-DD",
        help="End of explicit date window (default: yesterday).",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and parse but do NOT write to DB. Passes --dry-run to all adapters.",
    )
    p.add_argument(
        "--skip", nargs="+", choices=_ADAPTER_KEYS, default=[],
        metavar="ADAPTER",
        help=f"Adapters to skip. Choices: {_ADAPTER_KEYS}",
    )
    p.add_argument(
        "--only", nargs="+", choices=_ADAPTER_KEYS, default=[],
        metavar="ADAPTER",
        help=f"Run only these adapters (in registry order). Choices: {_ADAPTER_KEYS}",
    )
    p.add_argument(
        "--python", type=str, default=sys.executable,
        help="Python interpreter to use (default: same interpreter running this script).",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    # Validate date window
    start_date: Optional[date] = None
    end_date:   Optional[date] = None

    if args.start_date or args.end_date:
        end_date   = date.fromisoformat(args.end_date)   if args.end_date   else date.today() - timedelta(days=1)
        start_date = date.fromisoformat(args.start_date) if args.start_date else end_date - timedelta(days=29)
        if start_date > end_date:
            log.error("--start-date %s is after --end-date %s", start_date, end_date)
            return 1

    # Determine mode
    if start_date or end_date:
        mode = "window"
    elif args.full_history:
        mode = "full_history"
    else:
        mode = "daily"

    # Validate gold JSON if provided
    if args.gold_json and not Path(args.gold_json).exists():
        log.error("--gold-json file not found: %s", args.gold_json)
        return 1

    # Select adapters
    if args.only:
        # Preserve registry order even when --only is specified
        adapters = [a for a in _ADAPTERS if a["key"] in args.only]
    elif args.skip:
        adapters = [a for a in _ADAPTERS if a["key"] not in args.skip]
    else:
        adapters = list(_ADAPTERS)

    if not adapters:
        log.error("No adapters selected. Check --only / --skip arguments.")
        return 1

    # Announce
    log.info("=" * 60)
    log.info("Mr. Ripley — Layer-2 Backfill Orchestrator")
    log.info("=" * 60)
    log.info("Mode:      %s", mode.upper())
    log.info("DB:        %s", args.db)
    log.info("Dry-run:   %s", args.dry_run)
    log.info("Adapters:  %s", [a["key"] for a in adapters])
    if start_date:
        log.info("Window:    %s → %s", start_date, end_date)
    if args.gold_json:
        log.info("Gold JSON: %s", args.gold_json)
    log.info("")

    t0 = time.monotonic()
    results = run_all(
        adapters_to_run=adapters,
        mode=mode,
        db_path=args.db,
        dry_run=args.dry_run,
        python=args.python,
        gold_json=args.gold_json,
        start_date=start_date,
        end_date=end_date,
    )
    elapsed = time.monotonic() - t0

    return _print_summary(results, elapsed, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
