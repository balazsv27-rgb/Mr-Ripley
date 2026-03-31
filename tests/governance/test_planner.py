from governance.dag_runner.assembler import assemble_workflow_spec
from governance.dag_runner.loader import load_workflow_packages
from governance.dag_runner.planner import build_execution_plan
from governance.dag_runner.validator import validate_or_raise


def test_planner_builds_topological_execution_plan() -> None:
    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    validate_or_raise(spec)

    plan = build_execution_plan(spec)

    assert plan.workflow_name == "mr-ripley-governance-orchestration"
    assert len(plan.ordered_steps) == 18
    assert plan.ordered_step_ids[:5] == [
        "load-context",
        "classify-claims",
        "normalize-terminology",
        "route-claims-by-role",
        "phase-check",
    ]