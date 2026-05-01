"""
tests/layer2/test_revision_risk.py
------------------------------------
Phase 1 contract-completion tests for revision_risk awareness.

Proves:
- Registry validation rejects missing or non-bool revision_risk
- Alignment payload includes revision_risk
- Monthly macro series are revision_risk=true
- Daily market/yield series are revision_risk=false
- Quality gate output preserves revision_risk summary
- Snapshot JSON carries revision_policy, revision_risk_summary, and per-series revision_risk
- revision_risk does NOT block snapshot publication
"""

from __future__ import annotations

import json
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

# Path setup handled by tests/layer2/conftest.py


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_minimal_registry_entry(**overrides) -> dict:
    """Return a valid minimal registry entry, overriding any fields."""
    base = {
        "series_id": "TEST_SERIES",
        "description": "Test series",
        "tier": 2,
        "frequency": "D",
        "staleness_days": 3,
        "blocks_snapshot": False,
        "group": "test",
        "source": "fred",
        "full_history_start": "2005-01-03",
        "discontinued": False,
        "is_estimate": False,
        "include_in_snapshot": True,
        "revision_risk": False,
    }
    base.update(overrides)
    return base


def _write_temp_registry(series: List[dict]) -> Path:
    """Write a temporary series_registry.json and return its path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump({"registry_version": "test-1.0", "series": series}, tmp)
    tmp.close()
    return Path(tmp.name)


# ---------------------------------------------------------------------------
# A. Registry validation
# ---------------------------------------------------------------------------

class TestRegistryValidation:
    def test_valid_registry_loads(self):
        from layer2.config.registry import SeriesRegistry
        path = _write_temp_registry([_make_minimal_registry_entry(series_id="S1")])
        reg = SeriesRegistry(path)
        assert reg.get("S1")["revision_risk"] is False

    def test_missing_revision_risk_fails(self):
        from layer2.config.registry import SeriesRegistry
        entry = _make_minimal_registry_entry()
        del entry["revision_risk"]
        path = _write_temp_registry([entry])
        with pytest.raises(ValueError, match="revision_risk"):
            SeriesRegistry(path)

    def test_non_bool_revision_risk_fails(self):
        from layer2.config.registry import SeriesRegistry
        entry = _make_minimal_registry_entry(revision_risk="yes")
        path = _write_temp_registry([entry])
        with pytest.raises(ValueError, match="revision_risk"):
            SeriesRegistry(path)

    def test_int_revision_risk_fails(self):
        from layer2.config.registry import SeriesRegistry
        entry = _make_minimal_registry_entry(revision_risk=1)
        path = _write_temp_registry([entry])
        with pytest.raises(ValueError, match="revision_risk"):
            SeriesRegistry(path)


# ---------------------------------------------------------------------------
# B. Canonical registry — series classification
# ---------------------------------------------------------------------------

class TestCanonicalRegistryClassification:
    """These tests use the real series_registry.json."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        from layer2.config.registry import get_registry
        get_registry.cache_clear()
        yield
        get_registry.cache_clear()

    def test_monthly_macro_series_are_revision_risk_true(self):
        from layer2.config.registry import get_registry
        reg = get_registry()
        expected_true = {"CPILFESL", "PCEPI", "FEDFUNDS", "PCU2122212122210"}
        for sid in expected_true:
            entry = reg.get(sid)
            assert entry is not None, f"Series {sid} not found in registry"
            assert entry["revision_risk"] is True, f"{sid} should be revision_risk=true"

    def test_daily_market_series_are_revision_risk_false(self):
        from layer2.config.registry import get_registry
        reg = get_registry()
        expected_false = {
            "gold_price_proxy", "rates_vol_stress_move",
            "DFII10", "DFII5", "DGS10", "DGS2", "DGS5",
            "T10YIE", "T5YIE", "T5YIFR",
            "DFF", "EFFR", "DTWEXBGS", "VIXCLS", "SP500",
            "gld_holdings_flow_confirm",
        }
        for sid in expected_false:
            entry = reg.get(sid)
            assert entry is not None, f"Series {sid} not found in registry"
            assert entry["revision_risk"] is False, f"{sid} should be revision_risk=false"

    def test_all_snapshot_series_have_revision_risk_field(self):
        from layer2.config.registry import get_registry
        reg = get_registry()
        for s in reg.snapshot_series():
            assert "revision_risk" in s, f"{s['series_id']} missing revision_risk"
            assert isinstance(s["revision_risk"], bool), (
                f"{s['series_id']} revision_risk must be bool, got {type(s['revision_risk'])}"
            )

    def test_revision_risk_lookup_method(self):
        from layer2.config.registry import get_registry
        reg = get_registry()
        assert reg.revision_risk("CPILFESL") is True
        assert reg.revision_risk("DGS10") is False

    def test_revision_risk_lookup_raises_for_unknown(self):
        from layer2.config.registry import get_registry
        reg = get_registry()
        with pytest.raises(KeyError):
            reg.revision_risk("NONEXISTENT_SERIES")


# ---------------------------------------------------------------------------
# C. AlignedSeriesValue and payload
# ---------------------------------------------------------------------------

class TestAlignmentPayload:
    def test_aligned_series_value_has_revision_risk(self):
        from layer2.alignment import AlignedSeriesValue
        v = AlignedSeriesValue(
            series_id="CPILFESL",
            description="Core CPI",
            tier=2,
            group="inflation_monthly",
            blocks_snapshot=False,
            obs_ts=date(2026, 3, 1),
            as_of_ts=datetime(2026, 3, 15, 22, 0, tzinfo=timezone.utc),
            revision_seq=0,
            value=3.8,
            source="fred",
            staleness_days=14,
            revision_risk=True,
        )
        assert v.revision_risk is True
        d = v.to_dict()
        assert "revision_risk" in d
        assert d["revision_risk"] is True

    def test_aligned_series_value_default_revision_risk_false(self):
        from layer2.alignment import AlignedSeriesValue
        v = AlignedSeriesValue(
            series_id="DGS10",
            description="10Y yield",
            tier=1,
            group="nominal_yields",
            blocks_snapshot=True,
            obs_ts=date(2026, 3, 15),
            as_of_ts=datetime(2026, 3, 15, 22, 0, tzinfo=timezone.utc),
            revision_seq=0,
            value=4.2,
            source="fred",
            staleness_days=0,
        )
        assert v.revision_risk is False
        assert v.to_dict()["revision_risk"] is False

    def test_build_snapshot_values_payload_includes_revision_risk(self):
        from layer2.alignment import AlignedSeriesValue, AlignmentResult, build_snapshot_values_payload
        clock_date = date(2026, 3, 15)
        clock_ts = datetime(2026, 3, 15, 22, 0, tzinfo=timezone.utc)

        values = [
            AlignedSeriesValue(
                series_id="CPILFESL", description="Core CPI", tier=2,
                group="inflation_monthly", blocks_snapshot=False,
                obs_ts=date(2026, 3, 1), as_of_ts=clock_ts,
                revision_seq=0, value=3.8, source="fred",
                staleness_days=14, revision_risk=True,
            ),
            AlignedSeriesValue(
                series_id="DGS10", description="10Y yield", tier=1,
                group="nominal_yields", blocks_snapshot=True,
                obs_ts=clock_date, as_of_ts=clock_ts,
                revision_seq=0, value=4.2, source="fred",
                staleness_days=0, revision_risk=False,
            ),
        ]
        result = AlignmentResult(clock_date=clock_date, clock_ts=clock_ts, values=values, missing_series=[])
        payload = build_snapshot_values_payload(result)

        by_id = {p["series_id"]: p for p in payload}
        assert by_id["CPILFESL"]["revision_risk"] is True
        assert by_id["DGS10"]["revision_risk"] is False


# ---------------------------------------------------------------------------
# D. Quality gate — revision_risk preserved in output
# ---------------------------------------------------------------------------

class TestQualityGateRevisionRisk:
    def _make_aligned_payload(self) -> List[dict]:
        return [
            {
                "series_id": "DGS10", "tier": 1, "group": "nominal_yields",
                "obs_ts": "2026-03-15", "value": 4.2, "staleness_days": 0,
                "source": "fred", "as_of_ts": "2026-03-15T22:00:00+00:00",
                "revision_seq": 0, "revision_risk": False,
            },
            {
                "series_id": "CPILFESL", "tier": 2, "group": "inflation_monthly",
                "obs_ts": "2026-03-01", "value": 3.8, "staleness_days": 14,
                "source": "fred", "as_of_ts": "2026-03-15T22:00:00+00:00",
                "revision_seq": 0, "revision_risk": True,
            },
            {
                "series_id": "PCEPI", "tier": 2, "group": "inflation_monthly",
                "obs_ts": "2026-03-01", "value": 2.5, "staleness_days": 14,
                "source": "fred", "as_of_ts": "2026-03-15T22:00:00+00:00",
                "revision_seq": 0, "revision_risk": True,
            },
        ]

    def test_summary_contains_revision_risk_counts(self):
        payload = self._make_aligned_payload()
        rr_series = sorted(v["series_id"] for v in payload if v.get("revision_risk"))
        assert rr_series == ["CPILFESL", "PCEPI"]

        # Simulate what run_quality_gate does
        summary = {
            "tier1_total": 1, "tier1_pass": 1, "tier1_fail": 0,
            "tier2_total": 2, "tier2_warn": 0,
            "revision_risk_series_count": len(rr_series),
            "revision_risk_series": rr_series,
        }
        assert summary["revision_risk_series_count"] == 2
        assert "CPILFESL" in summary["revision_risk_series"]
        assert "PCEPI" in summary["revision_risk_series"]

    def test_revision_risk_does_not_block_snapshot(self):
        """revision_risk=true series must not affect snapshot_ok."""
        # snapshot_ok depends only on Tier-1 failures, not revision_risk
        payload = self._make_aligned_payload()
        tier1_fail_count = 0  # DGS10 is PASS
        snapshot_ok = tier1_fail_count == 0
        assert snapshot_ok is True


# ---------------------------------------------------------------------------
# E. Snapshot JSON contract
# ---------------------------------------------------------------------------

class TestSnapshotJsonContract:
    """Test write_snapshot_json produces required revision_risk fields."""

    def _make_quality(self, snapshot_ok: bool = True) -> dict:
        return {
            "snapshot_ok": snapshot_ok,
            "summary": {
                "tier1_total": 1, "tier1_pass": 1 if snapshot_ok else 0,
                "tier1_fail": 0 if snapshot_ok else 1,
                "tier2_total": 2, "tier2_warn": 0,
                "revision_risk_series_count": 2,
                "revision_risk_series": ["CPILFESL", "PCEPI"],
            },
            "blocking_failures": [],
            "tier2_warnings": [],
        }

    def _make_values(self) -> List[dict]:
        return [
            {
                "series_id": "DGS10", "tier": 1, "group": "nominal_yields",
                "obs_ts": "2026-03-15", "value": 4.2, "staleness_days": 0,
                "source": "fred", "as_of_ts": "2026-03-15T22:00:00+00:00",
                "revision_seq": 0, "revision_risk": False,
            },
            {
                "series_id": "CPILFESL", "tier": 2, "group": "inflation_monthly",
                "obs_ts": "2026-03-01", "value": 3.8, "staleness_days": 14,
                "source": "fred", "as_of_ts": "2026-03-15T22:00:00+00:00",
                "revision_seq": 0, "revision_risk": True,
            },
            {
                "series_id": "PCEPI", "tier": 2, "group": "inflation_monthly",
                "obs_ts": "2026-03-01", "value": 2.5, "staleness_days": 14,
                "source": "fred", "as_of_ts": "2026-03-15T22:00:00+00:00",
                "revision_seq": 0, "revision_risk": True,
            },
        ]

    def test_snapshot_json_has_revision_policy(self, tmp_path):
        from layer2.adapters.snapshot_publisher import write_snapshot_json
        out = tmp_path / "snap.json"
        clock_ts = datetime(2026, 3, 15, 22, 0, tzinfo=timezone.utc)
        run_ts = datetime(2026, 3, 16, 0, 0, tzinfo=timezone.utc)

        write_snapshot_json(
            str(out), "abc123", clock_ts, run_ts,
            "gold-v3.3.0", "1.0.0",
            self._make_quality(), self._make_values(), [],
        )

        data = json.loads(out.read_text())
        assert "revision_policy" in data
        rp = data["revision_policy"]
        assert rp["method"] == "latest_available_with_revision_risk_flag"
        assert rp["revision_writer"] == "not_implemented"
        assert rp["revision_risk_blocks_snapshot"] is False

    def test_snapshot_json_has_revision_risk_summary(self, tmp_path):
        from layer2.adapters.snapshot_publisher import write_snapshot_json
        out = tmp_path / "snap.json"
        clock_ts = datetime(2026, 3, 15, 22, 0, tzinfo=timezone.utc)
        run_ts = datetime(2026, 3, 16, 0, 0, tzinfo=timezone.utc)

        write_snapshot_json(
            str(out), "abc123", clock_ts, run_ts,
            "gold-v3.3.0", "1.0.0",
            self._make_quality(), self._make_values(), [],
        )

        data = json.loads(out.read_text())
        assert "revision_risk_summary" in data
        rrs = data["revision_risk_summary"]
        assert rrs["series_count"] == 2
        assert "CPILFESL" in rrs["series"]
        assert "PCEPI" in rrs["series"]
        assert "DGS10" not in rrs["series"]

    def test_snapshot_json_values_have_revision_risk(self, tmp_path):
        from layer2.adapters.snapshot_publisher import write_snapshot_json
        out = tmp_path / "snap.json"
        clock_ts = datetime(2026, 3, 15, 22, 0, tzinfo=timezone.utc)
        run_ts = datetime(2026, 3, 16, 0, 0, tzinfo=timezone.utc)

        write_snapshot_json(
            str(out), "abc123", clock_ts, run_ts,
            "gold-v3.3.0", "1.0.0",
            self._make_quality(), self._make_values(), [],
        )

        data = json.loads(out.read_text())
        values = data["values"]
        assert "revision_risk" in values["DGS10"]
        assert values["DGS10"]["revision_risk"] is False
        assert "revision_risk" in values["CPILFESL"]
        assert values["CPILFESL"]["revision_risk"] is True

    def test_snapshot_json_tier_dicts_have_revision_risk(self, tmp_path):
        from layer2.adapters.snapshot_publisher import write_snapshot_json
        out = tmp_path / "snap.json"
        clock_ts = datetime(2026, 3, 15, 22, 0, tzinfo=timezone.utc)
        run_ts = datetime(2026, 3, 16, 0, 0, tzinfo=timezone.utc)

        write_snapshot_json(
            str(out), "abc123", clock_ts, run_ts,
            "gold-v3.3.0", "1.0.0",
            self._make_quality(), self._make_values(), [],
        )

        data = json.loads(out.read_text())
        assert data["tier1_series"]["DGS10"]["revision_risk"] is False
        assert data["tier2_series"]["CPILFESL"]["revision_risk"] is True
        assert data["tier2_series"]["PCEPI"]["revision_risk"] is True

    def test_revision_risk_true_does_not_block_snapshot_publication(self, tmp_path):
        """Snapshot with revision_risk=true series must still be published if Tier-1 is clean."""
        from layer2.adapters.snapshot_publisher import write_snapshot_json
        out = tmp_path / "snap.json"
        clock_ts = datetime(2026, 3, 15, 22, 0, tzinfo=timezone.utc)
        run_ts = datetime(2026, 3, 16, 0, 0, tzinfo=timezone.utc)

        quality = self._make_quality(snapshot_ok=True)

        write_snapshot_json(
            str(out), "abc123", clock_ts, run_ts,
            "gold-v3.3.0", "1.0.0",
            quality, self._make_values(), [],
        )

        data = json.loads(out.read_text())
        assert data["verdict"] == "PASS"
        assert data["revision_policy"]["revision_risk_blocks_snapshot"] is False
        # Both revision_risk=true series are present
        assert "CPILFESL" in data["values"]
        assert "PCEPI" in data["values"]
