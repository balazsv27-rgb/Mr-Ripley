from __future__ import annotations

from dataclasses import dataclass, field

from governance.dag_runner.models import AssembledWorkflowSpec, WorkflowStep


class PlannerError(RuntimeError):
    """Raised when execution planning fails."""


@dataclass(frozen=True)
class PlannedNode:
    """One node in the planned execution order."""

    step_id: str
    component: str
    depends_on: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExecutionPlan:
    """Topologically ordered workflow execution plan."""

    workflow_name: str
    ordered_steps: list[PlannedNode] = field(default_factory=list)

    @property
    def ordered_step_ids(self) -> list[str]:
        return [node.step_id for node in self.ordered_steps]


def _build_dependency_graph(spec: AssembledWorkflowSpec) -> dict[str, list[str]]:
    """
    Build a step -> dependency list graph from the assembled spec.
    """
    graph: dict[str, list[str]] = {}

    for step_id, step in spec.workflow_steps.items():
        graph[step_id] = list(step.depends_on)

    return graph


def _topological_sort(graph: dict[str, list[str]]) -> list[str]:
    """
    Kahn-style topological sort.

    Graph format:
      node -> list of dependency nodes
    """
    all_nodes = set(graph.keys())

    for deps in graph.values():
        all_nodes.update(deps)

    indegree: dict[str, int] = {node: 0 for node in all_nodes}
    reverse_edges: dict[str, list[str]] = {node: [] for node in all_nodes}

    for node, deps in graph.items():
        indegree[node] = len(deps)
        for dep in deps:
            reverse_edges.setdefault(dep, []).append(node)

    ready = sorted([node for node, degree in indegree.items() if degree == 0])
    ordered: list[str] = []

    while ready:
        current = ready.pop(0)
        ordered.append(current)

        for dependent in reverse_edges.get(current, []):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
                ready.sort()

    if len(ordered) != len(all_nodes):
        unresolved = sorted(node for node, degree in indegree.items() if degree > 0)
        raise PlannerError(
            f"Topological sort failed; unresolved nodes remain: {unresolved}"
        )

    return ordered


def _build_planned_nodes(
    ordered_ids: list[str],
    workflow_steps: dict[str, WorkflowStep],
) -> list[PlannedNode]:
    """
    Convert ordered step ids into PlannedNode objects.

    Any ordered node not present in workflow_steps is ignored.
    In practice, validator should already guarantee consistency.
    """
    nodes: list[PlannedNode] = []

    for step_id in ordered_ids:
        step = workflow_steps.get(step_id)
        if step is None:
            continue

        nodes.append(
            PlannedNode(
                step_id=step_id,
                component=step.component,
                depends_on=list(step.depends_on),
            )
        )

    return nodes


def build_execution_plan(spec: AssembledWorkflowSpec) -> ExecutionPlan:
    """
    Build a topologically ordered execution plan from a validated workflow spec.
    """
    if not spec.workflow_steps:
        raise PlannerError("Cannot build execution plan: no workflow steps available.")

    graph = _build_dependency_graph(spec)
    ordered_ids = _topological_sort(graph)
    ordered_nodes = _build_planned_nodes(ordered_ids, spec.workflow_steps)

    if not ordered_nodes:
        raise PlannerError("Execution plan is empty after planning.")

    return ExecutionPlan(
        workflow_name=spec.manifest.workflow_name,
        ordered_steps=ordered_nodes,
    )