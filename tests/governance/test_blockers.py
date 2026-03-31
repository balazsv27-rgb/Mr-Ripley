from governance.dag_runner.assembler import assemble_workflow_spec
from governance.dag_runner.blockers import analyze_blockers
from governance.dag_runner.loader import load_workflow_packages
from governance.dag_runner.planner import build_execution_plan
from governance.dag_runner.validator import validate_or_raise


def test_blocker_analysis_matches_current_workflow() -> None:
    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    validate_or_raise(spec)
    plan = build_execution_plan(spec)

    summary = analyze_blockers(spec, plan)

    assert len(summary.declared_blockers) == 12
    assert len(summary.referenced_blockers) == 17
    assert len(summary.orphan_blockers) == 0
    assert len(summary.unknown_references) == 0
    assert summary.is_structurally_consistent is True