# layer2/index_suite.py
"""
index_suite.py
--------------
Governed M1 Index Suite for the Gold-First Market State Engine.

Purpose
-------
Compute provisional, versioned M1 indices from point-in-time correct Layer-2 data:

    - stress_index
    - corrbreak_index
    - drift_index
    - data_freshness_penalty

Design principles
-----------------
- Deterministic
- Replay-safe
- Versioned
- Point-in-time correct (as_of / clock governed)
- MOVE feeds governance only (stress / corrbreak), not direction

Important
---------
These mappings are provisional M1 specs. They are intentionally versioned and
must not be treated as frozen truths until M2 calibration.

Inputs
------
- governed clock_ts from layer2.clock
- aligned payload from quality_gate or layer2.alignment
- historical observations from Layer-2 truth DB, selected point-in-time correct

Outputs
-------
A dict / JSON payload containing:
- clock_ts / clock_date
- index_version
- stress_index
- corrbreak_index
- drift_index
- data_freshness_penalty
- component breakdowns
- null / degraded flags

Example
-------
    python -m layer2.index_suite --clock-date 2026-03-07 --json
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sqlite3
import statistics
import sys
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

_HERE = Path(__file__).resolve().parent
for _candidate in [_HERE.parent.parent, _HERE.parent]:
    if (_candidate / "layer2" / "db.py").exists() or (_candidate / "db.py").exists():
        if str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
        break

from layer2.clock import get_default_policy, get_engine_clock, EngineClock  # noqa: E402
from layer2.db import get_connection  # noqa: E402
from layer2.alignment import align_snapshot_state, build_snapshot_values_payload  # noqa: E402
from layer2.config.registry import get_registry  # noqa: E402

DB_PATH: str = os.getenv("L2_DB_PATH", "layer2_truth.db")
LOG_LEVEL: str = os.getenv("L2_LOG_LEVEL", "INFO")

CLOCK_TIMEZONE: str = os.getenv("L2_CLOCK_TIMEZONE", "UTC")
CLOCK_CUT_HOUR: int = int(os.getenv("L2_CLOCK_CUT_HOUR", "22"))
CLOCK_CUT_MINUTE: int = int(os.getenv("L2_CLOCK_CUT_MINUTE", "0"))
CLOCK_CUT_SECOND: int = int(os.getenv("L2_CLOCK_CUT_SECOND", "0"))
CLOCK_EXCEPTIONS_FILE: str = os.getenv("L2_CLOCK_EXCEPTIONS_FILE", "")
CLOCK_POLICY_VERSION: str = os.getenv("L2_CLOCK_POLICY_VERSION", "clock-v1")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] index_suite: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IndexSuiteConfig:
    """
    Provisional, versioned M1 index math configuration.

    All windows and mappings are intentionally explicit and version-tagged.
    """
    index_version: str = "idx-v1-m1-provisional"
    move_z_window: int = 252
    move_delta_lag: int = 5
    move_delta_z_window: int = 252
    vix_z_window: int = 252
    gold_vol_window_short: int = 20
    gold_vol_window_long: int = 252
    corr_window_short: int = 20
    corr_window_long: int = 60
    beta_window_short: int = 20
    beta_window_long: int = 120
    return_epsilon: float = 1e-12


@dataclass(frozen=True)
class IndexSuiteResult:
    clock_date: str
    clock_ts: str
    index_version: str
    stress_index: Optional[float]
    corrbreak_index: Optional[float]
    drift_index: Optional[float]
    data_freshness_penalty: Optional[float]
    degraded: bool
    null_reasons: List[str]
    components: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_index_suite(
    conn: sqlite3.Connection,
    clock: EngineClock,
    *,
    aligned_payload: Optional[List[Dict[str, Any]]] = None,
    config: Optional[IndexSuiteConfig] = None,
) -> IndexSuiteResult:
    """
    Compute the governed M1 indices as of `clock`.

    If aligned_payload is omitted, it will be computed from layer2.alignment.
    """
    cfg = config or IndexSuiteConfig()

    if aligned_payload is None:
        aligned = align_snapshot_state(conn, clock)
        aligned_payload = build_snapshot_values_payload(aligned)

    values = {row["series_id"]: row for row in aligned_payload}
    null_reasons: List[str] = []

    # ------------------------------------------------------------------
    # Data freshness penalty
    # ------------------------------------------------------------------
    freshness_penalty, freshness_components = compute_data_freshness_penalty(values)

    # ------------------------------------------------------------------
    # Historical point-in-time series pulls
    # ------------------------------------------------------------------
    gold_series = _get_pt_series(conn, "gold_price_proxy", clock)
    move_series = _get_pt_series(conn, "rates_vol_stress_move", clock)
    vix_series = _get_pt_series(conn, "VIXCLS", clock)
    spx_series = _get_pt_series(conn, "SP500", clock)
    usd_series = _get_pt_series(conn, "DTWEXBGS", clock)
    dgs10_series = _get_pt_series(conn, "DGS10", clock)
    t10yie_series = _get_pt_series(conn, "T10YIE", clock)

    real_yield_series = _combine_series_subtract(dgs10_series, t10yie_series)

    # ------------------------------------------------------------------
    # StressIndex
    # ------------------------------------------------------------------
    stress_index = None
    stress_components: Dict[str, Any] = {}

    try:
        stress_index, stress_components = compute_stress_index(
            gold_series=gold_series,
            move_series=move_series,
            vix_series=vix_series,
            spx_series=spx_series,
            cfg=cfg,
        )
    except InsufficientHistoryError as exc:
        null_reasons.append(f"stress_index: {exc}")

    # ------------------------------------------------------------------
    # CorrBreakIndex
    # ------------------------------------------------------------------
    corrbreak_index = None
    corrbreak_components: Dict[str, Any] = {}

    try:
        corrbreak_index, corrbreak_components = compute_corrbreak_index(
            gold_series=gold_series,
            move_series=move_series,
            spx_series=spx_series,
            usd_series=usd_series,
            real_yield_series=real_yield_series,
            cfg=cfg,
        )
    except InsufficientHistoryError as exc:
        null_reasons.append(f"corrbreak_index: {exc}")

    # ------------------------------------------------------------------
    # DriftIndex
    # ------------------------------------------------------------------
    drift_index = None
    drift_components: Dict[str, Any] = {}

    try:
        drift_index, drift_components = compute_drift_index(
            gold_series=gold_series,
            usd_series=usd_series,
            real_yield_series=real_yield_series,
            cfg=cfg,
        )
    except InsufficientHistoryError as exc:
        null_reasons.append(f"drift_index: {exc}")

    degraded = bool(null_reasons)

    return IndexSuiteResult(
        clock_date=clock.clock_date.isoformat(),
        clock_ts=clock.clock_ts.isoformat(),
        index_version=cfg.index_version,
        stress_index=stress_index,
        corrbreak_index=corrbreak_index,
        drift_index=drift_index,
        data_freshness_penalty=freshness_penalty,
        degraded=degraded,
        null_reasons=null_reasons,
        components={
            "stress": stress_components,
            "corrbreak": corrbreak_components,
            "drift": drift_components,
            "freshness": freshness_components,
        },
    )


# ---------------------------------------------------------------------------
# Index math
# ---------------------------------------------------------------------------

def compute_stress_index(
    *,
    gold_series: List[Tuple[date, float]],
    move_series: List[Tuple[date, float]],
    vix_series: List[Tuple[date, float]],
    spx_series: List[Tuple[date, float]],
    cfg: IndexSuiteConfig,
) -> Tuple[float, Dict[str, Any]]:
    """
    Provisional M1 StressIndex.

    MOVE contributes via:
    - z-score over 252 observations
    - 5-step acceleration / spike detector
    consistent with the MOVE validation doctrine.
    """
    _require_len(move_series, cfg.move_z_window + cfg.move_delta_lag, "MOVE history")
    _require_len(vix_series, cfg.vix_z_window, "VIX history")
    _require_len(gold_series, cfg.gold_vol_window_long + 1, "gold history")
    _require_len(spx_series, 6, "SP500 history")

    move_vals = [v for _, v in move_series]
    move_now = move_vals[-1]
    move_z = _zscore_last(move_vals, cfg.move_z_window)

    move_delta_series = _diff_lag(move_vals, cfg.move_delta_lag)
    move_delta_z = _zscore_last(move_delta_series, cfg.move_delta_z_window)

    vix_vals = [v for _, v in vix_series]
    vix_z = _zscore_last(vix_vals, cfg.vix_z_window)

    gold_rets = _log_returns([v for _, v in gold_series])
    gold_vol_short = _stdev_last(gold_rets, cfg.gold_vol_window_short)
    gold_vol_z = _zscore_last(
        _rolling_vols(gold_rets, cfg.gold_vol_window_short),
        cfg.gold_vol_window_long - cfg.gold_vol_window_short + 1,
    )

    spx_vals = [v for _, v in spx_series]
    spx_dd_5d = _drawdown_last_window(spx_vals, 5)

    move_component = _clamp(50 + 15 * move_z, 0, 100)
    if move_delta_z > 3:
        move_component = _clamp(move_component + 20, 0, 100)
    elif move_delta_z > 2:
        move_component = _clamp(move_component + 10, 0, 100)

    vix_component = _clamp(50 + 15 * vix_z, 0, 100)
    gold_vol_component = _clamp(50 + 10 * gold_vol_z, 0, 100)
    spx_dd_component = _clamp(abs(spx_dd_5d) * 800, 0, 100)  # 0.05 dd -> 40

    stress_raw = (
        0.35 * move_component +
        0.30 * vix_component +
        0.20 * gold_vol_component +
        0.15 * spx_dd_component
    )
    stress_index = round(_clamp(stress_raw, 0, 100), 2)

    return stress_index, {
        "move_now": move_now,
        "move_z": round(move_z, 4),
        "move_delta_z": round(move_delta_z, 4),
        "move_component": round(move_component, 2),
        "vix_z": round(vix_z, 4),
        "vix_component": round(vix_component, 2),
        "gold_vol_short": round(gold_vol_short, 6),
        "gold_vol_z": round(gold_vol_z, 4),
        "gold_vol_component": round(gold_vol_component, 2),
        "spx_dd_5d": round(spx_dd_5d, 6),
        "spx_dd_component": round(spx_dd_component, 2),
        "formula": "0.35*MOVE + 0.30*VIX + 0.20*GoldVol + 0.15*SPX drawdown",
    }


def compute_corrbreak_index(
    *,
    gold_series: List[Tuple[date, float]],
    move_series: List[Tuple[date, float]],
    spx_series: List[Tuple[date, float]],
    usd_series: List[Tuple[date, float]],
    real_yield_series: List[Tuple[date, float]],
    cfg: IndexSuiteConfig,
) -> Tuple[float, Dict[str, Any]]:
    """
    Provisional M1 CorrBreakIndex.

    Key idea:
    compare short vs longer rolling relationships and penalize:
    - sign flips
    - large magnitude changes

    MOVE is explicitly part of this governance signal.
    """
    pairs = {
        "gold_move": (gold_series, move_series, 0.15),
        "gold_spx": (gold_series, spx_series, 0.20),
        "gold_usd": (gold_series, usd_series, 0.30),
        "gold_real_yield": (gold_series, real_yield_series, 0.35),
    }

    pair_components: Dict[str, Any] = {}
    weighted_sum = 0.0

    for name, (lhs, rhs, weight) in pairs.items():
        score, meta = _corrbreak_pair_score(
            lhs, rhs,
            short_window=cfg.corr_window_short,
            long_window=cfg.corr_window_long,
        )
        pair_components[name] = meta | {"score": round(score, 2), "weight": weight}
        weighted_sum += weight * score

    return round(_clamp(weighted_sum, 0, 100), 2), pair_components


def compute_drift_index(
    *,
    gold_series: List[Tuple[date, float]],
    usd_series: List[Tuple[date, float]],
    real_yield_series: List[Tuple[date, float]],
    cfg: IndexSuiteConfig,
) -> Tuple[float, Dict[str, Any]]:
    """
    Provisional M1 DriftIndex.

    Measures instability in relationship structure:
    - beta shift gold vs USD
    - beta shift gold vs real yield
    - gold volatility regime shift
    """
    _require_len(gold_series, cfg.beta_window_long + 1, "gold history")
    _require_len(usd_series, cfg.beta_window_long + 1, "USD history")
    _require_len(real_yield_series, cfg.beta_window_long + 1, "real-yield history")

    gold_aligned_usd, usd_aligned = _align_two_series(gold_series, usd_series)
    gold_aligned_ry, ry_aligned = _align_two_series(gold_series, real_yield_series)

    gold_usd_beta_short = _rolling_beta_last(
        gold_aligned_usd, usd_aligned, cfg.beta_window_short
    )
    gold_usd_beta_long = _rolling_beta_last(
        gold_aligned_usd, usd_aligned, cfg.beta_window_long
    )
    usd_beta_shift = abs(gold_usd_beta_short - gold_usd_beta_long)

    gold_ry_beta_short = _rolling_beta_last(
        gold_aligned_ry, ry_aligned, cfg.beta_window_short
    )
    gold_ry_beta_long = _rolling_beta_last(
        gold_aligned_ry, ry_aligned, cfg.beta_window_long
    )
    ry_beta_shift = abs(gold_ry_beta_short - gold_ry_beta_long)

    gold_rets = _log_returns([v for _, v in gold_series])
    vol_short = _stdev_last(gold_rets, cfg.gold_vol_window_short)
    vol_long = _stdev_last(gold_rets, cfg.beta_window_long)
    vol_shift = abs(vol_short - vol_long) / max(abs(vol_long), cfg.return_epsilon)

    drift_raw = (
        35 * min(usd_beta_shift, 1.0) +
        35 * min(ry_beta_shift, 1.0) +
        30 * min(vol_shift, 1.0)
    )
    drift_index = round(_clamp(drift_raw, 0, 100), 2)

    return drift_index, {
        "gold_usd_beta_short": round(gold_usd_beta_short, 6),
        "gold_usd_beta_long": round(gold_usd_beta_long, 6),
        "usd_beta_shift": round(usd_beta_shift, 6),
        "gold_ry_beta_short": round(gold_ry_beta_short, 6),
        "gold_ry_beta_long": round(gold_ry_beta_long, 6),
        "ry_beta_shift": round(ry_beta_shift, 6),
        "gold_vol_short": round(vol_short, 6),
        "gold_vol_long": round(vol_long, 6),
        "vol_shift": round(vol_shift, 6),
    }


def compute_data_freshness_penalty(
    aligned_payload: Dict[str, Dict[str, Any]],
) -> Tuple[float, Dict[str, Any]]:
    """
    Deterministic freshness penalty from aligned payload.

    Rule:
    - 0   if staleness <= threshold
    - 50  if staleness = threshold + 1
    - 75  if staleness = threshold + 2
    - 100 if staleness > threshold + 2

    Aggregate:
    - max penalty across Tier-1 series
    """
    registry = get_registry()
    penalties: Dict[str, Dict[str, Any]] = {}

    for cfg in registry.snapshot_series():
        sid = cfg["series_id"]
        row = aligned_payload.get(sid)

        if row is None:
            penalties[sid] = {
                "tier": cfg["tier"],
                "threshold": cfg["staleness_days"],
                "staleness_days": None,
                "penalty": 100 if cfg["tier"] == 1 else 75,
                "reason": "missing_aligned_value",
            }
            continue

        stale = int(row["staleness_days"])
        threshold = int(cfg["staleness_days"])

        if stale <= threshold:
            penalty = 0
        elif stale == threshold + 1:
            penalty = 50
        elif stale == threshold + 2:
            penalty = 75
        else:
            penalty = 100

        penalties[sid] = {
            "tier": cfg["tier"],
            "threshold": threshold,
            "staleness_days": stale,
            "penalty": penalty,
            "reason": "fresh" if penalty == 0 else "stale",
        }

    tier1_penalties = [
        meta["penalty"]
        for sid, meta in penalties.items()
        if meta["tier"] == 1
    ]
    overall = float(max(tier1_penalties) if tier1_penalties else 0)

    return overall, {
        "overall_rule": "max_tier1_penalty",
        "series": penalties,
    }


# ---------------------------------------------------------------------------
# Point-in-time history access
# ---------------------------------------------------------------------------

def _get_pt_series(
    conn: sqlite3.Connection,
    series_id: str,
    clock: EngineClock,
) -> List[Tuple[date, float]]:
    """
    Point-in-time daily history for one series as known by `clock.clock_ts`.

    For each obs_ts:
    - keep only rows with as_of_ts <= clock_ts
    - choose latest by as_of_ts DESC, revision_seq DESC
    """
    rows = conn.execute(
        """
        WITH ranked AS (
            SELECT
                obs_ts,
                value,
                as_of_ts,
                revision_seq,
                ROW_NUMBER() OVER (
                    PARTITION BY obs_ts
                    ORDER BY as_of_ts DESC, revision_seq DESC
                ) AS rn
            FROM observations
            WHERE series_id = ?
              AND obs_ts <= ?
              AND as_of_ts <= ?
        )
        SELECT obs_ts, value
        FROM ranked
        WHERE rn = 1
        ORDER BY obs_ts ASC
        """,
        (series_id, clock.clock_date.isoformat(), clock.clock_ts.isoformat()),
    ).fetchall()

    return [(_coerce_date(r["obs_ts"]), float(r["value"])) for r in rows]


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------

class InsufficientHistoryError(ValueError):
    pass


def _require_len(seq: Sequence[Any], n: int, label: str) -> None:
    if len(seq) < n:
        raise InsufficientHistoryError(f"{label}: need >= {n}, got {len(seq)}")


def _coerce_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _mean(xs: Sequence[float]) -> float:
    return statistics.fmean(xs)


def _stdev(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    return statistics.pstdev(xs)


def _stdev_last(xs: Sequence[float], window: int) -> float:
    _require_len(xs, window, "vol window")
    return _stdev(xs[-window:])


def _zscore_last(xs: Sequence[float], window: int) -> float:
    _require_len(xs, window, "zscore window")
    segment = list(xs[-window:])
    mu = _mean(segment)
    sigma = _stdev(segment)
    if sigma <= 1e-12:
        return 0.0
    return (segment[-1] - mu) / sigma


def _diff_lag(xs: Sequence[float], lag: int) -> List[float]:
    _require_len(xs, lag + 1, "diff-lag series")
    return [xs[i] - xs[i - lag] for i in range(lag, len(xs))]


def _log_returns(xs: Sequence[float]) -> List[float]:
    _require_len(xs, 2, "returns series")
    out: List[float] = []
    for i in range(1, len(xs)):
        prev = xs[i - 1]
        cur = xs[i]
        if prev <= 0 or cur <= 0:
            out.append(0.0)
        else:
            out.append(math.log(cur / prev))
    return out


def _rolling_vols(returns: Sequence[float], window: int) -> List[float]:
    _require_len(returns, window, "rolling vols")
    out = []
    for i in range(window, len(returns) + 1):
        out.append(_stdev(returns[i - window:i]))
    return out


def _drawdown_last_window(xs: Sequence[float], window: int) -> float:
    _require_len(xs, window + 1, "drawdown window")
    segment = list(xs[-(window + 1):])
    peak = max(segment[:-1])
    if peak <= 0:
        return 0.0
    return (segment[-1] - peak) / peak


def _align_two_series(
    lhs: List[Tuple[date, float]],
    rhs: List[Tuple[date, float]],
) -> Tuple[List[float], List[float]]:
    lhs_map = {d: v for d, v in lhs}
    rhs_map = {d: v for d, v in rhs}
    common = sorted(set(lhs_map) & set(rhs_map))
    if len(common) < 2:
        raise InsufficientHistoryError("aligned pair history: insufficient overlap")
    return [lhs_map[d] for d in common], [rhs_map[d] for d in common]


def _corr(xs: Sequence[float], ys: Sequence[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        raise InsufficientHistoryError("correlation: insufficient paired history")

    mx = _mean(xs)
    my = _mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    deny = math.sqrt(sum((y - my) ** 2 for y in ys))
    den = denx * deny
    if den <= 1e-12:
        return 0.0
    return num / den


def _rolling_beta_last(
    lhs_vals: Sequence[float],
    rhs_vals: Sequence[float],
    window: int,
) -> float:
    _require_len(lhs_vals, window + 1, "beta lhs")
    _require_len(rhs_vals, window + 1, "beta rhs")

    lhs_rets = _log_returns(lhs_vals)[-window:]
    rhs_rets = _log_returns(rhs_vals)[-window:]

    mr = _mean(rhs_rets)
    mg = _mean(lhs_rets)
    cov = sum((x - mg) * (y - mr) for x, y in zip(lhs_rets, rhs_rets)) / len(lhs_rets)
    var = sum((y - mr) ** 2 for y in rhs_rets) / len(rhs_rets)
    if var <= 1e-12:
        return 0.0
    return cov / var


def _corrbreak_pair_score(
    lhs: List[Tuple[date, float]],
    rhs: List[Tuple[date, float]],
    *,
    short_window: int,
    long_window: int,
) -> Tuple[float, Dict[str, Any]]:
    lhs_vals, rhs_vals = _align_two_series(lhs, rhs)
    lhs_rets = _log_returns(lhs_vals)
    rhs_rets = _log_returns(rhs_vals)

    _require_len(lhs_rets, long_window, "corr long lhs")
    _require_len(rhs_rets, long_window, "corr long rhs")

    corr_short = _corr(lhs_rets[-short_window:], rhs_rets[-short_window:])
    corr_long = _corr(lhs_rets[-long_window:], rhs_rets[-long_window:])
    corr_gap = abs(corr_short - corr_long)
    sign_flip = int((corr_short < 0) != (corr_long < 0))

    score = min(100.0, 70.0 * corr_gap + 30.0 * sign_flip)

    return score, {
        "corr_short": round(corr_short, 6),
        "corr_long": round(corr_long, 6),
        "corr_gap": round(corr_gap, 6),
        "sign_flip": sign_flip,
    }


def _combine_series_subtract(
    lhs: List[Tuple[date, float]],
    rhs: List[Tuple[date, float]],
) -> List[Tuple[date, float]]:
    lhs_map = {d: v for d, v in lhs}
    rhs_map = {d: v for d, v in rhs}
    common = sorted(set(lhs_map) & set(rhs_map))
    return [(d, lhs_map[d] - rhs_map[d]) for d in common]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compute governed M1 index suite.")
    p.add_argument("--clock-date", type=str, default=None, help="Override clock date YYYY-MM-DD.")
    p.add_argument("--db", type=str, default=DB_PATH, help=f"SQLite DB path (default: {DB_PATH}).")
    p.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    p.add_argument("--timezone", type=str, default=CLOCK_TIMEZONE, help=f"Clock timezone (default: {CLOCK_TIMEZONE}).")
    p.add_argument("--cut-hour", type=int, default=CLOCK_CUT_HOUR, help=f"Clock cut hour (default: {CLOCK_CUT_HOUR}).")
    p.add_argument("--cut-minute", type=int, default=CLOCK_CUT_MINUTE, help=f"Clock cut minute (default: {CLOCK_CUT_MINUTE}).")
    p.add_argument("--cut-second", type=int, default=CLOCK_CUT_SECOND, help=f"Clock cut second (default: {CLOCK_CUT_SECOND}).")
    p.add_argument("--exceptions-file", type=str, default=CLOCK_EXCEPTIONS_FILE or None, help="Optional calendar exceptions JSON file.")
    p.add_argument("--policy-version", type=str, default=CLOCK_POLICY_VERSION, help=f"Clock policy version (default: {CLOCK_POLICY_VERSION}).")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    policy = get_default_policy(
        timezone_name=args.timezone,
        cut_hour=args.cut_hour,
        cut_minute=args.cut_minute,
        cut_second=args.cut_second,
        exceptions_path=args.exceptions_file,
        policy_version=args.policy_version,
    )
    clock = get_engine_clock(args.clock_date, policy=policy)
    conn = get_connection(args.db)

    result = build_index_suite(conn, clock)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        log.info("=" * 72)
        log.info("INDEX SUITE")
        log.info("  clock_date: %s", result.clock_date)
        log.info("  clock_ts:   %s", result.clock_ts)
        log.info("  version:    %s", result.index_version)
        log.info("=" * 72)
        log.info("  stress_index:            %s", result.stress_index)
        log.info("  corrbreak_index:         %s", result.corrbreak_index)
        log.info("  drift_index:             %s", result.drift_index)
        log.info("  data_freshness_penalty:  %s", result.data_freshness_penalty)
        log.info("  degraded:                %s", result.degraded)
        if result.null_reasons:
            for reason in result.null_reasons:
                log.warning("  null/degraded reason: %s", reason)
        log.info("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())