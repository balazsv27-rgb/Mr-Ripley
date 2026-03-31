from __future__ import annotations

from dataclasses import dataclass, field

from governance.dag_runner.models import AssembledWorkflowSpec
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