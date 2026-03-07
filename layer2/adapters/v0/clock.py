# layer2/clock.py
"""
Canonical engine clock for Layer-2.

Purpose
-------
Expose a single governed `clock_ts` per run/date so the entire Layer-2 pipeline
(quality gate, alignment, snapshot publication, replay) uses the same official
time boundary.

Design principles
-----------------
- Deterministic: same input date + same policy => same clock_ts
- Centralized: timezone / cut-time / calendar rules live here
- Replay-safe: supports explicit `--date`
- Extensible: supports optional calendar exceptions file for holidays, forced
  trading days, and future early-close logic

Current default behavior
------------------------
- Timezone-aware
- Daily cut time configurable (default: 22:00 UTC)
- Weekend-aware trading calendar
- Optional exception overrides via JSON file

Example
-------
    from layer2.clock import get_engine_clock

    result = get_engine_clock(run_date="2026-03-07")
    print(result.clock_ts.isoformat())
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set
from zoneinfo import ZoneInfo


DEFAULT_TIMEZONE = "UTC"
DEFAULT_CUT_HOUR = 22
DEFAULT_CUT_MINUTE = 0
DEFAULT_CUT_SECOND = 0


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CalendarExceptions:
    """
    Optional calendar overrides.

    All dates must be ISO strings: YYYY-MM-DD.

    holiday_dates:
        Dates treated as non-trading even if they are weekdays.

    forced_trading_dates:
        Dates treated as trading even if they would otherwise be excluded.

    early_close_dates:
        Reserved for future use. Maps date -> cut time, e.g.
        {"2026-11-27": "18:00:00"}

    notes:
        Free-form metadata; ignored by clock logic.
    """

    holiday_dates: Set[date] = field(default_factory=set)
    forced_trading_dates: Set[date] = field(default_factory=set)
    early_close_dates: Dict[date, time] = field(default_factory=dict)
    notes: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json_file(cls, path: Optional[Path]) -> "CalendarExceptions":
        if path is None:
            return cls()

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Calendar exceptions file not found: {path}")

        payload = json.loads(path.read_text(encoding="utf-8"))

        holiday_dates = {_parse_date(d) for d in payload.get("holiday_dates", [])}
        forced_trading_dates = {
            _parse_date(d) for d in payload.get("forced_trading_dates", [])
        }
        early_close_dates = {
            _parse_date(k): _parse_hms(v)
            for k, v in payload.get("early_close_dates", {}).items()
        }
        notes = payload.get("notes", {})

        return cls(
            holiday_dates=holiday_dates,
            forced_trading_dates=forced_trading_dates,
            early_close_dates=early_close_dates,
            notes=notes,
        )


@dataclass(frozen=True)
class ClockPolicy:
    """
    Governing policy for the engine clock.
    """

    timezone_name: str = DEFAULT_TIMEZONE
    cut_hour: int = DEFAULT_CUT_HOUR
    cut_minute: int = DEFAULT_CUT_MINUTE
    cut_second: int = DEFAULT_CUT_SECOND
    calendar_name: str = "WEEKDAY_US_MARKETS_PROXY"
    exceptions: CalendarExceptions = field(default_factory=CalendarExceptions)
    policy_version: str = "clock-v1"

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    def cut_time_for_date(self, d: date) -> time:
        """
        Return the governed cut time for a specific date.

        Future extension:
        - early closes
        - special sessions
        """
        if d in self.exceptions.early_close_dates:
            return self.exceptions.early_close_dates[d]

        return time(
            hour=self.cut_hour,
            minute=self.cut_minute,
            second=self.cut_second,
            tzinfo=self.tzinfo,
        )


@dataclass(frozen=True)
class EngineClock:
    """
    Canonical clock output for one run/date.
    """

    clock_date: date
    clock_ts: datetime
    timezone_name: str
    calendar_name: str
    policy_version: str
    is_trading_day: bool
    previous_trading_day: Optional[date]
    next_trading_day: Optional[date]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clock_date": self.clock_date.isoformat(),
            "clock_ts": self.clock_ts.isoformat(),
            "timezone_name": self.timezone_name,
            "calendar_name": self.calendar_name,
            "policy_version": self.policy_version,
            "is_trading_day": self.is_trading_day,
            "previous_trading_day": (
                self.previous_trading_day.isoformat()
                if self.previous_trading_day is not None
                else None
            ),
            "next_trading_day": (
                self.next_trading_day.isoformat()
                if self.next_trading_day is not None
                else None
            ),
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_default_policy(
    *,
    timezone_name: str = DEFAULT_TIMEZONE,
    cut_hour: int = DEFAULT_CUT_HOUR,
    cut_minute: int = DEFAULT_CUT_MINUTE,
    cut_second: int = DEFAULT_CUT_SECOND,
    exceptions_path: Optional[str | Path] = None,
    policy_version: str = "clock-v1",
) -> ClockPolicy:
    """
    Build the default governed clock policy.

    This is the single place to standardize the Layer-2 cut-time policy.
    """
    _validate_cut_time(cut_hour, cut_minute, cut_second)

    exceptions = CalendarExceptions.from_json_file(
        Path(exceptions_path) if exceptions_path else None
    )

    return ClockPolicy(
        timezone_name=timezone_name,
        cut_hour=cut_hour,
        cut_minute=cut_minute,
        cut_second=cut_second,
        calendar_name="WEEKDAY_US_MARKETS_PROXY",
        exceptions=exceptions,
        policy_version=policy_version,
    )


def get_engine_clock(
    run_date: Optional[str | date | datetime] = None,
    *,
    policy: Optional[ClockPolicy] = None,
) -> EngineClock:
    """
    Return the canonical engine clock for a given run date.

    Parameters
    ----------
    run_date:
        - None: use today's date in policy timezone
        - YYYY-MM-DD string
        - date
        - datetime

    policy:
        ClockPolicy. If omitted, default policy is used.

    Returns
    -------
    EngineClock
        Canonical clock object with governed `clock_ts`.
    """
    policy = policy or get_default_policy()
    resolved_date = resolve_run_date(run_date, policy=policy)

    cut_dt = datetime.combine(
        resolved_date,
        policy.cut_time_for_date(resolved_date).replace(tzinfo=None),
        tzinfo=policy.tzinfo,
    )

    return EngineClock(
        clock_date=resolved_date,
        clock_ts=cut_dt,
        timezone_name=policy.timezone_name,
        calendar_name=policy.calendar_name,
        policy_version=policy.policy_version,
        is_trading_day=is_trading_day(resolved_date, policy=policy),
        previous_trading_day=get_previous_trading_day(resolved_date, policy=policy),
        next_trading_day=get_next_trading_day(resolved_date, policy=policy),
    )


def resolve_run_date(
    run_date: Optional[str | date | datetime],
    *,
    policy: ClockPolicy,
) -> date:
    """
    Resolve a run-date input into a calendar date in the governed timezone.
    """
    if run_date is None:
        return datetime.now(policy.tzinfo).date()

    if isinstance(run_date, date) and not isinstance(run_date, datetime):
        return run_date

    if isinstance(run_date, datetime):
        if run_date.tzinfo is None:
            # Treat naive datetimes as already expressed in policy timezone.
            return run_date.replace(tzinfo=policy.tzinfo).date()
        return run_date.astimezone(policy.tzinfo).date()

    if isinstance(run_date, str):
        return _parse_date(run_date)

    raise TypeError(
        f"Unsupported run_date type: {type(run_date).__name__}. "
        "Expected None, str, date, or datetime."
    )


def is_trading_day(d: date, *, policy: ClockPolicy) -> bool:
    """
    Decide whether a date is considered a trading day under the current policy.

    Current behavior:
    - Mon-Fri are trading days
    - Sat/Sun are not
    - explicit holiday overrides can exclude weekdays
    - explicit forced-trading overrides can include excluded dates
    """
    if d in policy.exceptions.forced_trading_dates:
        return True

    if d in policy.exceptions.holiday_dates:
        return False

    return d.weekday() < 5  # 0=Mon ... 4=Fri


def get_previous_trading_day(
    d: date,
    *,
    policy: ClockPolicy,
    max_lookback_days: int = 14,
) -> Optional[date]:
    """
    Return the most recent trading day strictly before `d`.
    """
    current = d - timedelta(days=1)
    for _ in range(max_lookback_days):
        if is_trading_day(current, policy=policy):
            return current
        current -= timedelta(days=1)
    return None


def get_next_trading_day(
    d: date,
    *,
    policy: ClockPolicy,
    max_lookahead_days: int = 14,
) -> Optional[date]:
    """
    Return the next trading day strictly after `d`.
    """
    current = d + timedelta(days=1)
    for _ in range(max_lookahead_days):
        if is_trading_day(current, policy=policy):
            return current
        current += timedelta(days=1)
    return None


def get_latest_completed_clock(
    *,
    now: Optional[datetime] = None,
    policy: Optional[ClockPolicy] = None,
) -> EngineClock:
    """
    Return the most recent completed engine clock relative to `now`.

    Useful for daily schedulers that may run before or after the cut time.

    Example:
    - policy cut = 22:00 UTC
    - now = 2026-03-07 21:00 UTC -> returns clock for 2026-03-06
    - now = 2026-03-07 22:15 UTC -> returns clock for 2026-03-07
    """
    policy = policy or get_default_policy()
    now = now or datetime.now(policy.tzinfo)

    if now.tzinfo is None:
        now = now.replace(tzinfo=policy.tzinfo)
    else:
        now = now.astimezone(policy.tzinfo)

    today_clock = get_engine_clock(now.date(), policy=policy)

    if now >= today_clock.clock_ts:
        return today_clock

    yesterday = now.date() - timedelta(days=1)
    return get_engine_clock(yesterday, policy=policy)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_cut_time(hour: int, minute: int, second: int) -> None:
    if not (0 <= hour <= 23):
        raise ValueError(f"cut_hour must be in [0, 23], got {hour}")
    if not (0 <= minute <= 59):
        raise ValueError(f"cut_minute must be in [0, 59], got {minute}")
    if not (0 <= second <= 59):
        raise ValueError(f"cut_second must be in [0, 59], got {second}")


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid date '{value}'. Expected ISO format YYYY-MM-DD."
        ) from exc


def _parse_hms(value: str) -> time:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid time '{value}'. Expected ISO format HH:MM[:SS]."
        ) from exc

    if parsed.tzinfo is not None:
        # Keep all timezone handling in policy.tzinfo for determinism.
        return parsed.replace(tzinfo=None)

    return parsed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Canonical Layer-2 engine clock"
    )
    parser.add_argument(
        "--date",
        help="Clock date in YYYY-MM-DD. If omitted, uses today's date in policy timezone.",
    )
    parser.add_argument(
        "--latest-completed",
        action="store_true",
        help="Return the most recent completed clock relative to now.",
    )
    parser.add_argument(
        "--timezone",
        default=DEFAULT_TIMEZONE,
        help=f"IANA timezone name. Default: {DEFAULT_TIMEZONE}",
    )
    parser.add_argument(
        "--cut-hour",
        type=int,
        default=DEFAULT_CUT_HOUR,
        help=f"Governed cut hour. Default: {DEFAULT_CUT_HOUR}",
    )
    parser.add_argument(
        "--cut-minute",
        type=int,
        default=DEFAULT_CUT_MINUTE,
        help=f"Governed cut minute. Default: {DEFAULT_CUT_MINUTE}",
    )
    parser.add_argument(
        "--cut-second",
        type=int,
        default=DEFAULT_CUT_SECOND,
        help=f"Governed cut second. Default: {DEFAULT_CUT_SECOND}",
    )
    parser.add_argument(
        "--exceptions-file",
        help=(
            "Optional JSON file with holiday_dates, forced_trading_dates, "
            "and early_close_dates."
        ),
    )
    parser.add_argument(
        "--policy-version",
        default="clock-v1",
        help="Clock policy version tag. Default: clock-v1",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    policy = get_default_policy(
        timezone_name=args.timezone,
        cut_hour=args.cut_hour,
        cut_minute=args.cut_minute,
        cut_second=args.cut_second,
        exceptions_path=args.exceptions_file,
        policy_version=args.policy_version,
    )

    if args.latest_completed:
        result = get_latest_completed_clock(policy=policy)
    else:
        result = get_engine_clock(args.date, policy=policy)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"clock_date          : {result.clock_date.isoformat()}")
        print(f"clock_ts            : {result.clock_ts.isoformat()}")
        print(f"timezone_name       : {result.timezone_name}")
        print(f"calendar_name       : {result.calendar_name}")
        print(f"policy_version      : {result.policy_version}")
        print(f"is_trading_day      : {result.is_trading_day}")
        print(
            "previous_trading_day: "
            f"{result.previous_trading_day.isoformat() if result.previous_trading_day else 'None'}"
        )
        print(
            "next_trading_day    : "
            f"{result.next_trading_day.isoformat() if result.next_trading_day else 'None'}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())