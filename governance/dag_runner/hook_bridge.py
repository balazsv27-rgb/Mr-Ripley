"""
hook_bridge.py — Read-only bridge from governance hooks to persisted DAG run state.

This module is the stable API between the .claude/hooks/ runtime enforcement hooks
and the governance_run_state.json file produced by the DAG runner.

Design rules
------------
- Read-only: no writes to disk, no mutation of loaded state.
- Fail closed: missing data raises explicit exceptions rather than silently returning
  success values that could mask governance failures.
- No live runner dependency: consumes only the persisted JSON artifact.
- No YAML loading, no subprocess calls, no artifact-store writes.
- Standard library only.

Resolution order (documented per function)
-------------------------------------------
final_verdict:
  1. top-level 'final_verdict'
  2. top-level 'verdict_status'
  3. None (if structurally valid but genuinely absent)

artifacts:
  1. 'artifact_records' list → converted to name-keyed map internally

pr_readiness:
  1. top-level 'pr_readiness' str  (Phase 3 compact contract — wrapped as {"status": value})
  2. top-level 'pr_readiness' dict (legacy dict form)
  3. artifact named 'pr_readiness_verdict' in artifact_records
  4. None

unresolved blocks:
  1. blocker_unknown_reference_count > 0 (explicit unknown references)
  2. resolved verdict == 'blocked' (authoritative evidence)
  3. RunStateStructureError if no blocker structure and no verdict present
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from governance.dag_runner.state_store import DEFAULT_STATE_PATH


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class HookBridgeError(Exception):
    """Base exception for all hook-bridge errors."""


class RunStateNotFoundError(HookBridgeError):
    """Raised when the persisted run-state file does not exist or cannot be read."""


class RunStateDecodeError(HookBridgeError):
    """Raised when the run-state file exists but contains invalid JSON."""


class RunStateStructureError(HookBridgeError):
    """Raised when the run-state payload is structurally insufficient for a query."""


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _default_run_state_path() -> Path:
    """Return the default governance run-state path from the state store."""
    return DEFAULT_STATE_PATH


def _validate_minimal_structure(run_state: dict[str, Any]) -> None:
    """
    Verify that the run-state dict contains the minimum fields required for
    any hook-bridge query.

    Validates:
    - 'workflow_name' is present (run identity)
    - 'artifact_records' is present and is a list
    - 'execution_trace' is present and is a list
    - at least one of 'final_verdict' or 'verdict_status' is present

    Raises RunStateStructureError on any failure.
    """
    required_keys = {"workflow_name", "artifact_records", "execution_trace"}
    verdict_keys = {"final_verdict", "verdict_status"}

    missing = required_keys - set(run_state)
    if missing:
        raise RunStateStructureError(
            f"Run-state payload is missing required field(s): {sorted(missing)}. "
            "The file may be from an incompatible version or was truncated."
        )

    if not verdict_keys.intersection(run_state):
        raise RunStateStructureError(
            "Run-state payload contains neither 'final_verdict' nor 'verdict_status'. "
            "Cannot determine governance verdict from this payload."
        )

    if not isinstance(run_state["artifact_records"], list):
        raise RunStateStructureError(
            "'artifact_records' must be a list, got "
            f"{type(run_state['artifact_records']).__name__}."
        )

    if not isinstance(run_state["execution_trace"], list):
        raise RunStateStructureError(
            "'execution_trace' must be a list, got "
            f"{type(run_state['execution_trace']).__name__}."
        )


def _extract_artifact_map(run_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """
    Convert the 'artifact_records' list into a name-keyed dict for O(1) lookup.
    Entries that are not dicts or lack a 'name' key are silently skipped.
    """
    return {
        rec["name"]: rec
        for rec in run_state.get("artifact_records", [])
        if isinstance(rec, dict) and "name" in rec
    }


def _extract_final_verdict(run_state: dict[str, Any]) -> str | None:
    """
    Resolve the final verdict with deterministic priority:
      1. top-level 'final_verdict' (set by the executor after the run completes)
      2. top-level 'verdict_status' (set at verdict-computation time, pre-execution)
      3. None if both are absent or None

    Returns a string or None. Does not invent a verdict.
    """
    fv = run_state.get("final_verdict")
    if fv is not None:
        return str(fv)
    vs = run_state.get("verdict_status")
    if vs is not None:
        return str(vs)
    return None


def _extract_blocking_conditions(run_state: dict[str, Any]) -> dict[str, Any]:
    """
    Extract and normalise blocker-related fields into a query-ready dict.

    The V1 run-state format exposes blocker structural analysis (counts, consistency)
    rather than a list of runtime BlockingEvent objects. This function normalises
    those fields.

    Returned keys:
      unknown_reference_count (int)  — blocker references that have no declared match
      orphan_count (int)             — declared blockers with no workflow step reference
      structurally_consistent (bool) — overall registry/reference consistency
      verdict_blocked (bool)         — whether the resolved verdict is 'blocked'

    Raises RunStateStructureError when no blocker structure AND no verdict are
    present, refusing to return a guess when required data is missing.
    """
    blocker_keys = {
        "blocker_unknown_reference_count",
        "blocker_orphan_count",
        "blocker_structurally_consistent",
    }
    has_blocker_structure = bool(blocker_keys.intersection(run_state))
    has_verdict = bool({"final_verdict", "verdict_status"}.intersection(run_state))

    if not has_blocker_structure and not has_verdict:
        # Fail closed: nothing useful to answer from.
        raise RunStateStructureError(
            "Run-state payload contains no blocker structure fields and no verdict. "
            "Cannot evaluate unresolved blocking conditions."
        )

    return {
        "unknown_reference_count": int(run_state.get("blocker_unknown_reference_count", 0)),
        "orphan_count": int(run_state.get("blocker_orphan_count", 0)),
        "structurally_consistent": bool(run_state.get("blocker_structurally_consistent", True)),
        "verdict_blocked": _extract_final_verdict(run_state) == "blocked",
    }


def _extract_pr_readiness(run_state: dict[str, Any]) -> dict[str, Any] | None:
    """
    Resolve PR readiness with deterministic priority:
      1. top-level 'pr_readiness' str  (Phase 3 compact contract) — wrapped as {"status": value}
      2. top-level 'pr_readiness' dict (legacy dict form)
      3. artifact named 'pr_readiness_verdict' in artifact_records — V1 shell fallback
      4. None

    In V1 shell mode the pr_readiness_verdict artifact is a stub record
    (status='present', payload={'produced_by': step_id}). Callers are responsible
    for checking whether the returned payload is substantive.
    """
    top_level = run_state.get("pr_readiness")

    # 1. Phase 3 compact string — wrap into dict for uniform return type
    if isinstance(top_level, str):
        return {"status": top_level}

    # 2. Legacy dict form
    if isinstance(top_level, dict):
        return top_level

    # 3. Artifact named 'pr_readiness_verdict'
    artifact_map = _extract_artifact_map(run_state)
    pr_artifact = artifact_map.get("pr_readiness_verdict")
    if pr_artifact is not None:
        return pr_artifact

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_run_state(path: str | Path | None = None) -> dict[str, Any]:
    """
    Load and minimally validate the persisted governance run-state JSON.

    If path is None, uses the default state path (governance_run_state.json in
    the project working directory, as defined by state_store.DEFAULT_STATE_PATH).

    Returns the parsed run-state as a plain dict.

    Raises:
        RunStateNotFoundError   – file does not exist or cannot be read
        RunStateDecodeError     – file exists but contains invalid JSON
        RunStateStructureError  – JSON is valid but fails minimal structure check
    """
    resolved = Path(path) if path is not None else _default_run_state_path()

    if not resolved.exists():
        raise RunStateNotFoundError(
            f"Governance run-state file not found: {resolved}. "
            "Run 'python -m governance.dag_runner.cli --write-state' to generate it."
        )

    if not resolved.is_file():
        raise RunStateNotFoundError(
            f"Governance run-state path is not a regular file: {resolved}."
        )

    try:
        raw = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise RunStateNotFoundError(
            f"Could not read governance run-state file {resolved}: {exc}"
        ) from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RunStateDecodeError(
            f"Invalid JSON in governance run-state file {resolved}: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise RunStateStructureError(
            f"Governance run-state JSON root must be an object, got "
            f"{type(payload).__name__}."
        )

    _validate_minimal_structure(payload)
    return payload


def get_final_verdict(path: str | Path | None = None) -> str | None:
    """
    Return the final governance verdict status string.

    Resolution order:
      1. top-level 'final_verdict'   (executor-recorded, post-run)
      2. top-level 'verdict_status'  (computation-time, pre-execution)
      3. None — if both are absent in an otherwise structurally valid payload

    Does not invent a verdict.
    """
    run_state = load_run_state(path)
    return _extract_final_verdict(run_state)


def has_unresolved_blocks(path: str | Path | None = None) -> bool:
    """
    Return True if unresolved blocking conditions are present in run state.

    Inspects explicit blocker fields rather than inferring from verdict alone.

    Logic:
      True  — blocker_unknown_reference_count > 0 (explicit unresolved references)
      True  — resolved verdict is 'blocked' (authoritative evidence of unresolved state)
      False — blocker structure is present and clean (no unknowns, verdict not blocked)

    Raises RunStateStructureError when no blocker structure and no verdict are
    available, refusing to silently return False on missing data.
    """
    run_state = load_run_state(path)
    info = _extract_blocking_conditions(run_state)

    if info["unknown_reference_count"] > 0:
        return True

    if info["verdict_blocked"]:
        return True

    return False


def get_required_artifact(
    name: str,
    path: str | Path | None = None,
) -> dict[str, Any] | None:
    """
    Return the artifact record for the named artifact from persisted run state.

    Searches the 'artifact_records' collection in the run-state payload.
    Returns the full artifact record dict (name, producer_step, status, payload)
    or None if the artifact is not present.

    Does not synthesize an artifact record.
    """
    run_state = load_run_state(path)
    artifact_map = _extract_artifact_map(run_state)
    return artifact_map.get(name)


def get_recorded_trace_events(path: str | Path | None = None) -> list[dict[str, Any]]:
    """
    Return the persisted execution trace event list.

    Returns an empty list when the run state is structurally valid and
    execution_trace is explicitly empty (e.g. a partial or pre-execution state).

    Raises RunStateStructureError if execution_trace is absent from an otherwise
    complete payload — _validate_minimal_structure requires this key, so absence
    after a successful load indicates a corrupt payload.
    """
    run_state = load_run_state(path)
    trace = run_state.get("execution_trace")

    if trace is None:
        # Should be caught by _validate_minimal_structure; surface explicitly here.
        raise RunStateStructureError(
            "Run-state payload is missing 'execution_trace' after structural validation. "
            "The payload may be corrupt."
        )

    return list(trace)


def get_pr_readiness(path: str | Path | None = None) -> dict[str, Any] | None:
    """
    Return the PR readiness object if present.

    Resolution order:
      1. top-level 'pr_readiness' str  (Phase 3) — returned as {"status": value}
      2. top-level 'pr_readiness' dict (legacy)
      3. artifact named 'pr_readiness_verdict' in artifact_records
      4. None

    In V1 shell mode the returned artifact record will be a stub with
    payload={'produced_by': step_id}. Callers must inspect the payload
    to determine whether it carries substantive readiness data.

    Does not invent readiness fields.
    """
    run_state = load_run_state(path)
    return _extract_pr_readiness(run_state)
