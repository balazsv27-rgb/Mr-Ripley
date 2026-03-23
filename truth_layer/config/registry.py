"""
layer2/config/registry.py
--------------------------
Series registry loader and validator for the Gold-First Market State Engine.

Single source of truth for all series metadata. Every adapter, the quality
gate, and the snapshot publisher must read configuration from here — never
from hardcoded dicts or inline constants.

Usage (CLI):
    python -m layer2.config.registry --validate
    python -m layer2.config.registry --list
    python -m layer2.config.registry --list --tier 1
    python -m layer2.config.registry --show DGS10
    python -m layer2.config.registry --summary

Usage (code):
    from layer2.config.registry import get_registry

    reg = get_registry()
    for s in reg.tier1_series():
        print(s["series_id"], s["staleness_days"])
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REGISTRY_FILE = Path(__file__).parent / "series_registry.json"

_REQUIRED_FIELDS: Dict[str, type] = {
    "series_id":           str,
    "description":         str,
    "tier":                int,
    "frequency":           str,
    "staleness_days":      int,
    "blocks_snapshot":     bool,
    "group":               str,
    "source":              str,
    "full_history_start":  str,
    "discontinued":        bool,
    "is_estimate":         bool,
    "include_in_snapshot": bool,
}

_VALID_FREQUENCIES = {"D", "W", "M", "Q", "A"}
_VALID_TIERS = {1, 2}

# ---------------------------------------------------------------------------
# Registry class
# ---------------------------------------------------------------------------

class SeriesRegistry:
    """
    Loaded, validated view of series_registry.json.

    All view methods return plain dicts — the exact entries from the JSON
    file, so callers can access any field by key.
    """

    def __init__(self, path: Path = _REGISTRY_FILE) -> None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        self._version: str = raw.get("registry_version", "unknown")
        self._series: List[dict] = raw["series"]
        self._validate()

    # -----------------------------------------------------------------------
    # Validation
    # -----------------------------------------------------------------------

    def _validate(self) -> None:
        seen_ids: set = set()
        errors: List[str] = []

        for i, s in enumerate(self._series):
            sid = s.get("series_id", f"<entry {i}>")
            prefix = f"[{sid}]"

            # Duplicate check
            if sid in seen_ids:
                errors.append(f"{prefix} duplicate series_id")
            seen_ids.add(sid)

            # Required fields and types
            for field, expected_type in _REQUIRED_FIELDS.items():
                if field not in s:
                    errors.append(f"{prefix} missing required field '{field}'")
                    continue
                if not isinstance(s[field], expected_type):
                    errors.append(
                        f"{prefix} field '{field}' must be {expected_type.__name__}, "
                        f"got {type(s[field]).__name__}"
                    )

            # Valid tier
            if s.get("tier") not in _VALID_TIERS:
                errors.append(f"{prefix} tier must be one of {_VALID_TIERS}")

            # Valid frequency
            if s.get("frequency") not in _VALID_FREQUENCIES:
                errors.append(
                    f"{prefix} frequency must be one of {_VALID_FREQUENCIES}, "
                    f"got {s.get('frequency')!r}"
                )

            # Staleness >= 1
            if isinstance(s.get("staleness_days"), int) and s["staleness_days"] < 1:
                errors.append(f"{prefix} staleness_days must be >= 1")

            # Tier-1 must block
            if s.get("tier") == 1 and not s.get("blocks_snapshot", False):
                errors.append(f"{prefix} Tier-1 series must have blocks_snapshot=true")

            # Discontinued must not block
            if s.get("discontinued") and s.get("blocks_snapshot"):
                errors.append(
                    f"{prefix} discontinued series must have blocks_snapshot=false"
                )

            # Estimate must not be Tier-1
            if s.get("is_estimate") and s.get("tier") == 1:
                errors.append(
                    f"{prefix} is_estimate=true series cannot be assigned to Tier-1"
                )

            # Valid full_history_start date
            hist = s.get("full_history_start")
            if isinstance(hist, str):
                try:
                    date.fromisoformat(hist)
                except ValueError:
                    errors.append(
                        f"{prefix} full_history_start {hist!r} is not a valid ISO date"
                    )

        if errors:
            raise ValueError(
                f"Registry validation failed with {len(errors)} error(s):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

    # -----------------------------------------------------------------------
    # Metadata
    # -----------------------------------------------------------------------

    @property
    def version(self) -> str:
        return self._version

    # -----------------------------------------------------------------------
    # Full collection views
    # -----------------------------------------------------------------------

    def all_series(self) -> List[dict]:
        """All 23 series entries."""
        return list(self._series)

    def tier1_series(self) -> List[dict]:
        """All Tier-1 series (15 entries — block snapshot if stale)."""
        return [s for s in self._series if s["tier"] == 1]

    def tier1_required_ids(self) -> List[str]:
        """series_id list for all Tier-1 series. Used for completeness checks."""
        return [s["series_id"] for s in self.tier1_series()]

    def tier2_series(self) -> List[dict]:
        """All Tier-2 series (8 entries — warn only)."""
        return [s for s in self._series if s["tier"] == 2]

    def snapshot_series(self) -> List[dict]:
        """All series with include_in_snapshot=true (20 entries)."""
        return [s for s in self._series if s["include_in_snapshot"]]

    def snapshot_series_ids(self) -> List[str]:
        """series_id list for all snapshot-included series."""
        return [s["series_id"] for s in self.snapshot_series()]

    def fred_series(self) -> List[dict]:
        """All series fetched from FRED (used by fred_loader)."""
        return [s for s in self._series if s["source"] == "fred"]

    def active_series(self) -> List[dict]:
        """All non-discontinued series."""
        return [s for s in self._series if not s["discontinued"]]

    def discontinued_series(self) -> List[dict]:
        """All discontinued series."""
        return [s for s in self._series if s["discontinued"]]

    def estimate_series(self) -> List[dict]:
        """All series flagged as estimates (is_estimate=true)."""
        return [s for s in self._series if s["is_estimate"]]

    # -----------------------------------------------------------------------
    # Single-series lookups
    # -----------------------------------------------------------------------

    def get(self, series_id: str) -> Optional[dict]:
        """Return the registry entry for a series_id, or None."""
        for s in self._series:
            if s["series_id"] == series_id:
                return s
        return None

    def staleness_threshold(self, series_id: str) -> int:
        """Return staleness_days for a series. Raises KeyError if not found."""
        s = self.get(series_id)
        if s is None:
            raise KeyError(f"Unknown series_id: {series_id!r}")
        return s["staleness_days"]

    def blocks_snapshot(self, series_id: str) -> bool:
        """Return blocks_snapshot for a series. Raises KeyError if not found."""
        s = self.get(series_id)
        if s is None:
            raise KeyError(f"Unknown series_id: {series_id!r}")
        return s["blocks_snapshot"]

    def full_history_start(self, series_id: str) -> date:
        """Return full_history_start as a date object."""
        s = self.get(series_id)
        if s is None:
            raise KeyError(f"Unknown series_id: {series_id!r}")
        return date.fromisoformat(s["full_history_start"])

    # -----------------------------------------------------------------------
    # Grouped views
    # -----------------------------------------------------------------------

    def by_group(self) -> Dict[str, List[dict]]:
        """Return all series grouped by their 'group' field."""
        groups: Dict[str, List[dict]] = {}
        for s in self._series:
            groups.setdefault(s["group"], []).append(s)
        return groups

    def by_tier(self) -> Dict[int, List[dict]]:
        """Return all series grouped by tier."""
        result: Dict[int, List[dict]] = {}
        for s in self._series:
            result.setdefault(s["tier"], []).append(s)
        return result

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------

    def summary(self) -> dict:
        return {
            "registry_version":   self._version,
            "total_series":       len(self._series),
            "tier1_count":        len(self.tier1_series()),
            "tier2_count":        len(self.tier2_series()),
            "snapshot_count":     len(self.snapshot_series()),
            "discontinued_count": len(self.discontinued_series()),
            "estimate_count":     len(self.estimate_series()),
            "groups":             sorted(self.by_group().keys()),
        }


# ---------------------------------------------------------------------------
# Module-level singleton (cached after first load)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_registry(path: str = str(_REGISTRY_FILE)) -> SeriesRegistry:
    """
    Return the validated SeriesRegistry singleton.

    Cached after first call — subsequent calls return the same object.
    The cache is process-scoped; tests that need fresh registries should
    call get_registry.cache_clear() before each test.
    """
    return SeriesRegistry(Path(path))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_validate(reg: SeriesRegistry) -> None:
    s = reg.summary()
    print(
        f"Registry VALID  |  v{s['registry_version']}  |  {s['total_series']} series  "
        f"|  {s['tier1_count']} Tier-1  |  {s['tier2_count']} Tier-2  "
        f"|  {s['snapshot_count']} in snapshot  "
        f"|  {s['discontinued_count']} discontinued  "
        f"|  {s['estimate_count']} estimate"
    )


def _cli_list(reg: SeriesRegistry, tier: Optional[int]) -> None:
    series = reg.tier1_series() if tier == 1 else (
        reg.tier2_series() if tier == 2 else reg.all_series()
    )
    print(f"{'series_id':<30} {'tier':<5} {'freq':<5} {'stale':<6} "
          f"{'blocks':<7} {'discontinued':<13} {'group'}")
    print("-" * 90)
    for s in series:
        print(
            f"{s['series_id']:<30} "
            f"T{s['tier']:<4} "
            f"{s['frequency']:<5} "
            f"{s['staleness_days']:<6} "
            f"{'yes' if s['blocks_snapshot'] else 'no':<7} "
            f"{'yes' if s['discontinued'] else 'no':<13} "
            f"{s['group']}"
        )


def _cli_show(reg: SeriesRegistry, series_id: str) -> None:
    s = reg.get(series_id)
    if s is None:
        print(f"Series not found: {series_id!r}")
        sys.exit(1)
    for k, v in s.items():
        print(f"  {k:<25} {v}")


def _cli_summary(reg: SeriesRegistry) -> None:
    for k, v in reg.summary().items():
        print(f"  {k:<25} {v}")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Layer-2 series registry — validate and inspect."
    )
    p.add_argument("--validate", action="store_true", help="Validate registry and print summary.")
    p.add_argument("--list",     action="store_true", help="List all series.")
    p.add_argument("--tier",     type=int, default=None, help="Filter --list by tier (1 or 2).")
    p.add_argument("--show",     type=str, default=None, help="Show all fields for a series.")
    p.add_argument("--summary",  action="store_true", help="Print summary stats.")
    p.add_argument(
        "--registry-path", type=str, default=str(_REGISTRY_FILE),
        help=f"Path to series_registry.json (default: {_REGISTRY_FILE})."
    )
    args = p.parse_args()

    try:
        reg = SeriesRegistry(Path(args.registry_path))
    except (ValueError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.validate:
        _cli_validate(reg)
    elif args.list:
        _cli_list(reg, args.tier)
    elif args.show:
        _cli_show(reg, args.show)
    elif args.summary:
        _cli_summary(reg)
    else:
        _cli_validate(reg)

    return 0


if __name__ == "__main__":
    sys.exit(main())
