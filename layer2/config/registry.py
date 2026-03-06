"""
registry.py
-----------
Layer-2 Series Registry Loader & Validator for Mr. Ripley.

Single source of truth for all series metadata:
    - tier assignments
    - staleness thresholds
    - snapshot inclusion rules
    - blocking behavior
    - discontinuation flags
    - estimate flags

All three main modules MUST read from here (after tomorrow's refactor):
    quality_gate.py       -> reads SERIES_CHECKS from registry
    fred_loader.py        -> reads SERIES_CONFIG from registry
    snapshot_publisher.py -> reads SNAPSHOT_SERIES from registry

Usage (as module):
    from layer2.config.registry import SeriesRegistry
    reg = SeriesRegistry()
    tier1 = reg.tier1_required_ids()
    snapshot = reg.snapshot_series()

Usage (as validation CLI):
    python -m layer2.config.registry --validate
    python -m layer2.config.registry --list
    python -m layer2.config.registry --list --tier 1
    python -m layer2.config.registry --show DGS10
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default registry path — relative to repo root
DEFAULT_REGISTRY_PATH = Path(__file__).parent / "series_registry.json"

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Required fields and their expected types
# ---------------------------------------------------------------------------

REQUIRED_FIELDS: Dict[str, type] = {
    "series_id":          str,
    "description":        str,
    "tier":               int,
    "frequency":          str,
    "staleness_days":     int,
    "blocks_snapshot":    bool,
    "group":              str,
    "source":             str,
    "full_history_start": str,
    "discontinued":       bool,
    "is_estimate":        bool,
    "include_in_snapshot": bool,
}

VALID_TIERS = {1, 2}
VALID_FREQUENCIES = {"D", "W", "M", "Q", "A"}


# ---------------------------------------------------------------------------
# SeriesRegistry class
# ---------------------------------------------------------------------------

class SeriesRegistry:
    """
    Loads, validates, and provides views into series_registry.json.

    Raises ValueError on load if registry is invalid.
    All validation happens at construction time — fail fast, fail loud.
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path else DEFAULT_REGISTRY_PATH
        self._raw: dict = {}
        self._series: List[dict] = []
        self._by_id: Dict[str, dict] = {}
        self.registry_version: str = "unknown"
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            raise FileNotFoundError(
                f"Registry not found: {self._path}. "
                f"Expected at layer2/config/series_registry.json"
            )

        with open(self._path, encoding="utf-8") as f:
            try:
                self._raw = json.load(f)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Registry JSON is malformed: {exc}") from exc

        self.registry_version = self._raw.get("registry_version", "unknown")
        raw_series = self._raw.get("series", [])

        if not raw_series:
            raise ValueError("Registry contains no series entries.")

        errors = self._validate(raw_series)
        if errors:
            error_text = "\n".join(f"  - {e}" for e in errors)
            raise ValueError(
                f"Registry validation failed with {len(errors)} error(s):\n{error_text}"
            )

        self._series = raw_series
        self._by_id = {s["series_id"]: s for s in raw_series}

    def _validate(self, series: List[dict]) -> List[str]:
        """Validate all entries. Returns list of error strings (empty = valid)."""
        errors = []
        seen_ids = set()

        for i, entry in enumerate(series):
            sid = entry.get("series_id", f"<entry {i}>")

            # Duplicate check
            if sid in seen_ids:
                errors.append(f"{sid}: duplicate series_id")
            seen_ids.add(sid)

            # Required fields and types
            for field, expected_type in REQUIRED_FIELDS.items():
                if field not in entry:
                    errors.append(f"{sid}: missing required field '{field}'")
                elif not isinstance(entry[field], expected_type):
                    errors.append(
                        f"{sid}: field '{field}' must be {expected_type.__name__}, "
                        f"got {type(entry[field]).__name__}"
                    )

            # Tier range
            if "tier" in entry and entry["tier"] not in VALID_TIERS:
                errors.append(f"{sid}: tier must be one of {VALID_TIERS}, got {entry['tier']}")

            # Frequency range
            if "frequency" in entry and entry["frequency"] not in VALID_FREQUENCIES:
                errors.append(
                    f"{sid}: frequency must be one of {VALID_FREQUENCIES}, "
                    f"got {entry['frequency']}"
                )

            # Staleness must be positive
            if "staleness_days" in entry and entry["staleness_days"] < 1:
                errors.append(f"{sid}: staleness_days must be >= 1")

            # Tier-1 must block snapshot
            if entry.get("tier") == 1 and not entry.get("blocks_snapshot", True):
                errors.append(
                    f"{sid}: Tier-1 series must have blocks_snapshot=true"
                )

            # Discontinued series should not block snapshot
            if entry.get("discontinued") and entry.get("blocks_snapshot"):
                errors.append(
                    f"{sid}: discontinued series cannot have blocks_snapshot=true"
                )

            # Estimates should not be Tier-1
            if entry.get("is_estimate") and entry.get("tier") == 1:
                errors.append(
                    f"{sid}: is_estimate=true series cannot be Tier-1 "
                    f"(estimates must not block snapshot)"
                )

            # full_history_start must be valid date string
            if "full_history_start" in entry:
                try:
                    from datetime import date
                    date.fromisoformat(entry["full_history_start"])
                except ValueError:
                    errors.append(
                        f"{sid}: full_history_start '{entry['full_history_start']}' "
                        f"is not a valid YYYY-MM-DD date"
                    )

        return errors

    # ---------------------------------------------------------------------------
    # Public views
    # ---------------------------------------------------------------------------

    def all_series(self) -> List[dict]:
        """Return all series entries."""
        return list(self._series)

    def get(self, series_id: str) -> Optional[dict]:
        """Return a single series entry by ID, or None."""
        return self._by_id.get(series_id)

    def tier1_series(self) -> List[dict]:
        """Return all Tier-1 series (blocks_snapshot=True)."""
        return [s for s in self._series if s["tier"] == 1]

    def tier1_required_ids(self) -> List[str]:
        """Return series_ids of all Tier-1 series. Used by quality gate."""
        return [s["series_id"] for s in self.tier1_series()]

    def tier2_series(self) -> List[dict]:
        """Return all Tier-2 series."""
        return [s for s in self._series if s["tier"] == 2]

    def snapshot_series(self) -> List[dict]:
        """Return all series with include_in_snapshot=True."""
        return [s for s in self._series if s["include_in_snapshot"]]

    def snapshot_series_ids(self) -> List[str]:
        """Return series_ids of all snapshot-included series."""
        return [s["series_id"] for s in self.snapshot_series()]

    def fred_series(self) -> List[dict]:
        """Return all series sourced from FRED."""
        return [s for s in self._series if s["source"] == "fred"]

    def active_series(self) -> List[dict]:
        """Return all non-discontinued series."""
        return [s for s in self._series if not s["discontinued"]]

    def discontinued_series(self) -> List[dict]:
        """Return all discontinued series."""
        return [s for s in self._series if s["discontinued"]]

    def estimate_series(self) -> List[dict]:
        """Return all series flagged as estimates."""
        return [s for s in self._series if s["is_estimate"]]

    def by_group(self, group: str) -> List[dict]:
        """Return all series in a given group."""
        return [s for s in self._series if s["group"] == group]

    def by_tier(self, tier: int) -> List[dict]:
        """Return all series of a given tier."""
        return [s for s in self._series if s["tier"] == tier]

    def staleness_threshold(self, series_id: str) -> Optional[int]:
        """Return staleness_days for a series_id, or None if not found."""
        s = self._by_id.get(series_id)
        return s["staleness_days"] if s else None

    def blocks_snapshot(self, series_id: str) -> bool:
        """Return True if this series blocks snapshot when stale/missing."""
        s = self._by_id.get(series_id)
        return bool(s and s["blocks_snapshot"])

    @property
    def version(self) -> str:
        return self.registry_version

    @property
    def series_count(self) -> int:
        return len(self._series)

    # ---------------------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------------------

    def summary(self) -> dict:
        return {
            "registry_version": self.registry_version,
            "registry_path": str(self._path),
            "total_series": self.series_count,
            "tier1_count": len(self.tier1_series()),
            "tier2_count": len(self.tier2_series()),
            "snapshot_count": len(self.snapshot_series()),
            "fred_count": len(self.fred_series()),
            "discontinued_count": len(self.discontinued_series()),
            "estimate_count": len(self.estimate_series()),
            "active_count": len(self.active_series()),
        }


# ---------------------------------------------------------------------------
# Module-level convenience (singleton pattern)
# ---------------------------------------------------------------------------

_registry: Optional[SeriesRegistry] = None


def get_registry(path: Optional[Path] = None) -> SeriesRegistry:
    """
    Return the global registry singleton.
    Loads on first call, cached thereafter.
    Pass path= to override default location (useful for testing).
    """
    global _registry
    if _registry is None or path is not None:
        _registry = SeriesRegistry(path=path)
    return _registry


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] registry: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Mr. Ripley Layer-2 Series Registry — loader and validator."
    )
    p.add_argument(
        "--validate", action="store_true",
        help="Validate the registry and exit. Exit code 0 = valid, 1 = invalid."
    )
    p.add_argument(
        "--list", action="store_true",
        help="List all series in the registry."
    )
    p.add_argument(
        "--tier", type=int, default=None,
        help="Filter --list by tier (1 or 2)."
    )
    p.add_argument(
        "--show", type=str, default=None,
        help="Show full details for a specific series_id."
    )
    p.add_argument(
        "--summary", action="store_true",
        help="Print registry summary statistics."
    )
    p.add_argument(
        "--path", type=str, default=None,
        help="Override registry JSON path."
    )
    return p.parse_args()


def main() -> int:
    _setup_logging()
    args = parse_args()
    path = Path(args.path) if args.path else None

    # Load and validate (always validates on load)
    try:
        reg = SeriesRegistry(path=path)
        log.info("Registry loaded: v%s | %d series | path: %s",
                 reg.version, reg.series_count, reg._path)
    except (FileNotFoundError, ValueError) as exc:
        log.error("Registry INVALID: %s", exc)
        return 1

    # --validate: just load and report
    if args.validate:
        s = reg.summary()
        log.info("Registry VALID ✓")
        log.info("  version:      %s", s["registry_version"])
        log.info("  total:        %d series", s["total_series"])
        log.info("  tier-1:       %d (all block snapshot)", s["tier1_count"])
        log.info("  tier-2:       %d", s["tier2_count"])
        log.info("  in snapshot:  %d", s["snapshot_count"])
        log.info("  fred:         %d", s["fred_count"])
        log.info("  discontinued: %d", s["discontinued_count"])
        log.info("  estimates:    %d", s["estimate_count"])
        return 0

    # --summary
    if args.summary:
        import json as _json
        print(_json.dumps(reg.summary(), indent=2))
        return 0

    # --show
    if args.show:
        entry = reg.get(args.show)
        if not entry:
            log.error("Series not found: %s", args.show)
            return 1
        import json as _json
        print(_json.dumps(entry, indent=2))
        return 0

    # --list
    if args.list:
        series = reg.by_tier(args.tier) if args.tier else reg.all_series()
        log.info("=" * 72)
        log.info("Series Registry — %d entries%s",
                 len(series), f" (Tier-{args.tier} only)" if args.tier else "")
        log.info("=" * 72)
        for s in series:
            flags = []
            if s["discontinued"]:
                flags.append("DISCONTINUED")
            if s["is_estimate"]:
                flags.append("ESTIMATE")
            if not s["include_in_snapshot"]:
                flags.append("NO-SNAPSHOT")
            flag_str = " [" + ", ".join(flags) + "]" if flags else ""
            log.info(
                "  T%d %-10s %-30s stale=%-5s blocks=%s%s",
                s["tier"],
                s["frequency"],
                s["series_id"],
                f"{s['staleness_days']}d",
                str(s["blocks_snapshot"]),
                flag_str,
            )
        log.info("=" * 72)
        return 0

    # Default: validate + summary
    s = reg.summary()
    log.info("Registry VALID ✓  |  v%s  |  %d series  |  %d Tier-1  |  %d in snapshot",
             s["registry_version"], s["total_series"],
             s["tier1_count"], s["snapshot_count"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
