from governance.dag_runner.loader import load_workflow_packages


def test_loader_loads_root_workflow_and_packages() -> None:
    loaded = load_workflow_packages()

    assert loaded.manifest.workflow_name == "mr-ripley-governance-orchestration"
    assert len(loaded.packages) == 13
    assert loaded.workflow_path.name == "system-orchestration.yaml"