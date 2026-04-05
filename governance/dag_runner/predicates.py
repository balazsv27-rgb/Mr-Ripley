"""
predicates.py — V1 predicate evaluator for the Mr. Ripley governance DAG runner.

This module evaluates structured predicate conditions against a governance run state.
It is the single place for answering predicate questions at runtime.

Design rules
------------
- Fail closed: unsupported or malformed predicates raise explicit exceptions.
- Read-only: does not mutate run state.
- No disk I/O, no YAML parsing, no expression evaluation, no nested boolean algebra.
- Reuses artifact-policy logic from artifacts.py as the canonical artifact query layer.
- Standard library only.
- Deterministic: summary output is sorted for stability.

Supported V1 predicate types
-----------------------------
- artifact_exists         : matched when the named artifact is present in run state
- artifact_missing        : matched when the named artifact is absent from run state
- artifact_field_equals   : matched when artifact exists and a field equals a value
- artifact_field_not_equals: matched when artifact exists and a field does not equal a value

All other predicate types raise UnsupportedPredicateError.

Field resolution policy (for field-based predicates)
------------------------------------------------------
Fields are resolved from artifact record dicts in this order:
  1. record["payload"][field]   — if payload exists and is a dict
  2. record["data"][field]      — if data exists and is a dict
  3. record[field]              — top-level key on the record dict
  4. absent                     — if none of the above resolve

This conservative ordering ensures payload-carried fields take precedence over
top-level metadata, while still supporting both the hook artifact_store envelope
format (which uses "data") and the executor shell format (which uses "payload").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from governance.dag_runner.artifacts import (
    artifact_exists,
    get_artifact_record,
)
from governance.dag_runner.models import GovernanceRunState


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PredicateEvaluationError(Exception):
    """Base exception for predicate evaluation failures."""


class UnsupportedPredicateError(PredicateEvaluationError):
    """Raised when the predicate type is unknown or unsupported in V1."""


class PredicateStructureError(PredicateEvaluationError):
    """Raised when a predicate is malformed or missing required fields."""


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConditionEvaluationResult:
    """
    Result of evaluating a single structured predicate condition.

    Fields
    ------
    predicate_type : str       — the `type` value from the condition dict
    matched        : bool      — True when the predicate's condition is satisfied
    artifact       : str|None  — artifact name referenced by the predicate
    field          : str|None  — field name for field-based predicates; None otherwise
    expected       : Any       — expected value (from predicate); None for existence predicates
    actual         : Any       — actual resolved value; None when artifact/field absent
    detail         : str       — human-readable explanation of the evaluation outcome
    """
    predicate_type: str
    matched: bool
    artifact: str | None
    field: str | None
    expected: Any
    actual: Any
    detail: str


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

# The full set of V1-supported predicate type strings.
_SUPPORTED_TYPES = frozenset({
    "artifact_exists",
    "artifact_missing",
    "artifact_field_equals",
    "artifact_field_not_equals",
})

# Required keys per predicate type (beyond the universal "type" key).
_REQUIRED_KEYS: dict[str, frozenset[str]] = {
    "artifact_exists":          frozenset({"artifact"}),
    "artifact_missing":         frozenset({"artifact"}),
    "artifact_field_equals":    frozenset({"artifact", "field", "value"}),
    "artifact_field_not_equals": frozenset({"artifact", "field", "value"}),
}


def _predicate_type(condition: dict[str, Any]) -> str:
    """
    Extract and validate the predicate `type` string from a condition dict.

    Raises PredicateStructureError if `type` is absent or not a non-empty string.
    Raises UnsupportedPredicateError if the type is not in the V1 supported set.
    """
    if not isinstance(condition, dict):
        raise PredicateStructureError(
            f"Predicate condition must be a dict, got {type(condition).__name__}."
        )
    ptype = condition.get("type")
    if not isinstance(ptype, str) or not ptype.strip():
        raise PredicateStructureError(
            "Predicate condition is missing a non-empty 'type' field."
        )
    if ptype not in _SUPPORTED_TYPES:
        raise UnsupportedPredicateError(
            f"Predicate type '{ptype}' is not supported in V1. "
            f"Supported types: {sorted(_SUPPORTED_TYPES)}."
        )
    return ptype


def _require_keys(condition: dict[str, Any], ptype: str) -> None:
    """
    Assert that all required keys for the given predicate type are present.

    Raises PredicateStructureError listing the missing keys.
    """
    required = _REQUIRED_KEYS.get(ptype, frozenset())
    missing = required - condition.keys()
    if missing:
        raise PredicateStructureError(
            f"Predicate type '{ptype}' is missing required key(s): "
            f"{sorted(missing)}."
        )


def _get_artifact_record(
    run_state: GovernanceRunState | dict[str, Any],
    name: str,
) -> dict[str, Any] | None:
    """
    Return the artifact record dict for the named artifact, or None if absent.

    Delegates to the public artifacts.get_artifact_record() so input handling
    remains in the canonical artifact-policy module.
    """
    return get_artifact_record(run_state, name)


def _extract_field_value(record: dict[str, Any], field_name: str) -> tuple[Any, bool]:
    """
    Resolve a field value from an artifact record dict using the V1 policy order:
      1. record["payload"][field]  — payload dict takes precedence
      2. record["data"][field]     — supports hook artifact_store envelope format
      3. record[field]             — top-level fallback

    Returns (value, found) where found is False when the field is absent
    in all three locations.
    """
    payload = record.get("payload")
    if isinstance(payload, dict) and field_name in payload:
        return payload[field_name], True

    data = record.get("data")
    if isinstance(data, dict) and field_name in data:
        return data[field_name], True

    if field_name in record:
        return record[field_name], True

    return None, False


# ---------------------------------------------------------------------------
# Private per-type evaluators
# ---------------------------------------------------------------------------


def _evaluate_artifact_exists(
    condition: dict[str, Any],
    run_state: GovernanceRunState | dict[str, Any],
) -> ConditionEvaluationResult:
    artifact_name: str = condition["artifact"]
    present = artifact_exists(run_state, artifact_name)
    return ConditionEvaluationResult(
        predicate_type="artifact_exists",
        matched=present,
        artifact=artifact_name,
        field=None,
        expected=None,
        actual=None,
        detail=(
            f"Artifact '{artifact_name}' is present."
            if present
            else f"Artifact '{artifact_name}' is absent or not present."
        ),
    )


def _evaluate_artifact_missing(
    condition: dict[str, Any],
    run_state: GovernanceRunState | dict[str, Any],
) -> ConditionEvaluationResult:
    artifact_name: str = condition["artifact"]
    present = artifact_exists(run_state, artifact_name)
    return ConditionEvaluationResult(
        predicate_type="artifact_missing",
        matched=not present,
        artifact=artifact_name,
        field=None,
        expected=None,
        actual=None,
        detail=(
            f"Artifact '{artifact_name}' is absent (predicate satisfied)."
            if not present
            else f"Artifact '{artifact_name}' is present (predicate not satisfied)."
        ),
    )


def _evaluate_field_equals(
    condition: dict[str, Any],
    run_state: GovernanceRunState | dict[str, Any],
) -> ConditionEvaluationResult:
    artifact_name: str = condition["artifact"]
    field_name: str = condition["field"]
    expected_value: Any = condition["value"]

    record = _get_artifact_record(run_state, artifact_name)
    if record is None or not artifact_exists(run_state, artifact_name):
        return ConditionEvaluationResult(
            predicate_type="artifact_field_equals",
            matched=False,
            artifact=artifact_name,
            field=field_name,
            expected=expected_value,
            actual=None,
            detail=f"Artifact '{artifact_name}' is absent or not present.",
        )

    actual_value, found = _extract_field_value(record, field_name)
    if not found:
        return ConditionEvaluationResult(
            predicate_type="artifact_field_equals",
            matched=False,
            artifact=artifact_name,
            field=field_name,
            expected=expected_value,
            actual=None,
            detail=(
                f"Field '{field_name}' is absent from artifact '{artifact_name}'."
            ),
        )

    matched = actual_value == expected_value
    return ConditionEvaluationResult(
        predicate_type="artifact_field_equals",
        matched=matched,
        artifact=artifact_name,
        field=field_name,
        expected=expected_value,
        actual=actual_value,
        detail=(
            f"Field '{field_name}' equals {expected_value!r}."
            if matched
            else (
                f"Field '{field_name}' expected {expected_value!r}, "
                f"got {actual_value!r}."
            )
        ),
    )


def _evaluate_field_not_equals(
    condition: dict[str, Any],
    run_state: GovernanceRunState | dict[str, Any],
) -> ConditionEvaluationResult:
    artifact_name: str = condition["artifact"]
    field_name: str = condition["field"]
    expected_value: Any = condition["value"]

    record = _get_artifact_record(run_state, artifact_name)
    if record is None or not artifact_exists(run_state, artifact_name):
        return ConditionEvaluationResult(
            predicate_type="artifact_field_not_equals",
            matched=False,
            artifact=artifact_name,
            field=field_name,
            expected=expected_value,
            actual=None,
            detail=f"Artifact '{artifact_name}' is absent or not present.",
        )

    actual_value, found = _extract_field_value(record, field_name)
    if not found:
        return ConditionEvaluationResult(
            predicate_type="artifact_field_not_equals",
            matched=False,
            artifact=artifact_name,
            field=field_name,
            expected=expected_value,
            actual=None,
            detail=(
                f"Field '{field_name}' is absent from artifact '{artifact_name}'."
            ),
        )

    matched = actual_value != expected_value
    return ConditionEvaluationResult(
        predicate_type="artifact_field_not_equals",
        matched=matched,
        artifact=artifact_name,
        field=field_name,
        expected=expected_value,
        actual=actual_value,
        detail=(
            f"Field '{field_name}' is {actual_value!r}, which differs from "
            f"{expected_value!r} (predicate satisfied)."
            if matched
            else (
                f"Field '{field_name}' equals {expected_value!r}; "
                f"predicate requires a different value."
            )
        ),
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_EVALUATORS = {
    "artifact_exists":           _evaluate_artifact_exists,
    "artifact_missing":          _evaluate_artifact_missing,
    "artifact_field_equals":     _evaluate_field_equals,
    "artifact_field_not_equals": _evaluate_field_not_equals,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_condition(
    condition: dict[str, Any],
    run_state: GovernanceRunState | dict[str, Any],
) -> ConditionEvaluationResult:
    """
    Evaluate exactly one structured predicate condition against a run state.

    Steps:
      1. Validate the predicate structure (raises PredicateStructureError /
         UnsupportedPredicateError on failure — fail closed).
      2. Dispatch to the appropriate per-type evaluator.
      3. Return a ConditionEvaluationResult.

    Never mutates run_state.

    Raises
    ------
    PredicateStructureError   — condition is malformed or missing required keys
    UnsupportedPredicateError — condition type is not in V1 supported set
    ArtifactStructureError    — propagated from artifacts.py when run_state is malformed
    """
    ptype = _predicate_type(condition)  # validates type; may raise
    _require_keys(condition, ptype)     # validates required keys; may raise

    evaluator = _EVALUATORS[ptype]
    return evaluator(condition, run_state)


def predicate_matches(
    condition: dict[str, Any],
    run_state: GovernanceRunState | dict[str, Any],
) -> bool:
    """
    Return True if the predicate condition is matched, False otherwise.

    Thin wrapper over evaluate_condition() that returns only .matched.
    All exceptions from evaluate_condition() propagate unchanged.
    """
    return evaluate_condition(condition, run_state).matched


def build_predicate_summary(
    evaluations: list[ConditionEvaluationResult],
) -> dict[str, Any]:
    """
    Return a compact machine-readable summary of a list of predicate evaluations.

    Suitable for executor tracing, persisted diagnostics, and CI gate output.

    Fields
    ------
    total             : int           — total number of evaluations
    matched           : int           — number that matched
    unmatched         : int           — number that did not match
    by_type           : dict[str,int] — evaluation count per predicate type
    matched_by_type   : dict[str,int] — matched count per predicate type
    artifacts_checked : list[str]     — sorted unique artifact names referenced
    failing_predicates: list[dict]    — details for each unmatched predicate

    Each failing predicate entry contains:
      predicate_type, artifact, field, expected, actual, detail
    """
    total = len(evaluations)
    matched_count = sum(1 for e in evaluations if e.matched)

    by_type: dict[str, int] = {}
    matched_by_type: dict[str, int] = {}
    artifacts_checked: set[str] = set()
    failing: list[dict[str, Any]] = []

    for ev in evaluations:
        by_type[ev.predicate_type] = by_type.get(ev.predicate_type, 0) + 1
        if ev.matched:
            matched_by_type[ev.predicate_type] = (
                matched_by_type.get(ev.predicate_type, 0) + 1
            )
        if ev.artifact is not None:
            artifacts_checked.add(ev.artifact)
        if not ev.matched:
            failing.append({
                "predicate_type": ev.predicate_type,
                "artifact": ev.artifact,
                "field": ev.field,
                "expected": ev.expected,
                "actual": ev.actual,
                "detail": ev.detail,
            })

    return {
        "total": total,
        "matched": matched_count,
        "unmatched": total - matched_count,
        "by_type": dict(sorted(by_type.items())),
        "matched_by_type": dict(sorted(matched_by_type.items())),
        "artifacts_checked": sorted(artifacts_checked),
        "failing_predicates": failing,
    }
