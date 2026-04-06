from __future__ import annotations

from dataclasses import dataclass, field

from governance.dag_runner.models import AssembledWorkflowSpec, GovernanceRunState
from governance.dag_runner.planner import ExecutionPlan


class BlockerError(RuntimeError):
    """Raised when blocker analysis fails."""


@dataclass(frozen=True)
class BlockerReference:
    blocker_id: str
    raised_by_step: str


@dataclass(frozen=True)
class BlockerSummary:
    declared_blockers: list[str] = field(default_factory=list)
    referenced_blockers: list[BlockerReference] = field(default_factory=list)
    orphan_blockers: list[str] = field(default_factory=list)
    unknown_references: list[BlockerReference] = field(default_factory=list)

    @property
    def has_orphans(self) -> bool:
        return len(self.orphan_blockers) > 0

    @property
    def has_unknown_references(self) -> bool:
        return len(self.unknown_references) > 0

    @property
    def is_structurally_consistent(self) -> bool:
        return not self.has_orphans and not self.has_unknown_references


def _collect_declared_blockers(spec: AssembledWorkflowSpec) -> list[str]:
    return sorted(spec.blocking_conditions.keys())


def _collect_referenced_blockers(
    spec: AssembledWorkflowSpec,
    plan: ExecutionPlan,
) -> list[BlockerReference]:
    references: list[BlockerReference] = []

    for node in plan.ordered_steps:
        step = spec.workflow_steps.get(node.step_id)
        if step is None:
            raise BlockerError(
                f"Planned step '{node.step_id}' not found in workflow_steps."
            )

        for blocker_id in step.raises:
            references.append(
                BlockerReference(
                    blocker_id=blocker_id,
                    raised_by_step=node.step_id,
                )
            )

    return references


@dataclass(frozen=True)
class RuntimeBlockerSummary:
    """Summary of runtime blocking events recorded in a GovernanceRunState."""

    raised_blockers: list[str]
    unresolved_blockers: list[str]
    fatal_unresolved_blockers: list[str]
    raised_by_step: dict[str, list[str]]
    total_raised: int
    total_unresolved: int
    total_fatal_unresolved: int
    has_unresolved: bool
    has_fatal_unresolved: bool


def analyze_blockers(
    spec: AssembledWorkflowSpec,
    plan: ExecutionPlan,
) -> BlockerSummary:
    declared = _collect_declared_blockers(spec)
    declared_set = set(declared)

    referenced = _collect_referenced_blockers(spec, plan)

    unknown_references = [
        ref for ref in referenced if ref.blocker_id not in declared_set
    ]

    referenced_ids = {ref.blocker_id for ref in referenced}
    orphan_blockers = sorted(blocker_id for blocker_id in declared if blocker_id not in referenced_ids)

    return BlockerSummary(
        declared_blockers=declared,
        referenced_blockers=referenced,
        orphan_blockers=orphan_blockers,
        unknown_references=unknown_references,
    )


def analyze_runtime_blockers(
    run_state: GovernanceRunState,
    spec: AssembledWorkflowSpec,
) -> RuntimeBlockerSummary:
    """
    Analyze runtime blocking events recorded in run_state against the declared
    blocking conditions in spec.

    Fails closed: raises BlockerError if any recorded event references a
    blocking_id not declared in spec.blocking_conditions.
    """
    registry = spec.blocking_conditions
    events = run_state.blocking_conditions

    for event in events:
        if event.blocking_id not in registry:
            raise BlockerError(
                f"Unknown runtime blocker ID: '{event.blocking_id}'. "
                f"Must be declared in the workflow spec."
            )

    raised_by_step: dict[str, list[str]] = {}
    for event in events:
        step_list = raised_by_step.setdefault(event.raised_by, [])
        if event.blocking_id not in step_list:
            step_list.append(event.blocking_id)

    raised_blockers = sorted({event.blocking_id for event in events})

    unresolved_set = {event.blocking_id for event in events if not event.resolved}
    unresolved_blockers = sorted(unresolved_set)

    fatal_unresolved_blockers = sorted(
        bid for bid in unresolved_set if registry[bid].halts_workflow
    )

    return RuntimeBlockerSummary(
        raised_blockers=raised_blockers,
        unresolved_blockers=unresolved_blockers,
        fatal_unresolved_blockers=fatal_unresolved_blockers,
        raised_by_step=raised_by_step,
        total_raised=len(raised_blockers),
        total_unresolved=len(unresolved_blockers),
        total_fatal_unresolved=len(fatal_unresolved_blockers),
        has_unresolved=len(unresolved_blockers) > 0,
        has_fatal_unresolved=len(fatal_unresolved_blockers) > 0,
    )


def has_unresolved_fatal_blocks(
    run_state: GovernanceRunState,
    spec: AssembledWorkflowSpec,
) -> bool:
    """Return True if any unresolved runtime blocking event is fatal (halts_workflow=True)."""
    return analyze_runtime_blockers(run_state, spec).has_fatal_unresolved