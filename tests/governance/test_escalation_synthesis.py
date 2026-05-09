"""Tests for audit escalation synthesis in executor.py.

Covers the expanded _ESCALATION_STATUS_BLOCK_VALUES,
_ESCALATION_STATUS_REVIEW_VALUES, overall_boundary_status key scan,
and proper severity mapping for LLM-produced compound statuses.
"""
from __future__ import annotations

from typing import Any

import pytest

from governance.dag_runner.executor import (
    _ESCALATION_STATUS_BLOCK_VALUES,
    _ESCALATION_STATUS_REVIEW_VALUES,
    _scan_for_escalation_signals,
)


# ── _ESCALATION_STATUS_BLOCK_VALUES membership ──


def test_block_values_include_classic_statuses() -> None:
    for val in ("fail", "block", "blocked", "review_only"):
        assert val in _ESCALATION_STATUS_BLOCK_VALUES


def test_block_values_include_compound_block_statuses() -> None:
    assert "ambiguous_requires_block" in _ESCALATION_STATUS_BLOCK_VALUES
    assert "conflict_requires_block" in _ESCALATION_STATUS_BLOCK_VALUES


def test_review_values_include_ambiguous_review() -> None:
    assert "ambiguous_requires_review" in _ESCALATION_STATUS_REVIEW_VALUES


# ── _scan_for_escalation_signals: compound status detection ──


def _make_artifacts(**kwargs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return kwargs


def test_scan_detects_ambiguous_requires_block() -> None:
    arts = _make_artifacts(
        contract_compliance_verdict={
            "contract_status": "ambiguous_requires_block",
        },
    )
    findings = _scan_for_escalation_signals(arts)
    match = [
        f for f in findings
        if "ambiguous_requires_block" in f["signal"]
    ]
    assert len(match) == 1
    assert match[0]["severity"] == "blocking"


def test_scan_detects_conflict_requires_block() -> None:
    arts = _make_artifacts(
        role_citation_verdict={
            "overall_status": "conflict_requires_block",
        },
    )
    findings = _scan_for_escalation_signals(arts)
    match = [
        f for f in findings
        if "conflict_requires_block" in f["signal"]
    ]
    assert len(match) == 1
    assert match[0]["severity"] == "blocking"


def test_scan_detects_ambiguous_requires_review() -> None:
    arts = _make_artifacts(
        runtime_boundary_verdict={
            "overall_status": "ambiguous_requires_review",
        },
    )
    findings = _scan_for_escalation_signals(arts)
    match = [
        f for f in findings
        if "ambiguous_requires_review" in f["signal"]
    ]
    assert len(match) == 1
    assert match[0]["severity"] == "review"


def test_scan_detects_overall_boundary_status() -> None:
    """overall_boundary_status key is scanned (not just overall_status)."""
    arts = _make_artifacts(
        runtime_boundary_verdict={
            "overall_boundary_status": "blocked",
        },
    )
    findings = _scan_for_escalation_signals(arts)
    match = [
        f for f in findings
        if "overall_boundary_status=blocked" in f["signal"]
    ]
    assert len(match) == 1
    assert match[0]["severity"] == "blocking"


def test_scan_detects_alignment_status_block() -> None:
    arts = _make_artifacts(
        phase_alignment_status={
            "alignment_status": "ambiguous_requires_block",
        },
    )
    findings = _scan_for_escalation_signals(arts)
    match = [
        f for f in findings
        if "ambiguous_requires_block" in f["signal"]
    ]
    assert len(match) == 1
    assert match[0]["severity"] == "blocking"


# ── Severity mapping correctness ──


def test_severity_blocking_for_fail() -> None:
    arts = _make_artifacts(test={"overall_status": "fail"})
    findings = _scan_for_escalation_signals(arts)
    assert findings[0]["severity"] == "blocking"


def test_severity_blocking_for_blocked() -> None:
    arts = _make_artifacts(test={"overall_status": "blocked"})
    findings = _scan_for_escalation_signals(arts)
    assert findings[0]["severity"] == "blocking"


def test_severity_review_for_review_only() -> None:
    arts = _make_artifacts(test={"overall_status": "review_only"})
    findings = _scan_for_escalation_signals(arts)
    assert findings[0]["severity"] == "review"


# ── No false positives ──


def test_scan_no_findings_for_clean_artifact() -> None:
    arts = _make_artifacts(
        test={
            "overall_status": "pass",
            "allowed": True,
            "produced_by": "test",
        },
    )
    findings = _scan_for_escalation_signals(arts)
    assert len(findings) == 0


def test_scan_no_findings_for_empty_artifacts() -> None:
    findings = _scan_for_escalation_signals({})
    assert len(findings) == 0


# ── Multiple signals from single artifact ──


def test_scan_multiple_signals_single_artifact() -> None:
    arts = _make_artifacts(
        runtime_boundary_verdict={
            "overall_status": "ambiguous_requires_review",
            "boundary_violation_suspected": True,
            "requires_snapshot_boundary_auditor": True,
        },
    )
    findings = _scan_for_escalation_signals(arts)
    # Should detect at least 3 signals
    assert len(findings) >= 3

    signals = {f["signal"] for f in findings}
    assert any("ambiguous_requires_review" in s for s in signals)
    assert "boundary_violation_suspected" in signals
    assert "requires_snapshot_boundary_auditor" in signals


# ── Cross-artifact convergence ──


def test_scan_convergent_blocking_across_artifacts() -> None:
    """Multiple artifacts with blocking signals produce convergent findings."""
    arts = _make_artifacts(
        phase_alignment_status={
            "allowed": False,
            "alignment_status": "ambiguous_requires_block",
        },
        contract_compliance_verdict={
            "allowed": False,
            "contract_status": "ambiguous_requires_block",
        },
        runtime_boundary_verdict={
            "overall_status": "ambiguous_requires_review",
            "boundary_violation_suspected": True,
        },
    )
    findings = _scan_for_escalation_signals(arts)

    blocking = [f for f in findings if f["severity"] == "blocking"]
    review = [f for f in findings if f["severity"] == "review"]

    # Should have blocking findings from phase + contract (allowed=false)
    assert len(blocking) >= 4
    # Should have review finding from runtime boundary
    assert len(review) >= 1
