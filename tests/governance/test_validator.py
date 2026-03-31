from governance.dag_runner.assembler import assemble_workflow_spec
from governance.dag_runner.loader import load_workflow_packages
from governance.dag_runner.validator import validate_workflow_spec


def test_validator_accepts_current_workflow() -> None:
    loaded = load_workflow_packages()
    spec = assemble_workflow_spec(loaded)
    result = validate_workflow_spec(spec)

    assert result.is_valid is True
    assert result.issues == []