from governance.dag_runner.assembler import assemble_workflow_spec
from governance.dag_runner.loader import load_workflow_packages


def test_assembler_builds_typed_spec() -> None:
    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)

    assert spec.manifest.workflow_name == "mr-ripley-governance-orchestration"
    assert len(spec.workflow_steps) == 18
    assert len(spec.skills) == 13
    assert len(spec.artifacts) == 19
    assert len(spec.blocking_conditions) == 12
    assert len(spec.stage_gates) == 4
    assert len(spec.subagents) == 8