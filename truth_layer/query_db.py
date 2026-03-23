"""
query_db.py
-----------
Interactive CLI inspector for layer2_truth.db.

Lets you browse and query the observations, snapshots, and snapshot_values
tables without writing raw SQL. All output is formatted for readability.
Registry-aware: --freshness and --registry commands cross-reference
series_registry.json so you see every series, including ones not yet in DB.

Usage:
    python query_db.py --status
    python query_db.py --counts
    python query_db.py --freshness                     ← registry-aware staleness for ALL series
    python query_db.py --freshness --tier 1            ← Tier-1 only
    python query_db.py --registry                      ← dump full registry table
    python query_db.py --registry --tier 2
    python query_db.py --series DGS10
    python query_db.py --series DGS10 --tail 20
    python query_db.py --series DGS10 --from 2026-01-01 --to 2026-03-07
    python query_db.py --compare DGS10 DGS2 DFF
    python query_db.py --snapshots
    python query_db.py --snapshot-detail <snapshot_id>
    python query_db.py --sql "SELECT * FROM observations LIMIT 5"
    python query_db.py --tables
    python query_db.py --schema observations
    python query_db.py --gaps DGS10
    python query_db.py --export DGS10 --out dgs10.csv
    python query_db.py --export-all --out all_series.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_PATH: str = os.getenv("L2_DB_PATH", "layer2_truth.db")

# ---------------------------------------------------------------------------
# ANSI colours (disabled automatically if not a tty)
# ---------------------------------------------------------------------------

_USE_COLOUR = sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOUR else text

def bold(t):    return _c("1", t)
def cyan(t):    return _c("36", t)
def green(t):   return _c("32", t)
def yellow(t):  return _c("33", t)
def red(t):     return _c("31", t)
def dim(t):     return _c("2", t)
def magenta(t): return _c("35", t)

# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------

def get_conn(db_path: str) -> sqlite3.Connection:
    p = Path(db_path)
    if not p.exists():
        print(red(f"ERROR: Database not found: {db_path}"))
        print(dim("  Set L2_DB_PATH env var or pass --db <path>"))
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

# ---------------------------------------------------------------------------
# Registry loader (optional — graceful degradation if registry not available)
# ---------------------------------------------------------------------------

def _try_load_registry():
    """
    Attempt to load the Layer-2 series registry.
    Returns a SeriesRegistry instance or None if unavailable.
    Graceful: query_db.py works without the registry (just loses --freshness / --registry).
    """
    _HERE = Path(__file__).resolve().parent
    for _candidate in [_HERE.parent, _HERE]:
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))

    try:
        from layer2.config.registry import get_registry  # type: ignore
        return get_registry()
    except Exception:
        pass
    # Try path relative to this file (handles running from repo root or layer2/)
    for search in [_HERE, _HERE.parent, _HERE.parent.parent]:
        reg_path = search / "layer2" / "config" / "series_registry.json"
        if reg_path.exists():
            try:
                from layer2.config.registry import SeriesRegistry  # type: ignore
                return SeriesRegistry(reg_path)
            except Exception:
                pass
    return None

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_val(v, width: int = 10) -> str:
    if v is None:
        return dim("—").ljust(width)
    if isinstance(v, float):
        return f"{v:>{width}.4f}"
    return str(v).ljust(width)

def _sep(width: int = 80) -> str:
    return dim("─" * width)

def _table(headers: List[str], rows: List[tuple], col_widths: Optional[List[int]] = None) -> None:
    if col_widths is None:
        col_widths = [max(len(str(h)), max((len(str(r[i])) for r in rows), default=0))
                      for i, h in enumerate(headers)]
    header_line = "  ".join(bold(str(h).ljust(w)) for h, w in zip(headers, col_widths))
    print(header_line)
    print(dim("  ".join("─" * w for w in col_widths)))
    for row in rows:
        print("  ".join(str(v).ljust(w) for v, w in zip(row, col_widths)))

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_tables(conn: sqlite3.Connection) -> None:
    """List all tables in the database."""
    rows = conn.execute(
        "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
    ).fetchall()
    print(bold("\nTables in database:"))
    print(_sep(40))
    for r in rows:
        print(f"  {cyan(r['name']):<30} {dim(r['type'])}")
    print()


def cmd_schema(conn: sqlite3.Connection, table: str) -> None:
    """Print CREATE statement for a table."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = ?", (table,)
    ).fetchone()
    if not row:
        print(red(f"Table not found: {table!r}"))
        sys.exit(1)
    print(bold(f"\nSchema for {cyan(table)}:"))
    print(_sep(60))
    print(row["sql"])
    print()


def cmd_counts(conn: sqlite3.Connection) -> None:
    """Row counts and date ranges per series in observations."""
    rows = conn.execute("""
        SELECT
            series_id,
            COUNT(*)        AS rows,
            MIN(obs_ts)     AS first_obs,
            MAX(obs_ts)     AS last_obs,
            MAX(ingested_at) AS last_ingested
        FROM observations
        GROUP BY series_id
        ORDER BY series_id
    """).fetchall()

    if not rows:
        print(yellow("No observations in database yet."))
        return

    today = date.today()
    print(bold(f"\nObservations summary ({len(rows)} series):"))
    print(_sep(100))
    headers = ["series_id", "rows", "first_obs", "last_obs", "staleness", "last_ingested"]
    widths   = [30, 7, 12, 12, 11, 26]
    print("  ".join(bold(h.ljust(w)) for h, w in zip(headers, widths)))
    print(dim("  ".join("─" * w for w in widths)))

    for r in rows:
        last = r["last_obs"]
        if last:
            last_date = date.fromisoformat(last[:10])
            staleness = (today - last_date).days
            stale_str = f"{staleness}d ago"
            stale_col = green(stale_str) if staleness <= 5 else (yellow(stale_str) if staleness <= 14 else red(stale_str))
        else:
            stale_col = dim("N/A")
            stale_str = "N/A"

        print(
            f"  {cyan(r['series_id']):<30}  "
            f"{str(r['rows']):<7}  "
            f"{str(r['first_obs'] or '—'):<12}  "
            f"{str(r['last_obs'] or '—'):<12}  "
            f"{stale_col:<11}  "
            f"{dim(str(r['last_ingested'] or '—'))}"
        )
    print()


def cmd_freshness(conn: sqlite3.Connection, tier_filter: Optional[int] = None) -> None:
    """
    Registry-aware staleness report.
    Shows EVERY series in the registry, including those with no DB rows yet.
    Uses the registry's staleness_days threshold for PASS / WARN / FAIL verdict.
    """
    reg = _try_load_registry()
    if reg is None:
        print(yellow(
            "Registry not available — cannot run --freshness.\n"
            "Ensure layer2/config/series_registry.json exists and "
            "layer2/config/registry.py is on the Python path."
        ))
        return

    today = date.today()

    # Pull latest obs for all series in one query
    db_rows = conn.execute("""
        SELECT series_id, MAX(obs_ts) AS last_obs, COUNT(*) AS row_count
        FROM observations
        GROUP BY series_id
    """).fetchall()
    db_map = {r["series_id"]: (r["last_obs"], r["row_count"]) for r in db_rows}

    series_list = reg.all_series()
    if tier_filter is not None:
        series_list = [s for s in series_list if s["tier"] == tier_filter]

    pass_n = warn_n = fail_n = missing_n = 0

    print(bold(f"\nFreshness Report — {len(series_list)} series  (clock: {today})"))
    if tier_filter:
        print(dim(f"  Filtered to Tier-{tier_filter}"))
    print(_sep(110))

    widths = [30, 4, 6, 10, 7, 8, 8, 8, 7]
    headers = ["series_id", "tier", "freq", "group", "rows", "last_obs", "stale_d", "thresh", "verdict"]
    print("  " + "  ".join(bold(h.ljust(w)) for h, w in zip(headers, widths)))
    print("  " + dim("  ".join("─" * w for w in widths)))

    for s in series_list:
        sid         = s["series_id"]
        threshold   = s["staleness_days"]
        blocks      = s["blocks_snapshot"]
        discontinued = s["discontinued"]

        last_str, row_count, staleness_days, verdict_str, verdict_col = \
            _compute_freshness(sid, db_map, today, threshold, blocks, discontinued)

        if verdict_str == "PASS":   pass_n += 1
        elif verdict_str == "WARN": warn_n += 1
        elif verdict_str == "FAIL": fail_n += 1
        else:                       missing_n += 1

        print(
            f"  {cyan(sid):<30}  "
            f"T{s['tier']:<3}  "
            f"{s['frequency']:<6}  "
            f"{s['group']:<10}  "
            f"{str(row_count):<7}  "
            f"{last_str:<8}  "
            f"{str(staleness_days) + 'd' if staleness_days is not None else '—':<8}  "
            f"{str(threshold) + 'd':<8}  "
            f"{verdict_col}"
        )

    print(_sep(110))
    print(
        f"  {green(str(pass_n))} PASS  "
        f"{yellow(str(warn_n))} WARN  "
        f"{red(str(fail_n))} FAIL  "
        f"{dim(str(missing_n))} NO DATA"
    )
    print()


def _compute_freshness(
    sid: str,
    db_map: dict,
    today: date,
    threshold: int,
    blocks: bool,
    discontinued: bool,
) -> tuple:
    """Return (last_str, row_count, staleness_days, verdict_str, verdict_col)."""
    if sid not in db_map:
        return "—", 0, None, "NO DATA", dim("NO DATA")

    last_raw, row_count = db_map[sid]
    if not last_raw:
        return "—", row_count, None, "NO DATA", dim("NO DATA")

    last_date = date.fromisoformat(last_raw[:10])
    staleness = (today - last_date).days

    if discontinued:
        verdict_str = "OK"
        verdict_col = dim("OK (disc.)")
    elif staleness <= threshold:
        verdict_str = "PASS"
        verdict_col = green("PASS")
    elif blocks:
        verdict_str = "FAIL"
        verdict_col = red("FAIL ✗")
    else:
        verdict_str = "WARN"
        verdict_col = yellow("WARN ⚠")

    return last_raw[:10], row_count, staleness, verdict_str, verdict_col


def cmd_registry(tier_filter: Optional[int] = None) -> None:
    """Print full registry metadata table."""
    reg = _try_load_registry()
    if reg is None:
        print(yellow(
            "Registry not available — cannot run --registry.\n"
            "Ensure layer2/config/series_registry.json exists on the Python path."
        ))
        return

    series_list = reg.all_series()
    if tier_filter is not None:
        series_list = [s for s in series_list if s["tier"] == tier_filter]

    print(bold(f"\nSeries Registry  v{reg.version}  ({len(series_list)} series)"))
    if tier_filter:
        print(dim(f"  Filtered to Tier-{tier_filter}"))
    print(_sep(120))

    widths = [30, 4, 6, 10, 8, 7, 7, 8, 16, 12]
    headers = [
        "series_id", "tier", "freq", "group",
        "stale_d", "blocks", "disc.", "estimate",
        "full_hist_start", "source",
    ]
    print("  " + "  ".join(bold(h.ljust(w)) for h, w in zip(headers, widths)))
    print("  " + dim("  ".join("─" * w for w in widths)))

    for s in series_list:
        print(
            f"  {cyan(s['series_id']):<30}  "
            f"T{s['tier']:<3}  "
            f"{s['frequency']:<6}  "
            f"{s['group']:<10}  "
            f"{str(s['staleness_days']) + 'd':<8}  "
            f"{'yes' if s['blocks_snapshot'] else 'no':<7}  "
            f"{'yes' if s['discontinued'] else 'no':<7}  "
            f"{'yes' if s['is_estimate'] else 'no':<8}  "
            f"{s['full_history_start']:<16}  "
            f"{s['source']}"
        )
    print()

    summary = reg.summary()
    print(dim(
        f"  Total={summary['total_series']}  "
        f"Tier1={summary['tier1_count']}  "
        f"Tier2={summary['tier2_count']}  "
        f"Snapshot={summary['snapshot_count']}  "
        f"Discontinued={summary['discontinued_count']}  "
        f"Estimate={summary['estimate_count']}"
    ))
    print()


def cmd_series(
    conn: sqlite3.Connection,
    series_id: str,
    tail: int = 30,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> None:
    """Show observations for a single series."""
    params: list = [series_id]
    where = "WHERE series_id = ?"
    if from_date:
        where += " AND obs_ts >= ?"
        params.append(from_date)
    if to_date:
        where += " AND obs_ts <= ?"
        params.append(to_date)

    count = conn.execute(
        f"SELECT COUNT(*) AS n FROM observations {where}", params
    ).fetchone()["n"]

    if count == 0:
        print(yellow(f"No observations found for {series_id!r}"))
        return

    rows = conn.execute(
        f"""
        SELECT obs_ts, value, revision_seq, source, as_of_ts, ingested_at
        FROM observations
        {where}
        ORDER BY obs_ts DESC, revision_seq DESC
        LIMIT ?
        """,
        params + [tail],
    ).fetchall()

    date_range = ""
    if from_date or to_date:
        date_range = f" [{from_date or '...'} → {to_date or '...'}]"

    print(bold(f"\n{cyan(series_id)}{date_range}  —  {count} total rows  (showing {len(rows)})"))
    print(_sep(80))

    headers = ["obs_ts", "value", "rev", "source", "as_of_ts", "ingested_at"]
    widths   = [12, 12, 4, 20, 26, 26]
    print("  ".join(bold(h.ljust(w)) for h, w in zip(headers, widths)))
    print(dim("  ".join("─" * w for w in widths)))

    for r in rows:
        rev_col = dim(str(r["revision_seq"])) if r["revision_seq"] == 0 else yellow(str(r["revision_seq"]))
        print(
            f"  {r['obs_ts']:<12}  "
            f"{r['value']:>12.6f}  "
            f"{rev_col:<4}  "
            f"{str(r['source']):<20}  "
            f"{dim(str(r['as_of_ts'] or '—')):<26}  "
            f"{dim(str(r['ingested_at'] or '—'))}"
        )
    if count > tail:
        print(dim(f"  ... {count - tail} earlier rows not shown. Use --tail {count} or --from to narrow."))
    print()


def cmd_compare(conn: sqlite3.Connection, series_ids: List[str], tail: int = 20) -> None:
    """Side-by-side comparison of latest values for multiple series."""
    print(bold(f"\nComparing: {', '.join(cyan(s) for s in series_ids)}  (last {tail} dates)"))
    print(_sep(80))

    placeholders = ",".join("?" * len(series_ids))
    dates = conn.execute(
        f"""
        SELECT DISTINCT obs_ts FROM observations
        WHERE series_id IN ({placeholders})
        ORDER BY obs_ts DESC
        LIMIT ?
        """,
        series_ids + [tail],
    ).fetchall()
    dates = [r["obs_ts"] for r in dates]

    if not dates:
        print(yellow("No data found for any of the given series."))
        return

    data: dict = {s: {} for s in series_ids}
    for row in conn.execute(
        f"""
        SELECT series_id, obs_ts, value FROM observations
        WHERE series_id IN ({placeholders})
          AND obs_ts IN ({','.join('?' * len(dates))})
        ORDER BY obs_ts DESC, revision_seq DESC
        """,
        series_ids + dates,
    ).fetchall():
        if row["obs_ts"] not in data[row["series_id"]]:
            data[row["series_id"]][row["obs_ts"]] = row["value"]

    col_w = 14
    header = f"  {'date':<12}" + "".join(bold(s.rjust(col_w)) for s in series_ids)
    print(header)
    print(dim(f"  {'─'*12}" + ("─" * col_w) * len(series_ids)))

    for d in dates:
        line = f"  {d:<12}"
        for s in series_ids:
            v = data[s].get(d)
            if v is None:
                line += dim("—".rjust(col_w))
            else:
                line += f"{v:>{col_w}.4f}"
        print(line)
    print()


def cmd_snapshots(conn: sqlite3.Connection) -> None:
    """List all snapshots."""
    try:
        rows = conn.execute(
            """
            SELECT snapshot_id, clock_ts, verdict, tier1_pass, tier1_fail,
                   tier2_warn, series_count, dry_run, forced, created_at
            FROM snapshots
            ORDER BY clock_ts DESC
            LIMIT 50
            """
        ).fetchall()
    except sqlite3.OperationalError:
        print(yellow("No snapshots table found. Run snapshot_publisher.py first."))
        return

    if not rows:
        print(yellow("No snapshots in database yet."))
        return

    print(bold(f"\nSnapshots ({len(rows)} most recent):"))
    print(_sep(100))

    for r in rows:
        verdict = r["verdict"]
        v_col = green(verdict) if verdict == "PASS" else red(verdict)
        flags = []
        if r["dry_run"]: flags.append(yellow("dry-run"))
        if r["forced"]:  flags.append(magenta("forced"))
        flag_str = f"  [{', '.join(flags)}]" if flags else ""

        print(
            f"  {cyan(r['snapshot_id'][:16])}…  "
            f"{r['clock_ts']:<24}  "
            f"{v_col:<6}  "
            f"T1: {green(str(r['tier1_pass']))}✓ {red(str(r['tier1_fail']))}✗  "
            f"T2: {yellow(str(r['tier2_warn']))}⚠  "
            f"n={r['series_count']}"
            f"{flag_str}"
        )
    print()
    print(dim("  Use --snapshot-detail <id_prefix> to inspect a specific snapshot."))
    print()


def cmd_snapshot_detail(conn: sqlite3.Connection, snapshot_prefix: str) -> None:
    """Show full detail for a specific snapshot."""
    try:
        snap = conn.execute(
            "SELECT * FROM snapshots WHERE snapshot_id LIKE ?",
            (f"{snapshot_prefix}%",)
        ).fetchone()
    except sqlite3.OperationalError:
        print(yellow("No snapshots table found."))
        return

    if not snap:
        print(red(f"No snapshot found matching: {snapshot_prefix!r}"))
        return

    sid = snap["snapshot_id"]
    verdict = snap["verdict"]
    v_col = green(verdict) if verdict == "PASS" else red(verdict)

    print(bold(f"\nSnapshot: {cyan(sid)}"))
    print(_sep(80))
    print(f"  Clock:    {snap['clock_ts']}")
    print(f"  Created:  {snap['created_at']}")
    print(f"  Verdict:  {v_col}")
    print(f"  Tier-1:   {green(str(snap['tier1_pass']))} pass / {red(str(snap['tier1_fail']))} fail  (of {snap['tier1_series']})")
    print(f"  Tier-2:   {yellow(str(snap['tier2_warn']))} warn  (of {snap['tier2_series']})")
    print(f"  Dry-run:  {snap['dry_run']}  |  Forced: {snap['forced']}")

    values = conn.execute(
        """
        SELECT series_id, tier, group_name, obs_ts, value, staleness_days, source
        FROM snapshot_values
        WHERE snapshot_id = ?
        ORDER BY tier, group_name, series_id
        """,
        (sid,)
    ).fetchall()

    if values:
        print(bold(f"\n  Series values ({len(values)}):"))
        print(dim("  " + "─" * 78))
        headers = ["series_id", "tier", "group", "obs_ts", "value", "stale_d", "source"]
        widths   = [30, 5, 18, 12, 14, 8, 20]
        print("  " + "  ".join(bold(h.ljust(w)) for h, w in zip(headers, widths)))
        print("  " + dim("  ".join("─" * w for w in widths)))
        for v in values:
            print(
                f"  {cyan(v['series_id']):<30}  "
                f"T{v['tier']:<4}  "
                f"{str(v['group_name']):<18}  "
                f"{str(v['obs_ts']):<12}  "
                f"{v['value']:>14.6f}  "
                f"{str(v['staleness_days']):<8}  "
                f"{v['source']}"
            )
    print()


def cmd_gaps(conn: sqlite3.Connection, series_id: str, max_gap: int = 3) -> None:
    """Find suspiciously large gaps in a daily series."""
    rows = conn.execute(
        """
        SELECT obs_ts FROM observations
        WHERE series_id = ?
        ORDER BY obs_ts ASC
        """,
        (series_id,)
    ).fetchall()

    if not rows:
        print(yellow(f"No data for {series_id!r}"))
        return

    dates = [date.fromisoformat(r["obs_ts"][:10]) for r in rows]
    gaps = []
    for i in range(1, len(dates)):
        delta = (dates[i] - dates[i - 1]).days
        if delta > max_gap:
            gaps.append((dates[i - 1], dates[i], delta))

    print(bold(f"\nGap analysis for {cyan(series_id)}  (gaps > {max_gap} days):"))
    print(_sep(60))
    print(f"  Total observations: {len(dates)}")
    print(f"  Range:  {dates[0]}  →  {dates[-1]}")

    if not gaps:
        print(green(f"  No gaps > {max_gap} days found. ✓"))
    else:
        print(yellow(f"  {len(gaps)} gap(s) found:"))
        print()
        headers = ["from", "to", "gap_days"]
        widths   = [12, 12, 10]
        print("  " + "  ".join(bold(h.ljust(w)) for h, w in zip(headers, widths)))
        print("  " + dim("  ".join("─" * w for w in widths)))
        for from_d, to_d, delta in gaps:
            col = yellow if delta <= 7 else red
            print(f"  {str(from_d):<12}  {str(to_d):<12}  {col(str(delta) + 'd')}")
    print()


def cmd_sql(conn: sqlite3.Connection, query: str) -> None:
    """Run arbitrary read-only SQL and print results."""
    q = query.strip().upper()
    for kw in ("INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "REPLACE"):
        if q.startswith(kw):
            print(red(f"ERROR: Write statements are not allowed. Use sqlite3 directly for writes."))
            sys.exit(1)

    try:
        rows = conn.execute(query).fetchall()
    except sqlite3.Error as e:
        print(red(f"SQL error: {e}"))
        sys.exit(1)

    if not rows:
        print(yellow("Query returned no rows."))
        return

    keys = list(rows[0].keys())
    widths = [max(len(k), max(len(str(r[k])) for r in rows)) for k in keys]

    print(bold(f"\nQuery results ({len(rows)} rows):"))
    print(_sep(sum(widths) + 3 * len(widths)))
    print("  ".join(bold(k.ljust(w)) for k, w in zip(keys, widths)))
    print(dim("  ".join("─" * w for w in widths)))
    for row in rows:
        print("  ".join(str(row[k]).ljust(w) for k, w in zip(keys, widths)))
    print()


def cmd_export(conn: sqlite3.Connection, series_id: str, out_path: str) -> None:
    """Export a single series to CSV."""
    rows = conn.execute(
        """
        SELECT series_id, obs_ts, value, revision_seq, source, as_of_ts, ingested_at
        FROM observations
        WHERE series_id = ?
        ORDER BY obs_ts ASC, revision_seq ASC
        """,
        (series_id,)
    ).fetchall()

    if not rows:
        print(yellow(f"No data for {series_id!r}"))
        return

    _write_csv(rows, out_path, ["series_id", "obs_ts", "value", "revision_seq", "source", "as_of_ts", "ingested_at"])
    print(green(f"Exported {len(rows)} rows → {Path(out_path).resolve()}"))


def cmd_export_all(conn: sqlite3.Connection, out_path: str) -> None:
    """
    Export ALL series from observations to a single CSV, sorted by series_id then obs_ts.
    Includes every column so the file is a complete snapshot of the observations table.
    """
    rows = conn.execute(
        """
        SELECT series_id, obs_ts, value, revision_seq, source, as_of_ts, ingested_at
        FROM observations
        ORDER BY series_id ASC, obs_ts ASC, revision_seq ASC
        """
    ).fetchall()

    if not rows:
        print(yellow("No observations in database — nothing to export."))
        return

    _write_csv(rows, out_path, ["series_id", "obs_ts", "value", "revision_seq", "source", "as_of_ts", "ingested_at"])

    # Summary by series
    counts: dict = {}
    for r in rows:
        counts[r["series_id"]] = counts.get(r["series_id"], 0) + 1

    print(green(f"Exported {len(rows):,} rows across {len(counts)} series → {Path(out_path).resolve()}"))
    print(dim("  Series included:"))
    for sid, n in sorted(counts.items()):
        print(dim(f"    {sid:<35} {n:>7} rows"))
    print()


def _write_csv(rows, out_path: str, fieldnames: List[str]) -> None:
    p = Path(out_path)
    with p.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(fieldnames)
        for r in rows:
            writer.writerow([r[col] for col in fieldnames])


def cmd_status(conn: sqlite3.Connection) -> None:
    """High-level health summary across all series."""
    today = date.today()

    obs_rows = conn.execute(
        """
        SELECT series_id, COUNT(*) AS n, MAX(obs_ts) AS last_obs
        FROM observations
        GROUP BY series_id
        ORDER BY series_id
        """
    ).fetchall()

    try:
        snap_row = conn.execute(
            "SELECT COUNT(*) AS n, MAX(clock_ts) AS last FROM snapshots"
        ).fetchone()
        snap_count = snap_row["n"]
        snap_last  = snap_row["last"]
    except sqlite3.OperationalError:
        snap_count = 0
        snap_last  = None

    total_rows = conn.execute("SELECT COUNT(*) AS n FROM observations").fetchone()["n"]

    reg = _try_load_registry()
    registry_total = len(reg.all_series()) if reg else "?"

    print(bold("\n╔══════════════════════════════════════╗"))
    print(bold("║   Layer-2 Database Health Summary    ║"))
    print(bold("╚══════════════════════════════════════╝"))
    print(f"  DB path:         {cyan(os.getenv('L2_DB_PATH', 'layer2_truth.db'))}")
    print(f"  Today:           {today}")
    print(f"  Series in DB:    {bold(str(len(obs_rows)))}  (registry: {registry_total})")
    print(f"  Total rows:      {bold(f'{total_rows:,}')}")
    print(f"  Snapshots:       {bold(str(snap_count))}  (last: {snap_last or dim('none')})")
    print()

    if not obs_rows:
        print(yellow("  No observations loaded yet."))
        return

    pass_n = warn_n = fail_n = 0
    for r in obs_rows:
        last = r["last_obs"]
        if last:
            days = (today - date.fromisoformat(last[:10])).days
            if days <= 5:    pass_n += 1
            elif days <= 14: warn_n += 1
            else:            fail_n += 1
        else:
            fail_n += 1

    print(f"  Freshness:       {green(str(pass_n))} fresh  {yellow(str(warn_n))} stale  {red(str(fail_n))} missing/old")
    print()
    print(dim("  Commands: --counts | --freshness | --registry | --snapshots"))
    print()

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Layer-2 DB inspector — query and browse layer2_truth.db.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python query_db.py --status
  python query_db.py --counts
  python query_db.py --freshness                    # registry-aware staleness, all series
  python query_db.py --freshness --tier 1           # Tier-1 only
  python query_db.py --registry                     # full registry metadata table
  python query_db.py --registry --tier 2
  python query_db.py --series DGS10
  python query_db.py --series DGS10 --tail 50
  python query_db.py --series DGS10 --from 2026-01-01 --to 2026-03-07
  python query_db.py --compare DGS10 DGS2 DFF VIXCLS
  python query_db.py --snapshots
  python query_db.py --snapshot-detail abc123
  python query_db.py --gaps DGS10
  python query_db.py --gaps DGS10 --max-gap 5
  python query_db.py --export DGS10 --out dgs10.csv
  python query_db.py --export-all --out all_series.csv
  python query_db.py --sql "SELECT series_id, COUNT(*) FROM observations GROUP BY series_id"
  python query_db.py --tables
  python query_db.py --schema observations
        """
    )

    p.add_argument("--db", default=DB_PATH,
                   help=f"Path to SQLite DB (default: {DB_PATH} or L2_DB_PATH env).")

    # Display modes
    g = p.add_mutually_exclusive_group()
    g.add_argument("--status",          action="store_true", help="Overall health summary.")
    g.add_argument("--counts",          action="store_true", help="Row counts + date ranges per series.")
    g.add_argument("--freshness",       action="store_true",
                   help="Registry-aware staleness report. Shows ALL series (including missing from DB).")
    g.add_argument("--registry",        action="store_true",
                   help="Print full series registry metadata table.")
    g.add_argument("--tables",          action="store_true", help="List all tables.")
    g.add_argument("--schema",          metavar="TABLE",     help="Print CREATE statement for a table.")
    g.add_argument("--series",          metavar="SERIES_ID", help="Show observations for a series.")
    g.add_argument("--compare",         nargs="+",           metavar="SERIES_ID", help="Side-by-side latest values.")
    g.add_argument("--snapshots",       action="store_true", help="List snapshots.")
    g.add_argument("--snapshot-detail", metavar="ID_PREFIX", help="Full detail for one snapshot.")
    g.add_argument("--gaps",            metavar="SERIES_ID", help="Find date gaps in a series.")
    g.add_argument("--export",          metavar="SERIES_ID", help="Export one series to CSV.")
    g.add_argument("--export-all",      action="store_true",
                   help="Export ALL series from observations to a single CSV.")
    g.add_argument("--sql",             metavar="QUERY",     help="Run a read-only SQL query.")

    # Modifiers
    p.add_argument("--tail",    type=int, default=30,   help="Rows to show for --series / --compare (default: 30).")
    p.add_argument("--from",    dest="from_date",       help="Start date filter YYYY-MM-DD.")
    p.add_argument("--to",      dest="to_date",         help="End date filter YYYY-MM-DD.")
    p.add_argument("--max-gap", type=int, default=3,    help="Min gap size to flag in --gaps (default: 3 days).")
    p.add_argument("--out",     default="export.csv",   help="Output CSV path for --export / --export-all (default: export.csv).")
    p.add_argument("--tier",    type=int, default=None, choices=[1, 2],
                   help="Filter --freshness or --registry to a specific tier.")

    return p.parse_args()


def main() -> int:
    args = parse_args()

    # Commands that don't need a DB connection
    if args.registry:
        cmd_registry(tier_filter=args.tier)
        return 0

    conn = get_conn(args.db)

    if args.status:
        cmd_status(conn)
    elif args.counts:
        cmd_counts(conn)
    elif args.freshness:
        cmd_freshness(conn, tier_filter=args.tier)
    elif args.tables:
        cmd_tables(conn)
    elif args.schema:
        cmd_schema(conn, args.schema)
    elif args.series:
        cmd_series(conn, args.series, tail=args.tail,
                   from_date=args.from_date, to_date=args.to_date)
    elif args.compare:
        cmd_compare(conn, args.compare, tail=args.tail)
    elif args.snapshots:
        cmd_snapshots(conn)
    elif args.snapshot_detail:
        cmd_snapshot_detail(conn, args.snapshot_detail)
    elif args.gaps:
        cmd_gaps(conn, args.gaps, max_gap=args.max_gap)
    elif args.export:
        cmd_export(conn, args.export, args.out)
    elif args.export_all:
        cmd_export_all(conn, args.out)
    elif args.sql:
        cmd_sql(conn, args.sql)
    else:
        cmd_status(conn)

    return 0


if __name__ == "__main__":
    sys.exit(main())
