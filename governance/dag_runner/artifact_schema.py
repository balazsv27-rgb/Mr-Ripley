"""
artifact_schema.py — Artifact schema validation for backend-produced outputs.

V2B validates structural schema conformance of artifact payloads before
recording them in run_state.  Semantic validation is deferred.

Validation rules (V2B scope):
  1. Payload must be a non-empty dict.
  2. ``produced_by`` key must be present and match the producing step name.
  3. No forbidden envelope-level keys (``artifact``, ``session``, ``timestamp``).
  4. Artifact name must be in the step's declared ``outputs``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from governance.dag_runner.models import (
    AssembledWorkflowSpec,
    WorkflowStep,
)


class ArtifactSchemaError(RuntimeError):
    """Raised when artifact schema validation encounters an internal error."""


@dataclass(frozen=True)
class ArtifactSchemaViolation:
    """One schema violation found during artifact validation."""

    artifact_name: str
    violation: str
    detail: dict[str, Any] = field(default_factory=dict)


# Keys that belong in the artifact envelope (artifact_writer.py) and
# MUST NOT appear in the backend-produced payload dict.
_FORBIDDEN_ENVELOPE_KEYS: frozenset[str] = frozenset({
    "artifact",
    "session",
    "timestamp",
})


def validate_artifact_output(
    artifact_name: str,
    payload: Any,
    step: WorkflowStep,
    spec: AssembledWorkflowSpec,
) -> list[ArtifactSchemaViolation]:
    """Validate a single backend-produced artifact payload.

    Returns an empty list when the payload is valid.
    Returns one ``ArtifactSchemaViolation`` per detected issue.
    """
    violations: list[ArtifactSchemaViolation] = []

    # 1. Type constraint: payload must be a dict
    if not isinstance(payload, dict):
        violations.append(ArtifactSchemaViolation(
            artifact_name=artifact_name,
            violation="payload_not_dict",
            detail={"actual_type": type(payload).__name__},
        ))
        return violations  # cannot check further

    # 2. Non-empty
    if not payload:
        violations.append(ArtifactSchemaViolation(
            artifact_name=artifact_name,
            violation="payload_empty",
        ))
        return violations  # cannot check keys

    # 3. produced_by present and matching
    if "produced_by" not in payload:
        violations.append(ArtifactSchemaViolation(
            artifact_name=artifact_name,
            violation="missing_produced_by",
        ))
    elif payload["produced_by"] != step.name:
        violations.append(ArtifactSchemaViolation(
            artifact_name=artifact_name,
            violation="produced_by_mismatch",
            detail={
                "expected": step.name,
                "actual": payload["produced_by"],
            },
        ))

    # 4. No forbidden envelope keys
    forbidden_present = _FORBIDDEN_ENVELOPE_KEYS & set(payload.keys())
    if forbidden_present:
        violations.append(ArtifactSchemaViolation(
            artifact_name=artifact_name,
            violation="forbidden_envelope_keys",
            detail={"keys": sorted(forbidden_present)},
        ))

    # 5. Artifact name must be in step's declared outputs
    if artifact_name not in step.outputs:
        violations.append(ArtifactSchemaViolation(
            artifact_name=artifact_name,
            violation="undeclared_artifact",
            detail={
                "declared_outputs": list(step.outputs),
            },
        ))

    return violations
