"""
artifacts.py — Artifact policy and query module for the Mr. Ripley governance DAG runner.

This module is the single place for answering artifact questions:
  - Which artifacts are declared by the spec?
  - Which are unconditionally required?
  - Which are present in a run state?
  - Which required artifacts are missing?
  - What compact summary should verdict and hooks consume?

Design rules
------------
- Read-only and policy-only. No disk I/O, no run-state mutation, no execution.
- Fail closed: malformed inputs raise explicit exceptions rather than returning
  misleading success values.
- Supports both typed GovernanceRunState and persisted-json dict payloads.
- Deterministic: list-returning functions return sorted output.
- Standard library only.

Required-artifact policy (V1)
------------------------------
An artifact is unconditionally required in V1 when it is declared in the spec
with `ArtifactSpec.required = True`.  The assembler derives this flag directly
from the `conditional` field in artifacts.yaml:

    required = not conditional

This is the "more direct artifact declaration/ownership contract" referenced by
the V1 design spec.  It accurately encodes the project's intent: artifacts marked
`conditional: true` are only needed under specific predicate conditions at the PR
gate, whereas `conditional: false` artifacts must always be produced.

An alternative derivation is step-based: treat outputs of workflow steps that
have no `condition` and no `skip_if` as required.  This approach is implemented
in `_step_outputs_are_unconditionally_required()` for reference, but the
registry-based approach takes precedence because it is more direct and already
encodes the necessary distinctions (e.g. `doc_update_plan` is produced by an
unconditional step but declared `conditional: true` in the registry because it is
only required at the PR gate when a doc-update predicate is active).

Input normalization
-------------------
All public functions accept either a typed GovernanceRunState or a persisted-json
dict payload.  `_extract_artifact_records()` normalises both into a uniform list
of artifact record dicts before any policy logic runs.
"""
from __future__ import annotations

from typing import Any

from governance.dag_runner.models import (
    ArtifactRecord,
    AssembledWorkflowSpec,
    GovernanceRunState,
    WorkflowStep,
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ArtifactPolicyError(Exception):
    """Base exception for artifact-policy failures."""


class ArtifactStructureError(ArtifactPolicyError):
    """Raised when a run-state or spec payload is structurally insufficient."""


# Valid artifact status values (mirrors ArtifactStatus from models.py).
_PRESENT_STATUS = "present"
_VALID_STATUSES = frozenset({"present", "missing", "blocked", "stale"})


# ---------------------------------------------------------------------------
# Private helpers — input normalisation
# ---------------------------------------------------------------------------


def _extract_artifact_records(
    run_state: GovernanceRunState | dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Normalise a run-state input into a flat list of artifact record dicts.

    For typed GovernanceRunState:
      - reads .artifacts (dict[str, ArtifactRecord])
      - converts each ArtifactRecord to a plain dict

    For persisted dict payloads:
      - reads the 'artifact_records' key (list of dicts)

    Raises ArtifactStructureError if the payload is malformed.
    """
    if isinstance(run_state, GovernanceRunState):
        records = []
        for rec in run_state.artifacts.values():
            if not isinstance(rec, ArtifactRecord):
                raise ArtifactStructureError(
                    f"Expected ArtifactRecord in GovernanceRunState.artifacts, "
                    f"got {type(rec).__name__}."
                )
            records.append({
                "name": rec.name,
                "producer_step": rec.producer_step,
                "status": rec.status,
                "payload": dict(rec.payload),
            })
        return records

    if not isinstance(run_state, dict):
        raise ArtifactStructureError(
            f"run_state must be a GovernanceRunState or dict, got {type(run_state).__name__}."
        )

    raw_records = run_state.get("artifact_records")
    if raw_records is None:
        raise ArtifactStructureError(
            "Persisted run-state dict is missing the 'artifact_records' key."
        )
    if not isinstance(raw_records, list):
        raise ArtifactStructureError(
            f"'artifact_records' must be a list, got {type(raw_records).__name__}."
        )
    return raw_records


def _artifact_record_map(
    run_state: GovernanceRunState | dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """
    Return a name-keyed dict of artifact record dicts from the run state.

    Each record is guaranteed to have at least a 'name' key.
    Records that are not dicts or lack 'name' are skipped (defensive).
    """
    records = _extract_artifact_records(run_state)
    return {
        rec["name"]: rec
        for rec in records
        if isinstance(rec, dict) and "name" in rec
    }


def _artifact_status_is_present(record: dict[str, Any]) -> bool:
    """
    Return True only when the artifact status is explicitly 'present'.

    Conservative: 'missing', 'blocked', and 'stale' all return False.
    A missing or unexpected status also returns False.
    """
    status = record.get("status")
    return status == _PRESENT_STATUS


def _declared_artifact_names(spec: AssembledWorkflowSpec) -> set[str]:
    """Return the set of all declared artifact names from the spec."""
    return set(spec.artifacts.keys())


def _step_outputs_are_unconditionally_required(step: WorkflowStep) -> bool:
    """
    Return True if this step's outputs should be treated as unconditionally
    required by the step-based V1 heuristic: the step has no `condition` and
    no `skip_if` gating.

    This helper is provided for reference and cross-validation.  The primary
    required-artifact source is ArtifactSpec.required (registry-declared).
    """
    return step.condition is None and step.skip_if is None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def artifact_exists(
    run_state: GovernanceRunState | dict[str, Any],
    name: str,
) -> bool:
    """
    Return True if the named artifact is present and usable in the run state.

    V1 semantics:
      - the artifact record must exist in the run state
      - the artifact status must be 'present'
      - 'missing', 'blocked', and 'stale' are not considered present

    Raises ArtifactStructureError if the run-state shape is malformed.
    """
    record_map = _artifact_record_map(run_state)
    record = record_map.get(name)
    if record is None:
        return False
    return _artifact_status_is_present(record)


def get_required_artifacts(spec: AssembledWorkflowSpec) -> list[str]:
    """
    Return the sorted list of unconditionally required artifact names for this spec.

    Policy (V1):
      An artifact is unconditionally required when ArtifactSpec.required is True.
      The assembler derives this from the `conditional` field in artifacts.yaml:
          required = not conditional

    Artifacts with conditional: true (e.g. doc_update_plan, invariance_verdict,
    verification_matrix_delta) are excluded.  They are required only when specific
    runtime predicates are active, which is beyond V1 scope here.

    Returns a sorted list for determinism.
    """
    return sorted(
        name
        for name, artifact_spec in spec.artifacts.items()
        if artifact_spec.required
    )


def get_missing_required_artifacts(
    spec: AssembledWorkflowSpec,
    run_state: GovernanceRunState | dict[str, Any],
) -> list[str]:
    """
    Return the sorted list of required artifact names absent from the run state.

    An artifact counts as absent when artifact_exists() returns False for it.
    An empty list means all required artifacts are accounted for.

    Raises ArtifactStructureError if the run-state shape is malformed.
    """
    required = get_required_artifacts(spec)
    return sorted(name for name in required if not artifact_exists(run_state, name))


def build_artifact_summary(
    spec: AssembledWorkflowSpec,
    run_state: GovernanceRunState | dict[str, Any],
) -> dict[str, Any]:
    """
    Return a compact machine-readable artifact summary.

    Suitable for consumption by verdict logic, hook bridge, and future CI gates.

    Fields
    ------
    declared_artifacts        : int   — total artifacts declared in spec
    recorded_artifacts        : int   — total artifacts in run state (any status)
    required_artifacts        : list  — sorted required artifact names
    required_artifact_count   : int   — len(required_artifacts)
    present_required_artifacts: list  — required names that are present
    missing_required_artifacts: list  — required names that are absent/non-present
    required_outputs_present  : bool  — all required artifacts are present
    artifact_status_counts    : dict  — count per status value across all recorded artifacts

    Additional diagnostic fields
    ----------------------------
    all_recorded_artifact_names      : sorted list of all artifact names in run state
    declared_but_unrecorded_artifacts: declared in spec but absent from run state
    recorded_but_undeclared_artifacts: in run state but not declared in spec

    Raises ArtifactStructureError if the run-state shape is malformed.
    """
    required = get_required_artifacts(spec)
    record_map = _artifact_record_map(run_state)
    declared = _declared_artifact_names(spec)
    recorded = set(record_map.keys())

    present_required = sorted(
        name for name in required if _artifact_status_is_present(record_map.get(name, {}))
    )
    missing_required = sorted(name for name in required if name not in present_required)

    # Status count across all recorded artifacts
    status_counts: dict[str, int] = {s: 0 for s in sorted(_VALID_STATUSES)}
    for rec in record_map.values():
        status = rec.get("status", "")
        if status in _VALID_STATUSES:
            status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "declared_artifacts": len(spec.artifacts),
        "recorded_artifacts": len(record_map),
        "required_artifacts": required,
        "required_artifact_count": len(required),
        "present_required_artifacts": present_required,
        "missing_required_artifacts": missing_required,
        "required_outputs_present": len(missing_required) == 0,
        "artifact_status_counts": status_counts,
        # Diagnostic fields
        "all_recorded_artifact_names": sorted(recorded),
        "declared_but_unrecorded_artifacts": sorted(declared - recorded),
        "recorded_but_undeclared_artifacts": sorted(recorded - declared),
    }
