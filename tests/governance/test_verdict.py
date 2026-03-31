from governance.dag_runner.assembler import assemble_workflow_spec
from governance.dag_runner.blockers import analyze_blockers
from governance.dag_runner.loader import load_workflow_packages
from governance.dag_runner.planner import build_execution_plan
from governance.dag_runner.validator import validate_workflow_spec
from governance.dag_runner.verdict import compute_verdict


def test_verdict_is_ready_for_current_workflow() -> None:
    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    validation = validate_workflow_spec(spec)
    plan = build_execution_plan(spec)
    blockers = analyze_blockers(spec, plan)

    verdict = compute_verdict(validation, blockers)

    assert verdict.status == "ready"
    assert verdict.reasons == [
        "Validation passed and blocker structure is consistent."
    ]