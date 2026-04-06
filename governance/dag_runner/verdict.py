from __future__ import annotations

from dataclasses import dataclass, field

from governance.dag_runner.blockers import BlockerSummary
from governance.dag_runner.models import AssembledWorkflowSpec, GovernanceRunState
from governance.dag_runner.validator import ValidationResult


class VerdictError(RuntimeError):
    """Raised when verdict computation fails."""


@dataclass(frozen=True)
class GovernanceVerdict:
    status: str
    reasons: list[str] = field(default_factory=list)

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"

    @property
    def is_blocked(self) -> bool:
        return self.status == "blocked"

    @property
    def is_review_only(self) -> bool:
        return self.status == "review_only"


def compute_structural_verdict(
    validation_result: ValidationResult,
    blocker_summary: BlockerSummary,
) -> GovernanceVerdict:
    """
    Structural verdict based on workflow validation and blocker registry structure.

    Does not consult runtime state.
    """
    reasons: list[str] = []

    if not validation_result.is_valid:
        reasons.append(
            f"Validation failed with {len(validation_result.issues)} issue(s)."
        )
        return GovernanceVerdict(status="blocked", reasons=reasons)

    if blocker_summary.has_unknown_references:
        reasons.append(
            f"Unknown blocker references detected: {len(blocker_summary.unknown_references)}."
        )
        return GovernanceVerdict(status="blocked", reasons=reasons)

    if blocker_summary.has_orphans:
        reasons.append(
            f"Declared blocker(s) not referenced by any planned step: {len(blocker_summary.orphan_blockers)}."
        )
        return GovernanceVerdict(status="review_only", reasons=reasons)

    if not blocker_summary.is_structurally_consistent:
        reasons.append("Blocker summary is not structurally consistent.")
        return GovernanceVerdict(status="review_only", reasons=reasons)

    reasons.append("Validation passed and blocker structure is consistent.")
    return GovernanceVerdict(status="ready", reasons=reasons)


def compute_verdict(
    validation_result: ValidationResult,
    blocker_summary: BlockerSummary,
) -> GovernanceVerdict:
    """Backward-compatible structural verdict. Delegates to compute_structural_verdict."""
    return compute_structural_verdict(validation_result, blocker_summary)


def _is_workflow_complete(run_state: GovernanceRunState) -> bool:
    return any(e.event_type == "run_completed" for e in run_state.execution_trace)


def compute_runtime_verdict(
    validation_result: ValidationResult,
    blocker_summary: BlockerSummary,
    run_state: GovernanceRunState,
    artifact_summary: dict,
    spec: AssembledWorkflowSpec,
) -> GovernanceVerdict:
    """
    Runtime-aware verdict: extends structural checks with execution state.

    Evaluation order:
    1. Structural invalidity → blocked
    2. Unknown structural blocker refs → blocked
    3. Fatal unresolved runtime blockers → blocked
    4. Non-fatal unresolved runtime blockers → review_only
    5. Required outputs not present → review_only
    6. Workflow not complete (no run_completed trace event) → review_only
    7. Structural orphan blockers → review_only
    8. All clean → ready
    """
    from governance.dag_runner.blockers import analyze_runtime_blockers

    reasons: list[str] = []

    # 1. Structural invalidity
    if not validation_result.is_valid:
        reasons.append(
            f"Validation failed with {len(validation_result.issues)} issue(s)."
        )
        return GovernanceVerdict(status="blocked", reasons=reasons)

    # 2. Unknown structural blocker refs
    if blocker_summary.has_unknown_references:
        reasons.append(
            f"Unknown blocker references detected: {len(blocker_summary.unknown_references)}."
        )
        return GovernanceVerdict(status="blocked", reasons=reasons)

    # 3. Fatal unresolved runtime blockers
    runtime_summary = analyze_runtime_blockers(run_state, spec)
    if runtime_summary.has_fatal_unresolved:
        reasons.append(
            f"Unresolved fatal blocker(s): {runtime_summary.fatal_unresolved_blockers}."
        )
        return GovernanceVerdict(status="blocked", reasons=reasons)

    # 4. Non-fatal unresolved runtime blockers
    if runtime_summary.has_unresolved:
        reasons.append(
            f"Unresolved non-fatal blocker(s): {runtime_summary.unresolved_blockers}."
        )
        return GovernanceVerdict(status="review_only", reasons=reasons)

    # 5. Required outputs not present
    if not artifact_summary.get("required_outputs_present", False):
        missing = artifact_summary.get("missing_required_artifacts", [])
        reasons.append(f"Required artifacts not present: {missing}.")
        return GovernanceVerdict(status="review_only", reasons=reasons)

    # 6. Workflow not complete
    if not _is_workflow_complete(run_state):
        reasons.append("Workflow did not complete (no run_completed trace event).")
        return GovernanceVerdict(status="review_only", reasons=reasons)

    # 7. Structural orphan blockers
    if blocker_summary.has_orphans:
        reasons.append(
            f"Declared blocker(s) not referenced by any planned step: {len(blocker_summary.orphan_blockers)}."
        )
        return GovernanceVerdict(status="review_only", reasons=reasons)

    # 8. All clean
    reasons.append(
        "Validation passed, all required artifacts present, and no unresolved blockers."
    )
    return GovernanceVerdict(status="ready", reasons=reasons)
