"""
adapter_schema.py — Deterministic adapter-schema verdict synthesis.

Produces ``adapter_schema_verdict`` structurally from:
- governance_context.code_context (series_registry, adapter_inventory,
  layer2_boundary_checks, execution_artifact_scan)
- runtime_boundary_verdict (boundary compliance status)
- optionally contract_compliance_verdict

Design constraints:
- NO LLM invocation — pure deterministic policy evaluation.
- Registry-as-single-source-of-truth per CLAUDE.md §8.
- INSERT OR REPLACE is forbidden per code-conventions.md.
- Layer-3 execution artifacts must be absent.
- inference_used=false when structured evidence is present.
- inference_used=true only when required structured evidence is missing.
"""
from __future__ import annotations

from typing import Any

from governance.dag_runner.models import GovernanceRunState, WorkflowStep


# ---------------------------------------------------------------------------
# Checked item IDs
# ---------------------------------------------------------------------------

_AS01 = "AS-01"  # registry present and parseable
_AS02 = "AS-02"  # registry series count / tier / snapshot metadata
_AS03 = "AS-03"  # SP500 and SP500_PROXY coexistence / provenance
_AS04 = "AS-04"  # adapter inventory present
_AS05 = "AS-05"  # spy_adapter.py present when SP500_PROXY exists
_AS06 = "AS-06"  # INSERT OR REPLACE absent / INSERT OR IGNORE present
_AS07 = "AS-07"  # Layer-3 execution artifacts absent
_AS08 = "AS-08"  # runtime_boundary_verdict accepted
_AS09 = "AS-09"  # schema/content scan caveat


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_payload(run_state: GovernanceRunState, name: str) -> dict[str, Any]:
    """Return artifact payload or empty dict."""
    record = run_state.artifacts.get(name)
    if record is not None and record.status == "present":
        return record.payload
    return {}


def _checked_item(
    item_id: str,
    target: str,
    assessment: str,
    evidence_source: str,
    reason: str,
    missing_inputs: list[str] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "target": target,
        "assessment": assessment,
        "evidence_source": evidence_source,
        "reason": reason,
        "missing_inputs": missing_inputs or [],
        "notes": notes or [],
    }


# ---------------------------------------------------------------------------
# Main synthesis
# ---------------------------------------------------------------------------

def synthesize_adapter_schema_verdict(
    step: WorkflowStep,
    run_state: GovernanceRunState,
) -> dict[str, Any]:
    """Produce a deterministic adapter_schema_verdict from upstream artifacts.

    Evaluates registry compliance, schema write discipline, adapter boundary
    integrity, and SP500_PROXY provenance using runner-observed code_context
    and runtime_boundary_verdict. Does not invoke Claude.
    """
    gc_payload = _get_payload(run_state, "governance_context")
    rbv_payload = _get_payload(run_state, "runtime_boundary_verdict")

    code_context = gc_payload.get("code_context") or {}
    sr = code_context.get("series_registry") or {}
    ai = code_context.get("adapter_inventory") or {}
    bc = code_context.get("layer2_boundary_checks") or {}
    es = code_context.get("execution_artifact_scan") or {}

    # Unwrap runtime_boundary_verdict — may be nested
    rbv = rbv_payload.get("runtime_boundary_verdict") or rbv_payload

    # --- Evidence availability ---
    has_code_context = bool(code_context)
    has_sr = sr.get("status") == "present" or sr.get("series_count", 0) > 0
    has_ai = ai.get("status") == "present" or ai.get("adapter_count", 0) > 0
    has_rbv = bool(rbv) and rbv.get("overall_assessment") is not None

    inference_used = not (has_code_context and has_sr and has_ai)

    # --- Extract evidence fields ---
    registry_version = sr.get("registry_version")
    series_count = sr.get("series_count", 0)
    tier1_count = sr.get("tier1_count", 0)
    tier2_count = sr.get("tier2_count", 0)
    include_in_snapshot_count = sr.get("include_in_snapshot_count", 0)

    sp500_detected = sr.get("sp500_detected", False)
    sp500_proxy_detected = sr.get("sp500_proxy_detected", False)
    sp500_proxy_source = sr.get("sp500_proxy_source")
    sp500_proxy_full_history_start = sr.get("sp500_proxy_full_history_start")
    sp500_proxy_include_in_snapshot = sr.get("sp500_proxy_include_in_snapshot")
    sp500_proxy_tier = sr.get("sp500_proxy_tier")

    adapter_count = ai.get("adapter_count", 0)
    adapter_files = ai.get("adapter_files") or []

    insert_or_replace_detected = bc.get("insert_or_replace_detected", False)
    # Check individual checks for insert_or_ignore
    bc_checks = bc.get("checks") or []
    insert_or_ignore_detected = any(
        c.get("insert_or_ignore_count", 0) > 0 for c in bc_checks
        if isinstance(c, dict)
    )

    layer3_absent = es.get("layer3_execution_artifacts_absent")

    rbv_boundary_violation = rbv.get("boundary_violation_suspected", False)
    rbv_raw_access = rbv.get("raw_observation_access_detected", False)
    rbv_forbidden = rbv.get("forbidden_access_detected", False)
    rbv_latest_misuse = rbv.get("latest_snapshot_misuse_detected", False)
    rbv_overall = rbv.get("overall_assessment", "")

    runtime_boundary_compliant = (
        has_rbv
        and not rbv_boundary_violation
        and not rbv_raw_access
        and not rbv_forbidden
        and not rbv_latest_misuse
    )

    # --- Checked items ---
    checked_items: list[dict[str, Any]] = []
    blocking_reasons: list[str] = []
    review_reasons: list[str] = []
    notes: list[str] = []

    # AS-01: Registry present and parseable
    if has_sr and sr.get("status") != "missing":
        validation_errors = sr.get("validation_errors") or []
        if validation_errors:
            checked_items.append(_checked_item(
                _AS01, "series_registry.json", "review_only",
                "code_context.series_registry",
                f"Registry present but has validation errors: {validation_errors[:3]}",
            ))
            review_reasons.append(
                f"Registry has {len(validation_errors)} validation error(s)",
            )
        else:
            checked_items.append(_checked_item(
                _AS01, "series_registry.json", "compliant",
                "code_context.series_registry",
                f"Registry present, parseable, version={registry_version}",
            ))
    else:
        checked_items.append(_checked_item(
            _AS01, "series_registry.json", "blocked",
            "code_context.series_registry",
            "Registry missing or not parseable",
            missing_inputs=["series_registry.json"],
        ))
        blocking_reasons.append("series_registry missing or malformed")

    # AS-02: Registry series count / tier / snapshot metadata
    if has_sr and series_count > 0:
        checked_items.append(_checked_item(
            _AS02, "series_registry metadata", "compliant",
            "code_context.series_registry",
            f"series_count={series_count}, tier1={tier1_count}, "
            f"tier2={tier2_count}, include_in_snapshot={include_in_snapshot_count}",
        ))
    elif has_sr:
        checked_items.append(_checked_item(
            _AS02, "series_registry metadata", "review_only",
            "code_context.series_registry",
            "Registry present but series_count=0",
        ))
        review_reasons.append("Registry exists but contains no series")
    else:
        checked_items.append(_checked_item(
            _AS02, "series_registry metadata", "blocked",
            "code_context.series_registry",
            "Cannot assess — registry not available",
            missing_inputs=["series_registry"],
        ))

    # AS-03: SP500 and SP500_PROXY coexistence / provenance
    if sp500_detected and sp500_proxy_detected:
        sp500_source = sr.get("sp500_source")
        provenance_ok = (
            sp500_proxy_source == "yahoo_spy"
            and sp500_proxy_full_history_start == "2005-01-03"
            and sp500_proxy_include_in_snapshot is True
            and sp500_proxy_tier == 1
        )
        if provenance_ok and sp500_source == "fred":
            checked_items.append(_checked_item(
                _AS03, "SP500 / SP500_PROXY coexistence", "compliant",
                "code_context.series_registry",
                f"SP500 (source=fred) and SP500_PROXY (source=yahoo_spy, "
                f"full_history_start=2005-01-03, include_in_snapshot=true, "
                f"tier=1) both present with correct provenance",
            ))
        elif sp500_proxy_source != "yahoo_spy":
            checked_items.append(_checked_item(
                _AS03, "SP500_PROXY source", "blocked",
                "code_context.series_registry",
                f"SP500_PROXY source is '{sp500_proxy_source}', "
                f"expected 'yahoo_spy'",
            ))
            blocking_reasons.append(
                f"SP500_PROXY source={sp500_proxy_source}, expected yahoo_spy",
            )
        elif sp500_proxy_include_in_snapshot is False:
            checked_items.append(_checked_item(
                _AS03, "SP500_PROXY include_in_snapshot", "blocked",
                "code_context.series_registry",
                "SP500_PROXY include_in_snapshot=false — expected true",
            ))
            blocking_reasons.append("SP500_PROXY include_in_snapshot=false")
        elif sp500_proxy_tier != 1:
            checked_items.append(_checked_item(
                _AS03, "SP500_PROXY tier", "blocked",
                "code_context.series_registry",
                f"SP500_PROXY tier={sp500_proxy_tier}, expected 1",
            ))
            blocking_reasons.append(f"SP500_PROXY tier={sp500_proxy_tier}")
        else:
            checked_items.append(_checked_item(
                _AS03, "SP500 / SP500_PROXY coexistence", "review_only",
                "code_context.series_registry",
                f"SP500_PROXY provenance partially confirmed. "
                f"SP500 source={sp500_source}",
            ))
            review_reasons.append("SP500/SP500_PROXY provenance partially confirmed")
    elif sp500_proxy_detected and not sp500_detected:
        checked_items.append(_checked_item(
            _AS03, "SP500 / SP500_PROXY coexistence", "review_only",
            "code_context.series_registry",
            "SP500_PROXY present but SP500 not detected",
        ))
        review_reasons.append("SP500_PROXY without SP500")
    elif has_sr:
        checked_items.append(_checked_item(
            _AS03, "SP500 / SP500_PROXY", "not_applicable",
            "code_context.series_registry",
            "Neither SP500 nor SP500_PROXY detected in registry",
        ))
    else:
        checked_items.append(_checked_item(
            _AS03, "SP500 / SP500_PROXY", "blocked",
            "code_context.series_registry",
            "Cannot assess — registry not available",
            missing_inputs=["series_registry"],
        ))

    # AS-04: Adapter inventory present
    if has_ai:
        checked_items.append(_checked_item(
            _AS04, "adapter_inventory", "compliant",
            "code_context.adapter_inventory",
            f"Adapter directory present, {adapter_count} adapter(s): "
            f"{', '.join(adapter_files[:10])}",
        ))
    else:
        checked_items.append(_checked_item(
            _AS04, "adapter_inventory", "review_only",
            "code_context.adapter_inventory",
            "Adapter inventory not available in code_context",
            missing_inputs=["adapter_inventory"],
        ))
        review_reasons.append("Adapter inventory missing from code_context")

    # AS-05: spy_adapter.py present when SP500_PROXY exists
    if sp500_proxy_detected:
        spy_present = "spy_adapter.py" in adapter_files
        if spy_present:
            checked_items.append(_checked_item(
                _AS05, "spy_adapter.py", "compliant",
                "code_context.adapter_inventory",
                "spy_adapter.py present — required for SP500_PROXY",
            ))
        else:
            checked_items.append(_checked_item(
                _AS05, "spy_adapter.py", "blocked",
                "code_context.adapter_inventory",
                "SP500_PROXY exists in registry but spy_adapter.py "
                "not found in adapter inventory",
                missing_inputs=["spy_adapter.py"],
            ))
            blocking_reasons.append(
                "SP500_PROXY present but spy_adapter.py missing",
            )
    else:
        checked_items.append(_checked_item(
            _AS05, "spy_adapter.py", "not_applicable",
            "code_context.series_registry",
            "SP500_PROXY not detected — spy_adapter check not applicable",
        ))

    # AS-06: INSERT OR REPLACE absent / INSERT OR IGNORE present
    if bc and bc.get("checks"):
        if insert_or_replace_detected:
            checked_items.append(_checked_item(
                _AS06, "schema write discipline", "blocked",
                "code_context.layer2_boundary_checks",
                "INSERT OR REPLACE detected in Layer-2 write paths",
            ))
            blocking_reasons.append("INSERT OR REPLACE detected")
        else:
            checked_items.append(_checked_item(
                _AS06, "schema write discipline", "compliant",
                "code_context.layer2_boundary_checks",
                f"INSERT OR REPLACE absent. INSERT OR IGNORE "
                f"{'detected' if insert_or_ignore_detected else 'not scanned'}",
            ))
    else:
        checked_items.append(_checked_item(
            _AS06, "schema write discipline", "review_only",
            "code_context.layer2_boundary_checks",
            "Boundary check data not available",
            missing_inputs=["layer2_boundary_checks"],
        ))
        review_reasons.append("Boundary checks not available for schema write scan")

    # AS-07: Layer-3 execution artifacts absent
    if layer3_absent is True:
        checked_items.append(_checked_item(
            _AS07, "Layer-3 execution artifacts", "compliant",
            "code_context.execution_artifact_scan",
            "Layer-3 execution artifacts absent",
        ))
    elif layer3_absent is False:
        detected = es.get("detected_layer3_indicators") or []
        checked_items.append(_checked_item(
            _AS07, "Layer-3 execution artifacts", "blocked",
            "code_context.execution_artifact_scan",
            f"Layer-3 execution artifacts detected: {detected[:5]}",
        ))
        blocking_reasons.append("Layer-3 execution artifacts detected")
    else:
        checked_items.append(_checked_item(
            _AS07, "Layer-3 execution artifacts", "review_only",
            "code_context.execution_artifact_scan",
            "Execution artifact scan not available",
            missing_inputs=["execution_artifact_scan"],
        ))
        review_reasons.append("Execution artifact scan unavailable")

    # AS-08: runtime_boundary_verdict accepted
    if has_rbv:
        if runtime_boundary_compliant:
            checked_items.append(_checked_item(
                _AS08, "runtime_boundary_verdict", "compliant",
                "runtime_boundary_verdict",
                f"Runtime boundary verdict: {rbv_overall}. "
                f"No boundary violations suspected.",
            ))
        else:
            violation_signals = []
            if rbv_boundary_violation:
                violation_signals.append("boundary_violation_suspected=true")
            if rbv_raw_access:
                violation_signals.append("raw_observation_access_detected=true")
            if rbv_forbidden:
                violation_signals.append("forbidden_access_detected=true")
            if rbv_latest_misuse:
                violation_signals.append("latest_snapshot_misuse_detected=true")
            checked_items.append(_checked_item(
                _AS08, "runtime_boundary_verdict", "blocked",
                "runtime_boundary_verdict",
                f"Runtime boundary violation: {', '.join(violation_signals)}",
            ))
            blocking_reasons.append(
                f"runtime_boundary_verdict: {', '.join(violation_signals)}",
            )
    else:
        checked_items.append(_checked_item(
            _AS08, "runtime_boundary_verdict", "review_only",
            "runtime_boundary_verdict",
            "runtime_boundary_verdict not available",
            missing_inputs=["runtime_boundary_verdict"],
        ))
        review_reasons.append("runtime_boundary_verdict not available")

    # AS-09: Content scan caveat
    unresolved_content_scan_caveat = False
    if has_ai and adapter_count > 0:
        # Adapter inventory is structural (file names only), not content-scanned
        unresolved_content_scan_caveat = True
        checked_items.append(_checked_item(
            _AS09, "adapter content scan", "review_only",
            "code_context.adapter_inventory",
            "Adapter inventory is structural (file listing only). "
            "Full content-level pattern scan of adapter source files "
            "not performed by runner.",
            notes=[
                "Content scan requires direct file read access, "
                "which the structural runner does not perform.",
            ],
        ))
        review_reasons.append(
            "Adapter content scan unavailable — structural inventory only",
        )
    elif not has_ai:
        unresolved_content_scan_caveat = True
        checked_items.append(_checked_item(
            _AS09, "adapter content scan", "review_only",
            "code_context.adapter_inventory",
            "Adapter inventory not available — content scan not possible",
            missing_inputs=["adapter_inventory"],
        ))

    # --- Determine sub-statuses ---
    # Registry-driven status
    registry_items = [c for c in checked_items if c["item_id"] in (_AS01, _AS02)]
    if any(c["assessment"] == "blocked" for c in registry_items):
        registry_driven_status = "blocked"
    elif any(c["assessment"] == "review_only" for c in registry_items):
        registry_driven_status = "review_only"
    else:
        registry_driven_status = "compliant"

    # Schema write status
    schema_items = [c for c in checked_items if c["item_id"] == _AS06]
    if any(c["assessment"] == "blocked" for c in schema_items):
        schema_write_status = "blocked"
    elif any(c["assessment"] == "review_only" for c in schema_items):
        schema_write_status = "review_only"
    else:
        schema_write_status = "compliant"

    # Adapter boundary status
    boundary_items = [
        c for c in checked_items
        if c["item_id"] in (_AS04, _AS05, _AS07, _AS08, _AS09)
    ]
    if any(c["assessment"] == "blocked" for c in boundary_items):
        adapter_boundary_status = "blocked"
    elif any(c["assessment"] == "review_only" for c in boundary_items):
        adapter_boundary_status = "review_only"
    else:
        adapter_boundary_status = "compliant"

    # SP500 proxy status
    sp500_items = [c for c in checked_items if c["item_id"] in (_AS03, _AS05)]
    if not sp500_proxy_detected and has_sr:
        sp500_proxy_status = "not_applicable"
    elif any(c["assessment"] == "blocked" for c in sp500_items):
        sp500_proxy_status = "blocked"
    elif any(c["assessment"] == "review_only" for c in sp500_items):
        sp500_proxy_status = "review_only"
    else:
        sp500_proxy_status = "compliant"

    # --- Overall status ---
    if blocking_reasons:
        overall_status = "blocked"
    elif review_reasons:
        overall_status = "review_only"
    else:
        overall_status = "compliant"

    # --- Build result ---
    return {
        "produced_by": "adapter-schema-check",
        "adapter_schema_status": {
            "overall_status": overall_status,
            "inference_used": inference_used,
            "registry_driven_status": registry_driven_status,
            "schema_write_status": schema_write_status,
            "adapter_boundary_status": adapter_boundary_status,
            "sp500_proxy_status": sp500_proxy_status,
            "checked_items": checked_items,
            "summary": {
                "registry_present": has_sr,
                "registry_version": registry_version,
                "series_count": series_count,
                "tier1_count": tier1_count,
                "tier2_count": tier2_count,
                "include_in_snapshot_count": include_in_snapshot_count,
                "sp500_detected": sp500_detected,
                "sp500_proxy_detected": sp500_proxy_detected,
                "sp500_proxy_source": sp500_proxy_source,
                "sp500_proxy_full_history_start": sp500_proxy_full_history_start,
                "sp500_proxy_include_in_snapshot": sp500_proxy_include_in_snapshot,
                "sp500_proxy_tier": sp500_proxy_tier,
                "adapter_count": adapter_count,
                "adapter_files": adapter_files[:20],
                "insert_or_replace_detected": insert_or_replace_detected,
                "insert_or_ignore_detected": insert_or_ignore_detected,
                "layer3_execution_artifacts_absent": layer3_absent,
                "runtime_boundary_compliant": runtime_boundary_compliant,
                "unresolved_content_scan_caveat": unresolved_content_scan_caveat,
                "blocking_reasons": blocking_reasons[:10],
                "review_reasons": review_reasons[:10],
                "notes": notes[:10],
            },
        },
        "registry_driven_compliance": registry_driven_status == "compliant",
        "schema_violation_detected": insert_or_replace_detected,
        "adapter_boundary_violation_detected": adapter_boundary_status == "blocked",
        "source_authority_conflict_detected": False,
        "requires_adapter_schema_guardian": overall_status == "blocked",
        "requires_doc_code_sync_review": overall_status in ("review_only", "blocked"),
        "inference_used": inference_used,
    }
