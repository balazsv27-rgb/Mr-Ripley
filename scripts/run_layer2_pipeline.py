"""
scripts/run_layer2_pipeline.py
------------------------------

Minimal Layer-2 operational orchestrator for Mr. Ripley.

Runs the complete Layer-2 pipeline:

    1. adapters/backfill
    2. quality gate
    3. snapshot publisher

Design goals:
    - deterministic execution wrapper
    - fail-closed on Tier-1 / quality failures
    - retry support
    - kill switch
    - dry-run support
    - auditable file logging

Usage:

    # Daily production run
    python scripts/run_layer2_pipeline.py

    # Dry-run
    python scripts/run_layer2_pipeline.py --dry-run

    # Force snapshot publish if publisher supports --force
    python scripts/run_layer2_pipeline.py --force

    # Run adapters only
    python scripts/run_layer2_pipeline.py --adapters-only

    # Skip adapters and only validate/publish current DB state
    python scripts/run_layer2_pipeline.py --skip-adapters

    # Kill switch
    set L2_KILL_SWITCH=1
    python scripts/run_layer2_pipeline.py

Environment:
    L2_DB_PATH          SQLite DB path, default: layer2_truth.db
    L2_ENGINE_VERSION   Required by snapshot_publisher.py
    L2_LOG_LEVEL        DEBUG | INFO | WARNING | ERROR
    L2_KILL_SWITCH      If "1", abort immediately
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = REPO_ROOT / "runtime"
LOG_DIR = RUNTIME_DIR / "logs"

DEFAULT_DB_PATH = os.getenv("L2_DB_PATH", "layer2_truth.db")
LOG_LEVEL = os.getenv("L2_LOG_LEVEL", "INFO").upper()

KILL_SWITCH_ENV = "L2_KILL_SWITCH"
ENGINE_VERSION_ENV = "L2_ENGINE_VERSION"


@dataclass
class StageResult:
    name: str
    command: List[str]
    exit_code: int
    attempts: int
    elapsed_seconds: float


@dataclass
class PipelineContext:
    run_id: str
    run_ts: str
    db_path: str
    dry_run: bool
    force: bool
    python: str
    max_retries: int
    results: Dict[str, StageResult] = field(default_factory=dict)


def configure_logging(run_id: str) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"layer2_pipeline_{run_id}.log"

    handlers: List[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_path, encoding="utf-8"),
    ]

    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s [%(levelname)s] layer2_pipeline: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        handlers=handlers,
        force=True,
    )

    return log_path


log = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def check_kill_switch() -> None:
    if os.getenv(KILL_SWITCH_ENV) == "1":
        raise SystemExit("Layer-2 pipeline aborted: L2_KILL_SWITCH=1")


def require_engine_version(skip_publish: bool, adapters_only: bool) -> None:
    if skip_publish or adapters_only:
        return
    if not os.getenv(ENGINE_VERSION_ENV):
        raise SystemExit(
            "L2_ENGINE_VERSION is not set. "
            'PowerShell: $env:L2_ENGINE_VERSION="gold-v3.3.0"'
        )


def run_command(
    *,
    name: str,
    command: List[str],
    ctx: PipelineContext,
    retryable: bool = True,
) -> StageResult:
    attempts_allowed = ctx.max_retries + 1 if retryable else 1
    last_rc = 1
    t_stage = time.monotonic()

    for attempt in range(1, attempts_allowed + 1):
        check_kill_switch()

        log.info("=" * 72)
        log.info("Stage %s | attempt %d/%d", name, attempt, attempts_allowed)
        log.info("CMD: %s", " ".join(command))
        log.info("=" * 72)

        t0 = time.monotonic()
        proc = subprocess.run(command, cwd=str(REPO_ROOT), check=False)
        elapsed = time.monotonic() - t0
        last_rc = int(proc.returncode)

        if last_rc == 0:
            total_elapsed = time.monotonic() - t_stage
            result = StageResult(
                name=name,
                command=command,
                exit_code=0,
                attempts=attempt,
                elapsed_seconds=total_elapsed,
            )
            ctx.results[name] = result
            log.info("Stage %s PASS | elapsed=%.1fs", name, elapsed)
            return result

        log.error(
            "Stage %s FAIL | exit_code=%d | elapsed=%.1fs",
            name,
            last_rc,
            elapsed,
        )

        if attempt < attempts_allowed:
            sleep_s = min(30, 2**attempt)
            log.warning("Retrying stage %s after %.1fs", name, sleep_s)
            time.sleep(sleep_s)

    total_elapsed = time.monotonic() - t_stage
    result = StageResult(
        name=name,
        command=command,
        exit_code=last_rc,
        attempts=attempts_allowed,
        elapsed_seconds=total_elapsed,
    )
    ctx.results[name] = result
    raise RuntimeError(f"Stage {name!r} failed after {attempts_allowed} attempt(s)")


def build_backfill_cmd(ctx: PipelineContext, args: argparse.Namespace) -> List[str]:
    cmd = [ctx.python, "layer2/run_backfill.py", "--db", ctx.db_path]

    if args.full_history:
        cmd.append("--full-history")

    if args.gold_json:
        cmd += ["--gold-json", args.gold_json]

    if args.start_date:
        cmd += ["--start-date", args.start_date]

    if args.end_date:
        cmd += ["--end-date", args.end_date]

    if args.only:
        cmd += ["--only", *args.only]

    if args.skip:
        cmd += ["--skip", *args.skip]

    if ctx.dry_run:
        cmd.append("--dry-run")

    return cmd


def build_quality_gate_cmd(ctx: PipelineContext) -> List[str]:
    return [ctx.python, "layer2/adapters/quality_gate.py"]


def build_snapshot_cmd(ctx: PipelineContext) -> List[str]:
    cmd = [ctx.python, "layer2/adapters/snapshot_publisher.py"]

    if ctx.dry_run:
        cmd.append("--dry-run")

    if ctx.force:
        cmd.append("--force")

    return cmd


def print_summary(ctx: PipelineContext, log_path: Path, ok: bool) -> int:
    log.info("")
    log.info("=" * 72)
    log.info("LAYER-2 PIPELINE SUMMARY")
    log.info("=" * 72)
    log.info("run_id:      %s", ctx.run_id)
    log.info("run_ts:      %s", ctx.run_ts)
    log.info("db_path:     %s", ctx.db_path)
    log.info("dry_run:     %s", ctx.dry_run)
    log.info("force:       %s", ctx.force)
    log.info("log_path:    %s", log_path)

    for name, result in ctx.results.items():
        status = "PASS" if result.exit_code == 0 else f"FAIL({result.exit_code})"
        log.info(
            "stage=%-14s status=%-8s attempts=%d elapsed=%.1fs",
            name,
            status,
            result.attempts,
            result.elapsed_seconds,
        )

    log.info("verdict:     %s", "PASS" if ok else "FAIL")
    log.info("=" * 72)

    return 0 if ok else 1


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run the complete Mr. Ripley Layer-2 pipeline."
    )

    p.add_argument("--db", default=DEFAULT_DB_PATH)
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--max-retries", type=int, default=2)

    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")

    p.add_argument("--skip-adapters", action="store_true")
    p.add_argument("--adapters-only", action="store_true")
    p.add_argument("--quality-only", action="store_true")
    p.add_argument("--skip-publish", action="store_true")

    p.add_argument("--full-history", action="store_true")
    p.add_argument("--gold-json", default=None)
    p.add_argument("--start-date", default=None)
    p.add_argument("--end-date", default=None)

    p.add_argument("--only", nargs="+", default=None)
    p.add_argument("--skip", nargs="+", default=None)

    return p.parse_args()


def main() -> int:
    args = parse_args()

    run_id = make_run_id()
    run_ts = utc_now_iso()
    log_path = configure_logging(run_id)

    ctx = PipelineContext(
        run_id=run_id,
        run_ts=run_ts,
        db_path=args.db,
        dry_run=args.dry_run,
        force=args.force,
        python=args.python,
        max_retries=max(0, args.max_retries),
    )

    try:
        check_kill_switch()
        require_engine_version(
            skip_publish=args.skip_publish,
            adapters_only=args.adapters_only or args.quality_only,
        )

        log.info("Mr. Ripley Layer-2 pipeline starting")
        log.info("run_id=%s | dry_run=%s | db=%s", ctx.run_id, ctx.dry_run, ctx.db_path)

        if args.quality_only:
            run_command(
                name="quality_gate",
                command=build_quality_gate_cmd(ctx),
                ctx=ctx,
                retryable=False,
            )
            return print_summary(ctx, log_path, ok=True)

        if not args.skip_adapters:
            run_command(
                name="adapters",
                command=build_backfill_cmd(ctx, args),
                ctx=ctx,
                retryable=True,
            )

        if args.adapters_only:
            return print_summary(ctx, log_path, ok=True)

        run_command(
            name="quality_gate",
            command=build_quality_gate_cmd(ctx),
            ctx=ctx,
            retryable=False,
        )

        if not args.skip_publish:
            run_command(
                name="snapshot_publish",
                command=build_snapshot_cmd(ctx),
                ctx=ctx,
                retryable=False,
            )

        return print_summary(ctx, log_path, ok=True)

    except SystemExit as exc:
        log.error("%s", exc)
        return print_summary(ctx, log_path, ok=False)

    except Exception as exc:
        log.exception("Layer-2 pipeline failed: %s", exc)
        return print_summary(ctx, log_path, ok=False)


if __name__ == "__main__":
    sys.exit(main())