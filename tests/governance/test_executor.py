from governance.dag_runner.assembler import assemble_workflow_spec
from governance.dag_runner.blockers import analyze_blockers
from governance.dag_runner.executor import execute_plan
from governance.dag_runner.loader import load_workflow_packages
from governance.dag_runner.planner import build_execution_plan
from governance.dag_runner.validator import validate_workflow_spec
from governance.dag_runner.verdict import compute_verdict


def test_executor_records_v1_shell_run_state() -> None:
    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    validation = validate_workflow_spec(spec)
    plan = build_execution_plan(spec)
    blockers = analyze_blockers(spec, plan)
    verdict = compute_verdict(validation, blockers)

    result = execute_plan(spec, plan, verdict_status=verdict.status)
    run_state = result.run_state

    assert run_state.final_verdict == "ready"
    assert len(run_state.node_results) == 18
    assert len(run_state.execution_trace) == 38
    assert len(run_state.artifacts) == 19

    assert "load-context" in run_state.node_results
    assert "pre-pr-governance-readiness" in run_state.node_results

    assert run_state.node_results["load-context"].status == "PASS"
    assert run_state.node_results["pre-pr-governance-readiness"].status == "PASS"