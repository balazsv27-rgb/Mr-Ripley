"""Tests for R2-A / R2-A.1: artifact disk-write and required-input validation.

R2-A.1: Before V2 step execution, verify declared input artifacts are present.
R2-A:   After V2 step execution, write artifact envelopes to disk.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from governance.dag_runner.artifact_writer import ArtifactWriterError
from governance.dag_runner.execution_backend import MockExecutionBackend
from governance.dag_runner.executor import execute_plan
from governance.dag_runner.models import (
    ArtifactSpec,
    AssembledWorkflowSpec,
    BlockingCondition,
    ExecutionConfig,
    ManifestSpec,
    WorkflowStep,
)
from governance.dag_runner.planner import ExecutionPlan, PlannedNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_step(
    name: str,
    *,
    outputs: list[str] | None = None,
    inputs: list[str] | None = None,
    raises: list[str] | None = None,
    depends_on: list[str] | None = None,
    component: str = "constitution",
) -> WorkflowStep:
    raw: dict = {}
    if inputs is not None:
        raw["inputs"] = inputs
    return WorkflowStep(
        name=name,
        component=component,
        outputs=outputs or [],
        raises=raises or [],
        depends_on=depends_on or [],
        raw=raw,
    )


def _make_spec(
    steps: dict[str, WorkflowStep],
    *,
    artifacts: dict[str, ArtifactSpec] | None = None,
    blocking_conditions: dict[str, BlockingCondition] | None = None,
) -> AssembledWorkflowSpec:
    return AssembledWorkflowSpec(
        manifest=ManifestSpec(workflow_name="test-artifacts", workflow_version="1.0"),
        workflow_steps=steps,
        artifacts=artifacts or {},
        blocking_conditions=blocking_conditions or {},
    )


def _make_plan(step_ids: list[str], components: dict[str, str] | None = None) -> ExecutionPlan:
    comps = components or {}
    return ExecutionPlan(
        workflow_name="test-artifacts",
        ordered_steps=[
            PlannedNode(
                step_id=sid,
                component=comps.get(sid, "constitution"),
            )
            for sid in step_ids
        ],
    )


def _agent_config() -> ExecutionConfig:
    return ExecutionConfig(mode="agent_execution", request_text="test request")


def _dry_run_config() -> ExecutionConfig:
    return ExecutionConfig(mode="dry_run")


# ---------------------------------------------------------------------------
# R2-A.1: Required-Input Artifact Validation
# ---------------------------------------------------------------------------


class TestRequiredInputValidation:
    """Required-input artifact validation in V2 mode."""

    def test_missing_required_input_fails_step(self) -> None:
        """Step B needs 'alpha_out' which was never produced → FAIL."""
        steps = {
            "step-a": _make_step("step-a", outputs=["alpha_out"]),
            "step-b": _make_step("step-b", inputs=["alpha_out"]),
        }
        artifacts = {
            "alpha_out": ArtifactSpec(name="alpha_out", producer_step="step-a"),
        }
        spec = _make_spec(steps, artifacts=artifacts)
        # Plan only step-b — step-a never runs, so alpha_out is never produced
        plan = _make_plan(["step-b"])
        backend = MockExecutionBackend()

        result = execute_plan(spec, plan, config=_agent_config(), backend=backend)
        assert result.run_state.node_results["step-b"].status == "FAIL"
        assert "alpha_out" in result.run_state.node_results["step-b"].summary

    def test_present_required_input_executes(self) -> None:
        """Step A produces alpha_out, step B needs it → both PASS."""
        steps = {
            "step-a": _make_step("step-a", outputs=["alpha_out"]),
            "step-b": _make_step(
                "step-b", inputs=["alpha_out"], depends_on=["step-a"],
            ),
        }
        artifacts = {
            "alpha_out": ArtifactSpec(name="alpha_out", producer_step="step-a"),
        }
        spec = _make_spec(steps, artifacts=artifacts)
        plan = _make_plan(["step-a", "step-b"])
        backend = MockExecutionBackend()

        result = execute_plan(spec, plan, config=_agent_config(), backend=backend)
        assert result.run_state.node_results["step-a"].status == "PASS"
        assert result.run_state.node_results["step-b"].status == "PASS"

    def test_non_registry_input_skipped(self) -> None:
        """Input 'CLAUDE.md' not in spec.artifacts → no failure."""
        steps = {
            "step-a": _make_step("step-a", inputs=["CLAUDE.md"]),
        }
        spec = _make_spec(steps, artifacts={})  # no artifacts in registry
        plan = _make_plan(["step-a"])
        backend = MockExecutionBackend()

        result = execute_plan(spec, plan, config=_agent_config(), backend=backend)
        assert result.run_state.node_results["step-a"].status == "PASS"

    def test_dry_run_skips_input_validation(self) -> None:
        """Dry-run mode does not check inputs (no artifacts are produced)."""
        steps = {
            "step-a": _make_step("step-a", inputs=["alpha_out"]),
        }
        artifacts = {
            "alpha_out": ArtifactSpec(name="alpha_out", producer_step="other"),
        }
        spec = _make_spec(steps, artifacts=artifacts)
        plan = _make_plan(["step-a"])
        backend = MockExecutionBackend()

        result = execute_plan(spec, plan, config=_dry_run_config(), backend=backend)
        assert result.run_state.node_results["step-a"].status == "PASS"

    def test_missing_input_trace_event(self) -> None:
        """Trace contains 'required_input_missing' event."""
        steps = {
            "step-a": _make_step("step-a", inputs=["alpha_out"]),
        }
        artifacts = {
            "alpha_out": ArtifactSpec(name="alpha_out", producer_step="other"),
        }
        spec = _make_spec(steps, artifacts=artifacts)
        plan = _make_plan(["step-a"])
        backend = MockExecutionBackend()

        result = execute_plan(spec, plan, config=_agent_config(), backend=backend)
        event_types = [e.event_type for e in result.run_state.execution_trace]
        assert "required_input_missing" in event_types

    def test_v1_shell_unaffected(self) -> None:
        """V1 shell mode (backend=None) does not check inputs."""
        steps = {
            "step-a": _make_step("step-a", inputs=["alpha_out"], outputs=["out"]),
        }
        artifacts = {
            "alpha_out": ArtifactSpec(name="alpha_out", producer_step="other"),
        }
        spec = _make_spec(steps, artifacts=artifacts)
        plan = _make_plan(["step-a"])

        result = execute_plan(spec, plan)  # no backend = V1 shell
        assert result.run_state.node_results["step-a"].status == "PASS"

    def test_missing_input_with_halt_on_critical(self) -> None:
        """Missing input on a step with halts_workflow blocker → halt."""
        steps = {
            "step-a": _make_step(
                "step-a",
                inputs=["alpha_out"],
                raises=["fatal_blocker"],
            ),
            "step-b": _make_step("step-b"),
        }
        artifacts = {
            "alpha_out": ArtifactSpec(name="alpha_out", producer_step="other"),
        }
        blocking = {
            "fatal_blocker": BlockingCondition(
                id="fatal_blocker", halts_workflow=True,
            ),
        }
        spec = _make_spec(steps, artifacts=artifacts, blocking_conditions=blocking)
        plan = _make_plan(["step-a", "step-b"])
        backend = MockExecutionBackend()

        result = execute_plan(spec, plan, config=_agent_config(), backend=backend)
        assert result.run_state.node_results["step-a"].status == "FAIL"
        assert result.run_state.node_results["step-b"].status == "SKIP"


# ---------------------------------------------------------------------------
# R2-A: Artifact Disk-Write Integration
# ---------------------------------------------------------------------------


class TestArtifactDiskWrite:
    """Artifact envelope disk-write integration in V2 mode."""

    def test_artifact_envelope_written_to_disk(self) -> None:
        """V2 execution writes envelope files to session artifact_dir."""
        steps = {
            "step-a": _make_step("step-a", outputs=["alpha_out"]),
        }
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = MockExecutionBackend()

        result = execute_plan(
            spec, plan, config=_agent_config(), backend=backend,
        )

        assert result.run_state.node_results["step-a"].status == "PASS"

        # Verify envelope file exists in session directory
        artifact_dir = Path(result.run_state.session_dir) / "artifacts"
        envelope_path = artifact_dir / "alpha_out.json"
        assert envelope_path.is_file()

        # Verify envelope schema matches hook contract
        with envelope_path.open() as f:
            envelope = json.load(f)
        assert set(envelope.keys()) == {
            "artifact", "produced_by", "session", "timestamp", "data",
        }
        assert envelope["artifact"] == "alpha_out"
        assert envelope["produced_by"] == "step-a"

    def test_multiple_artifacts_written(self) -> None:
        """All produced artifacts are written to disk."""
        steps = {
            "step-a": _make_step("step-a", outputs=["out_1", "out_2"]),
        }
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = MockExecutionBackend()

        result = execute_plan(spec, plan, config=_agent_config(), backend=backend)
        artifact_dir = Path(result.run_state.session_dir) / "artifacts"

        assert (artifact_dir / "out_1.json").is_file()
        assert (artifact_dir / "out_2.json").is_file()

    def test_dry_run_no_disk_artifacts(self) -> None:
        """Dry-run mode does NOT write artifact files to disk."""
        steps = {
            "step-a": _make_step("step-a", outputs=["alpha_out"]),
        }
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = MockExecutionBackend()

        result = execute_plan(spec, plan, config=_dry_run_config(), backend=backend)
        artifact_dir = Path(result.run_state.session_dir) / "artifacts"

        # No artifact files should be written (directory exists but is empty)
        assert not list(artifact_dir.iterdir())

    def test_artifact_write_failure_fails_step(self) -> None:
        """ArtifactWriterError causes step to FAIL (fail-closed)."""
        steps = {
            "step-a": _make_step("step-a", outputs=["alpha_out"]),
        }
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = MockExecutionBackend()

        with patch(
            "governance.dag_runner.executor.write_artifact_envelope",
            side_effect=ArtifactWriterError("disk full"),
        ):
            result = execute_plan(
                spec, plan, config=_agent_config(), backend=backend,
            )

        assert result.run_state.node_results["step-a"].status == "FAIL"
        assert "alpha_out" in result.run_state.node_results["step-a"].summary

    def test_artifact_produced_trace_event(self) -> None:
        """Trace contains 'artifact_produced' events after disk write."""
        steps = {
            "step-a": _make_step("step-a", outputs=["alpha_out"]),
        }
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = MockExecutionBackend()

        result = execute_plan(
            spec, plan, config=_agent_config(), backend=backend,
        )

        event_types = [e.event_type for e in result.run_state.execution_trace]
        assert "artifact_produced" in event_types

    def test_artifact_write_failed_trace_event(self) -> None:
        """Trace contains 'artifact_write_failed' on write failure."""
        steps = {
            "step-a": _make_step("step-a", outputs=["alpha_out"]),
        }
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = MockExecutionBackend()

        with patch(
            "governance.dag_runner.executor.write_artifact_envelope",
            side_effect=ArtifactWriterError("disk full"),
        ):
            result = execute_plan(
                spec, plan, config=_agent_config(), backend=backend,
            )

        event_types = [e.event_type for e in result.run_state.execution_trace]
        assert "artifact_write_failed" in event_types

    def test_v1_shell_no_disk_write(self) -> None:
        """V1 shell mode (backend=None) does NOT write artifact files to session dir."""
        steps = {
            "step-a": _make_step("step-a", outputs=["alpha_out"]),
        }
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])

        result = execute_plan(spec, plan)  # no backend = V1 shell
        artifact_dir = Path(result.run_state.session_dir) / "artifacts"

        assert not list(artifact_dir.iterdir())

    def test_envelope_session_matches_run_id(self) -> None:
        """Envelope 'session' field matches the run's run_id."""
        steps = {
            "step-a": _make_step("step-a", outputs=["alpha_out"]),
        }
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = MockExecutionBackend()

        result = execute_plan(
            spec, plan, config=_agent_config(), backend=backend,
        )

        artifact_dir = Path(result.run_state.session_dir) / "artifacts"
        with (artifact_dir / "alpha_out.json").open() as f:
            envelope = json.load(f)
        assert envelope["session"] == result.run_state.run_id
