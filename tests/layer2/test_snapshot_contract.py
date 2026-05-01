"""
tests/layer2/test_snapshot_contract.py
---------------------------------------
Phase 2 snapshot contract completeness tests.

Proves:
- validate_snapshot_contract passes on a valid snapshot dict
- missing required top-level field fails validation
- missing guards field fails validation
- invalid reason_code fails validation
- forced snapshot has forced=True and data_ok=False in guards
- Tier-1 missing/stale yields data_ok=False in guards
- values_by_group and values contain equivalent series_ids
- all values include as_of_ts, revision_seq, and revision_risk
- build_guards produces correct reason_code under each condition
- validate_guards rejects bad inputs
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pytest

# Path setup handled by tests/layer2/conftest.py


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_valid_values() -> Dict[str, Any]:
    return {
        "DGS10": {
            "obs_ts": "2026-03-15",
            "value": 4.2,
            "staleness_days": 0,
            "tier": 1,
            "group": "nominal_yields",
            "source": "fred",
            "as_of_ts": "2026-03-15T22:00:00+00:00",
            "revision_seq": 0,
            "revision_risk": False,
        },
        "CPILFESL": {
            "obs_ts": "2026-03-01",
            "value": 3.8,
            "staleness_days": 14,
            "tier": 2,
            "group": "inflation_monthly",
            "source": "fred",
            "as_of_ts": "2026-03-15T22:00:00+00:00",
            "revision_seq": 0,
            "revision_risk": True,
        },
    }


def _make_valid_values_by_group() -> Dict[str, Any]:
    values = _make_valid_values()
    by_group: Dict[str, list] = {}
    for sid, v in values.items():
        entry = dict(v, series_id=sid)
        by_group.setdefault(v["group"], []).append(entry)
    return by_group


def _make_valid_guards(
    *,
    forced: bool = False,
    missing_tier1: bool = False,
    freshness_ok: bool = True,
    snapshot_ok: bool = True,
    revision_risk_present: bool = True,
) -> dict:
    from layer2.constants import build_guards
    return build_guards(
        snapshot_ok=snapshot_ok,
        forced=forced,
        missing_tier1=missing_tier1,
        freshness_ok=freshness_ok,
        revision_risk_present=revision_risk_present,
    )


def _make_valid_snapshot(**overrides) -> dict:
    snap = {
        "snapshot_id": "abc123",
        "engine_version": "gold-v3.3.0",
        "config_version": "1.0.0",
        "clock_ts": "2026-03-15T22:00:00+00:00",
        "clock_date": "2026-03-15",
        "verdict": "PASS",
        "forced": False,
        "dry_run": False,
        "guards": _make_valid_guards(),
        "revision_policy": {
            "method": "latest_available_with_revision_risk_flag",
            "revision_writer": "not_implemented",
            "revision_risk_blocks_snapshot": False,
        },
        "revision_risk_summary": {"series_count": 1, "series": ["CPILFESL"]},
        "tier1_series": {},
        "tier2_series": {},
        "missing_series": [],
        "layer1_events": [],
        "run_ts": "2026-03-16T00:00:00+00:00",
        "published_at": "2026-03-16T00:00:00+00:00",
        "series_count": 2,
        "quality_summary": {
            "tier1_total": 1, "tier1_pass": 1, "tier1_fail": 0,
            "tier2_total": 1, "tier2_warn": 0,
        },
        "values_by_group": _make_valid_values_by_group(),
        "values": _make_valid_values(),
    }
    snap.update(overrides)
    return snap


# ---------------------------------------------------------------------------
# A. validate_snapshot_contract — passing case
# ---------------------------------------------------------------------------

class TestValidSnapshotPasses:
    def test_valid_snapshot_passes_contract(self):
        from layer2.constants import validate_snapshot_contract
        validate_snapshot_contract(_make_valid_snapshot())

    def test_valid_snapshot_with_forced_passes_contract(self):
        from layer2.constants import validate_snapshot_contract
        guards = _make_valid_guards(forced=True)
        snap = _make_valid_snapshot(forced=True, guards=guards, verdict="FAIL")
        validate_snapshot_contract(snap)


# ---------------------------------------------------------------------------
# B. Missing required top-level field fails
# ---------------------------------------------------------------------------

class TestMissingTopLevelField:
    @pytest.mark.parametrize("field", [
        "snapshot_id", "engine_version", "config_version",
        "clock_ts", "clock_date", "verdict", "forced", "dry_run",
        "guards", "tier1_series", "tier2_series", "missing_series",
        "layer1_events", "run_ts", "published_at", "series_count",
        "quality_summary", "values_by_group", "values",
        "revision_policy", "revision_risk_summary",
    ])
    def test_missing_field_raises(self, field: str):
        from layer2.constants import validate_snapshot_contract
        snap = _make_valid_snapshot()
        del snap[field]
        with pytest.raises(ValueError, match=field):
            validate_snapshot_contract(snap)


# ---------------------------------------------------------------------------
# C. Missing guards field fails
# ---------------------------------------------------------------------------

class TestMissingGuardsField:
    @pytest.mark.parametrize("field", [
        "data_ok", "freshness_ok", "idempotent_ok", "revision_risk_present",
        "forced", "missing_tier1", "snapshot_ok", "reason_code",
    ])
    def test_missing_guards_field_raises(self, field: str):
        from layer2.constants import validate_snapshot_contract
        snap = _make_valid_snapshot()
        del snap["guards"][field]
        with pytest.raises(ValueError, match=field):
            validate_snapshot_contract(snap)

    def test_guards_wrong_type_raises(self):
        from layer2.constants import validate_snapshot_contract
        snap = _make_valid_snapshot()
        snap["guards"]["data_ok"] = "yes"
        with pytest.raises(ValueError, match="data_ok"):
            validate_snapshot_contract(snap)


# ---------------------------------------------------------------------------
# D. Invalid reason_code fails
# ---------------------------------------------------------------------------

class TestInvalidReasonCode:
    def test_invalid_reason_code_raises(self):
        from layer2.constants import validate_snapshot_contract
        snap = _make_valid_snapshot()
        snap["guards"]["reason_code"] = "TOTALLY_MADE_UP"
        with pytest.raises(ValueError, match="TOTALLY_MADE_UP"):
            validate_snapshot_contract(snap)

    def test_empty_reason_code_raises(self):
        from layer2.constants import validate_snapshot_contract
        snap = _make_valid_snapshot()
        snap["guards"]["reason_code"] = ""
        with pytest.raises(ValueError):
            validate_snapshot_contract(snap)

    def test_valid_reason_codes_pass(self):
        from layer2.constants import validate_snapshot_contract, ReasonCode
        for code in ReasonCode.data_layer_codes():
            snap = _make_valid_snapshot()
            snap["guards"]["reason_code"] = code.value
            # no exception
            validate_snapshot_contract(snap)


# ---------------------------------------------------------------------------
# E. Forced snapshot guard semantics
# ---------------------------------------------------------------------------

class TestForcedSnapshotGuards:
    def test_forced_snapshot_has_forced_true(self):
        guards = _make_valid_guards(forced=True)
        assert guards["forced"] is True

    def test_forced_snapshot_has_data_ok_false(self):
        guards = _make_valid_guards(forced=True, snapshot_ok=True)
        assert guards["data_ok"] is False

    def test_forced_snapshot_reason_code_is_data_forced(self):
        from layer2.constants import ReasonCode
        guards = _make_valid_guards(forced=True, snapshot_ok=True)
        assert guards["reason_code"] == ReasonCode.DATA_FORCED.value

    def test_forced_snapshot_passes_contract_validation(self):
        from layer2.constants import validate_snapshot_contract
        guards = _make_valid_guards(forced=True, snapshot_ok=False, freshness_ok=False)
        snap = _make_valid_snapshot(forced=True, verdict="FAIL", guards=guards)
        validate_snapshot_contract(snap)


# ---------------------------------------------------------------------------
# F. Tier-1 missing / stale yields data_ok=False
# ---------------------------------------------------------------------------

class TestTier1FailGuards:
    def test_missing_tier1_sets_data_ok_false(self):
        guards = _make_valid_guards(missing_tier1=True, snapshot_ok=False, freshness_ok=False)
        assert guards["data_ok"] is False
        assert guards["missing_tier1"] is True

    def test_missing_tier1_reason_code_is_data_missing(self):
        from layer2.constants import ReasonCode
        guards = _make_valid_guards(missing_tier1=True, snapshot_ok=False, freshness_ok=False)
        assert guards["reason_code"] == ReasonCode.DATA_MISSING.value

    def test_stale_tier1_sets_data_ok_false(self):
        guards = _make_valid_guards(freshness_ok=False, snapshot_ok=False)
        assert guards["data_ok"] is False
        assert guards["freshness_ok"] is False

    def test_stale_tier1_reason_code_is_data_stale(self):
        from layer2.constants import ReasonCode
        guards = _make_valid_guards(freshness_ok=False, snapshot_ok=False)
        assert guards["reason_code"] == ReasonCode.DATA_STALE.value

    def test_clean_tier1_sets_data_ok_true(self):
        from layer2.constants import ReasonCode
        guards = _make_valid_guards(forced=False, missing_tier1=False, freshness_ok=True, snapshot_ok=True)
        assert guards["data_ok"] is True
        assert guards["reason_code"] == ReasonCode.DATA_OK.value


# ---------------------------------------------------------------------------
# G. values_by_group and values series_id equivalence
# ---------------------------------------------------------------------------

class TestValuesGroupEquivalence:
    def test_equivalent_ids_pass(self):
        from layer2.constants import validate_snapshot_contract
        validate_snapshot_contract(_make_valid_snapshot())

    def test_extra_in_values_raises(self):
        from layer2.constants import validate_snapshot_contract
        snap = _make_valid_snapshot()
        snap["values"]["ORPHAN"] = snap["values"]["DGS10"].copy()
        with pytest.raises(ValueError, match="ORPHAN"):
            validate_snapshot_contract(snap)

    def test_extra_in_values_by_group_raises(self):
        from layer2.constants import validate_snapshot_contract
        snap = _make_valid_snapshot()
        orphan = dict(snap["values"]["DGS10"], series_id="ORPHAN2")
        snap["values_by_group"]["nominal_yields"].append(orphan)
        with pytest.raises(ValueError, match="ORPHAN2"):
            validate_snapshot_contract(snap)


# ---------------------------------------------------------------------------
# H. All values include required per-series fields
# ---------------------------------------------------------------------------

class TestValueRequiredFields:
    @pytest.mark.parametrize("field", [
        "obs_ts", "value", "staleness_days", "tier", "source",
        "as_of_ts", "revision_seq", "revision_risk",
    ])
    def test_missing_value_field_raises(self, field: str):
        from layer2.constants import validate_snapshot_contract
        snap = _make_valid_snapshot()
        del snap["values"]["DGS10"][field]
        with pytest.raises(ValueError, match=field):
            validate_snapshot_contract(snap)

    def test_all_values_have_as_of_ts(self):
        values = _make_valid_values()
        for sid, v in values.items():
            assert "as_of_ts" in v, f"{sid} missing as_of_ts"
            assert v["as_of_ts"] is not None

    def test_all_values_have_revision_seq(self):
        values = _make_valid_values()
        for sid, v in values.items():
            assert "revision_seq" in v, f"{sid} missing revision_seq"


# ---------------------------------------------------------------------------
# I. Revision risk in guards and values
# ---------------------------------------------------------------------------

class TestRevisionRiskInContract:
    def test_revision_risk_present_true_when_any_value_has_it(self):
        guards = _make_valid_guards(revision_risk_present=True)
        assert guards["revision_risk_present"] is True

    def test_revision_risk_present_false_when_none_have_it(self):
        guards = _make_valid_guards(revision_risk_present=False)
        assert guards["revision_risk_present"] is False

    def test_all_values_have_revision_risk_field(self):
        values = _make_valid_values()
        for sid, v in values.items():
            assert "revision_risk" in v, f"{sid} missing revision_risk"
            assert isinstance(v["revision_risk"], bool), f"{sid} revision_risk must be bool"


# ---------------------------------------------------------------------------
# J. write_snapshot_json produces contract-valid output
# ---------------------------------------------------------------------------

class TestWriteSnapshotJsonProducesValidContract:
    def _make_quality(self, snapshot_ok: bool = True) -> dict:
        return {
            "snapshot_ok": snapshot_ok,
            "summary": {
                "tier1_total": 1, "tier1_pass": 1 if snapshot_ok else 0,
                "tier1_fail": 0 if snapshot_ok else 1,
                "tier2_total": 1, "tier2_warn": 0,
            },
            "blocking_failures": [],
            "tier2_warnings": [],
        }

    def _make_values(self) -> list:
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
        ]

    def test_write_snapshot_json_passes_contract_validation(self, tmp_path):
        from layer2.adapters.snapshot_publisher import write_snapshot_json
        from layer2.constants import validate_snapshot_contract
        out = tmp_path / "snap.json"
        clock_ts = datetime(2026, 3, 15, 22, 0, tzinfo=timezone.utc)
        run_ts = datetime(2026, 3, 16, 0, 0, tzinfo=timezone.utc)

        write_snapshot_json(
            str(out), "abc123", clock_ts, run_ts,
            "gold-v3.3.0", "1.0.0",
            self._make_quality(), self._make_values(), [],
        )

        data = json.loads(out.read_text())
        validate_snapshot_contract(data)

    def test_guards_fields_present_in_written_snapshot(self, tmp_path):
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
        guards = data["guards"]
        for field in ("data_ok", "freshness_ok", "idempotent_ok",
                      "revision_risk_present", "forced", "missing_tier1",
                      "snapshot_ok", "reason_code"):
            assert field in guards, f"guards missing {field}"

    def test_guards_revision_risk_present_reflects_payload(self, tmp_path):
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
        assert data["guards"]["revision_risk_present"] is True

    def test_forced_snapshot_guards_data_ok_false(self, tmp_path):
        from layer2.adapters.snapshot_publisher import write_snapshot_json
        out = tmp_path / "snap.json"
        clock_ts = datetime(2026, 3, 15, 22, 0, tzinfo=timezone.utc)
        run_ts = datetime(2026, 3, 16, 0, 0, tzinfo=timezone.utc)

        write_snapshot_json(
            str(out), "forced123", clock_ts, run_ts,
            "gold-v3.3.0", "1.0.0",
            self._make_quality(snapshot_ok=True), self._make_values(), [],
            forced=True,
        )

        data = json.loads(out.read_text())
        assert data["guards"]["forced"] is True
        assert data["guards"]["data_ok"] is False
        assert data["guards"]["reason_code"] == "DATA_FORCED"
