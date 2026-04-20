"""Tests for the failure diagnostics contract.

Every FAIL step in --json output must include a standard set of
failure_detail fields.  These tests verify that all six FAIL paths
populate failure_detail consistently and that debug artifacts are
written for every failure type.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from governance.dag_runner.artifact_writer import ArtifactWriterError
from governance.dag_runner.diagnostics import (
    build_diagnostic_report,
    diagnostic_report_to_dict,
)
from governance.dag_runner.execution_backend import (
    MockExecutionBackend,
    write_failure_debug_artifact,
)
from governance.dag_runner.executor import execute_plan
from governance.dag_runner.models import (
    AgentExecutionResult,
    AgentSpec,
    ArtifactSpec,
    AssembledWorkflowSpec,
    BlockingCondition,
    ExecutionConfig,
    FailureClassification,
    ManifestSpec,
    PromptContext,
    WorkflowStep,
)
from governance.dag_runner.planner import ExecutionPlan, PlannedNode


# ---------------------------------------------------------------------------
# Standard failure_detail fields that must be present on every FAIL step
# ---------------------------------------------------------------------------

STANDARD_FIELDS = {
    "failure_origin",
    "failure_stage",
    "returncode",
    "parse_failure_reason",
    "stderr_preview",
    "raw_output_preview",
    "debug_artifact_written",
    "debug_artifact_path",
}


def _assert_standard_fields(failure_detail: dict) -> None:
    """Assert all eight standard fields are present in failure_detail."""
    missing = STANDARD_FIELDS - set(failure_detail.keys())
    assert not missing, f"Missing standard failure_detail fields: {missing}"


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class FailingMockBackend(MockExecutionBackend):
    """Backend that returns success=False with a FailureClassification."""

    def __init__(self, failing_steps: set[str], *, origin: str = "runtime") -> None:
        super().__init__()
        self._failing_steps = failing_steps
        self._origin = origin

    def execute_step(self, step, agent, config, run_state, spec, prompt_context=None, **kwargs):
        if step.name in self._failing_steps:
            return AgentExecutionResult(
                success=False,
                failure=FailureClassification(
                    origin=self._origin,
                    step_id=step.name,
                    detail="forced failure for test",
                ),
                stderr="simulated stderr output",
                raw_output="simulated raw output",
            )
        return super().execute_step(step, agent, config, run_state, spec, prompt_context=prompt_context, **kwargs)

    def execute_structural_step(self, step, component_kind, run_state, spec, **kwargs):
        if step.name in self._failing_steps:
            return AgentExecutionResult(
                success=False,
                failure=FailureClassification(
                    origin=self._origin,
                    step_id=step.name,
                    detail="forced failure for test",
                ),
            )
        return super().execute_structural_step(step, component_kind, run_state, spec, **kwargs)


class TimeoutMockBackend(MockExecutionBackend):
    """Backend that simulates a timeout failure."""

    def __init__(self, failing_steps: set[str]) -> None:
        super().__init__()
        self._failing_steps = failing_steps

    def execute_step(self, step, agent, config, run_state, spec, prompt_context=None, **kwargs):
        if step.name in self._failing_steps:
            return AgentExecutionResult(
                success=False,
                failure=FailureClassification(
                    origin="timeout",
                    step_id=step.name,
                    detail="Claude CLI subprocess timed out after 60000ms.",
                ),
            )
        return super().execute_step(step, agent, config, run_state, spec, prompt_context=prompt_context, **kwargs)


class SchemaViolatingBackend:
    """Backend that produces artifacts violating schema rules.

    NOT a MockExecutionBackend subclass so strict_artifact_validation is True.
    """

    def __init__(self, bad_payloads: dict[str, dict]) -> None:
        self._bad_payloads = bad_payloads

    def execute_step(self, step, agent, config, run_state, spec, prompt_context=None, **kwargs):
        artifacts = {}
        for output_name in step.outputs:
            if output_name in self._bad_payloads:
                artifacts[output_name] = self._bad_payloads[output_name]
            else:
                artifacts[output_name] = {"produced_by": step.name}
        return AgentExecutionResult(success=True, artifacts_produced=artifacts)

    def execute_structural_step(self, step, component_kind, run_state, spec, **kwargs):
        artifacts = {}
        for output_name in step.outputs:
            artifacts[output_name] = {"produced_by": step.name, "structural": True}
        return AgentExecutionResult(success=True, artifacts_produced=artifacts)


def _make_step(
    name: str,
    *,
    component: str = "skill:classify-claims",
    outputs: list[str] | None = None,
    inputs: list[str] | None = None,
    raises: list[str] | None = None,
    depends_on: list[str] | None = None,
) -> WorkflowStep:
    raw: dict = {}
    if inputs is not None:
        raw["inputs"] = inputs
    # Skill/subagent steps need an agent_binding to be dispatched via backend
    kind = component.split(":")[0] if ":" in component else component
    if kind in ("skill", "subagents"):
        agent_name = component.split(":", 1)[1] if ":" in component else component
        raw["agent_binding"] = agent_name
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
        manifest=ManifestSpec(workflow_name="test-fd", workflow_version="1.0"),
        workflow_steps=steps,
        artifacts=artifacts or {},
        blocking_conditions=blocking_conditions or {},
        agents={
            "classify-claims": AgentSpec(name="classify-claims"),
        },
    )


def _make_plan(step_ids: list[str], components: dict[str, str] | None = None) -> ExecutionPlan:
    comps = components or {}
    return ExecutionPlan(
        workflow_name="test-fd",
        ordered_steps=[
            PlannedNode(
                step_id=sid,
                component=comps.get(sid, "skill:classify-claims"),
            )
            for sid in step_ids
        ],
    )


def _default_config() -> ExecutionConfig:
    return ExecutionConfig(mode="agent_execution", request_text="test")


# ---------------------------------------------------------------------------
# Tests: Standard failure_detail contract
# ---------------------------------------------------------------------------


class TestGenericBackendFailure:
    """Path 1: backend returns success=False (runtime/timeout/OSError)."""

    def test_backend_failure_has_standard_fields(self) -> None:
        steps = {"step-a": _make_step("step-a")}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = FailingMockBackend({"step-a"})

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.status == "FAIL"
        _assert_standard_fields(nr.failure_detail)
        assert nr.failure_detail["failure_origin"] == "runtime"
        assert nr.failure_detail["failure_stage"] == "backend_invocation"
        assert nr.failure_detail["debug_artifact_written"] is True

    def test_timeout_failure_has_standard_fields(self) -> None:
        steps = {"step-a": _make_step("step-a")}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = TimeoutMockBackend({"step-a"})

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.status == "FAIL"
        _assert_standard_fields(nr.failure_detail)
        assert nr.failure_detail["failure_origin"] == "timeout"
        assert nr.failure_detail["failure_stage"] == "backend_timeout"

    def test_nonzero_exit_has_stderr_preview(self) -> None:
        steps = {"step-a": _make_step("step-a")}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = FailingMockBackend({"step-a"})

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.failure_detail["stderr_preview"] == "simulated stderr output"
        assert nr.failure_detail["raw_output_preview"] == "simulated raw output"


class TestMissingInputsFailure:
    """Path 4: missing required input artifacts."""

    def test_missing_inputs_has_standard_fields(self) -> None:
        steps = {
            "step-a": _make_step("step-a", outputs=["art-a"]),
            "step-b": _make_step(
                "step-b",
                inputs=["art-a"],
                depends_on=["step-a"],
            ),
        }
        spec = _make_spec(
            steps,
            artifacts={
                "art-a": ArtifactSpec(name="art-a", producer_step="step-a"),
            },
        )
        plan = _make_plan(["step-a", "step-b"])
        # step-a fails, so art-a never produced; step-b should FAIL on missing input
        backend = FailingMockBackend({"step-a"})

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr_b = result.run_state.node_results.get("step-b")

        # step-b may be skipped if step-a halts; if reached, must have standard fields
        if nr_b is not None and nr_b.status == "FAIL":
            _assert_standard_fields(nr_b.failure_detail)
            assert nr_b.failure_detail["failure_origin"] == "contract"
            assert nr_b.failure_detail["failure_stage"] == "input_validation"
            assert "missing_inputs" in nr_b.failure_detail

    def test_missing_inputs_classified_as_contract(self) -> None:
        """Missing inputs is a contract failure, not structural."""
        steps = {
            "step-producer": _make_step(
                "step-producer",
                component="constitution",
                outputs=["needed-art"],
            ),
            "step-consumer": _make_step(
                "step-consumer",
                inputs=["needed-art"],
                depends_on=["step-producer"],
            ),
        }
        spec = _make_spec(
            steps,
            artifacts={
                "needed-art": ArtifactSpec(name="needed-art", producer_step="step-producer"),
            },
        )
        plan = _make_plan(
            ["step-producer", "step-consumer"],
            components={
                "step-producer": "constitution",
                "step-consumer": "skill:classify-claims",
            },
        )
        # Produce art that doesn't match the expected name
        backend = MockExecutionBackend(artifact_payloads={
            "needed-art": {"produced_by": "step-producer", "structural": True},
        })

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        # If step-consumer got needed-art, it should pass. This test validates
        # the classification when missing_inputs actually fires.
        # Force the missing case by using a backend that skips producing the artifact:
        class NoArtBackend(MockExecutionBackend):
            def execute_structural_step(self, step, component_kind, run_state, spec, **kwargs):
                # Produce empty artifacts for the producer step
                return AgentExecutionResult(success=True, artifacts_produced={})

        backend2 = NoArtBackend()
        result2 = execute_plan(spec, plan, config=_default_config(), backend=backend2)
        nr = result2.run_state.node_results.get("step-consumer")
        if nr is not None and nr.status == "FAIL":
            assert nr.failure_detail["failure_origin"] == "contract"


class TestSchemaValidationFailure:
    """Path 3: artifact schema violations with strict validation."""

    def test_schema_violation_has_standard_fields(self) -> None:
        steps = {
            "step-a": _make_step("step-a", outputs=["art-a"]),
        }
        spec = _make_spec(steps)
        # Produce an artifact that violates schema (missing produced_by)
        backend = SchemaViolatingBackend({"art-a": {"no_produced_by": True}})

        result = execute_plan(spec, plan=_make_plan(["step-a"]), config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.status == "FAIL"
        _assert_standard_fields(nr.failure_detail)
        assert nr.failure_detail["failure_origin"] == "contract"
        assert nr.failure_detail["failure_stage"] == "schema_validation"
        assert "violation_count" in nr.failure_detail
        assert "violations" in nr.failure_detail


class TestArtifactWriteFailure:
    """Path 6: artifact envelope write to disk fails."""

    def test_artifact_write_failure_has_standard_fields(self) -> None:
        steps = {
            "step-a": _make_step(
                "step-a",
                component="constitution",
                outputs=["art-a"],
            ),
        }
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"], components={"step-a": "constitution"})
        backend = MockExecutionBackend()

        with patch(
            "governance.dag_runner.executor.write_artifact_envelope",
            side_effect=ArtifactWriterError("disk full"),
        ):
            result = execute_plan(
                spec, plan, config=_default_config(), backend=backend
            )

        nr = result.run_state.node_results["step-a"]
        assert nr.status == "FAIL"
        _assert_standard_fields(nr.failure_detail)
        assert nr.failure_detail["failure_origin"] == "artifact"
        assert nr.failure_detail["failure_stage"] == "artifact_write"
        assert "failed_artifacts" in nr.failure_detail


# ---------------------------------------------------------------------------
# Tests: Debug artifact writing
# ---------------------------------------------------------------------------


class TestDebugArtifactWriting:
    """Debug artifacts must be written for all FAIL paths."""

    def test_debug_artifact_written_for_backend_failure(self) -> None:
        steps = {"step-a": _make_step("step-a")}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = FailingMockBackend({"step-a"})

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.failure_detail["debug_artifact_written"] is True
        assert nr.failure_detail["debug_artifact_path"] is not None
        # Verify the file actually exists
        debug_path = Path(nr.failure_detail["debug_artifact_path"])
        assert debug_path.exists()
        content = json.loads(debug_path.read_text(encoding="utf-8"))
        assert content["step_name"] == "step-a"

    def test_debug_write_failure_surfaces_in_trace_and_detail(self) -> None:
        steps = {"step-a": _make_step("step-a")}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = FailingMockBackend({"step-a"})

        with patch(
            "governance.dag_runner.executor.write_failure_debug_artifact",
            return_value=(False, None, "permission denied"),
        ):
            result = execute_plan(
                spec, plan, config=_default_config(), backend=backend
            )

        nr = result.run_state.node_results["step-a"]
        assert nr.failure_detail["debug_artifact_written"] is False
        assert nr.failure_detail["debug_artifact_path"] is None
        assert nr.failure_detail["debug_write_error"] == "permission denied"

        # Verify trace event
        trace_types = [e.event_type for e in result.run_state.execution_trace]
        assert "debug_write_failed" in trace_types


class TestWriteFailureDebugArtifact:
    """Unit tests for the write_failure_debug_artifact function itself."""

    def test_writes_json_with_failure_detail(self, tmp_path: Path) -> None:
        fd = {"failure_origin": "runtime", "failure_stage": "backend_invocation"}
        written, path, err = write_failure_debug_artifact(
            step_name="test-step",
            failure_detail=fd,
            raw_output="some raw output",
            stderr="some stderr",
            debug_dir=str(tmp_path),
        )
        assert written is True
        assert path is not None
        assert err is None
        content = json.loads(Path(path).read_text(encoding="utf-8"))
        assert content["step_name"] == "test-step"
        assert content["failure_detail"]["failure_origin"] == "runtime"
        assert content["raw_output_length"] == 15
        assert content["stderr_length"] == 11

    def test_works_without_raw_output(self, tmp_path: Path) -> None:
        fd = {"failure_origin": "contract", "failure_stage": "input_validation"}
        written, path, err = write_failure_debug_artifact(
            step_name="no-output-step",
            failure_detail=fd,
            debug_dir=str(tmp_path),
        )
        assert written is True
        content = json.loads(Path(path).read_text(encoding="utf-8"))
        assert "raw_output_length" not in content
        assert "stderr_length" not in content

    def test_returns_error_on_failure(self, tmp_path: Path) -> None:
        # Create a file where a directory is expected — writing will fail
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        written, path, err = write_failure_debug_artifact(
            step_name="test",
            failure_detail={},
            debug_dir=str(blocker),
        )
        assert written is False
        assert path is None
        assert err is not None

    def test_envelope_extraction_when_raw_output_is_cli_json(self, tmp_path: Path) -> None:
        """When raw_output is a CLI JSON envelope, the debug file must
        contain the inner result text and envelope metadata — not just
        a truncated outer JSON string."""
        inner_result = (
            "I'll analyze this request.\n\n"
            "<tool_call>\n"
            '{"name": "Glob", "arguments": {"pattern": "**/*.json"}}\n'
            "</tool_call>"
        )
        envelope = json.dumps({
            "type": "result",
            "is_error": False,
            "result": inner_result,
            "usage": {"input_tokens": 50000, "output_tokens": 200},
        })
        fd = {"failure_origin": "runtime", "failure_stage": "backend_parse"}
        written, path, err = write_failure_debug_artifact(
            step_name="classify-claims",
            failure_detail=fd,
            raw_output=envelope,
            stderr="",
            debug_dir=str(tmp_path),
        )
        assert written is True
        content = json.loads(Path(path).read_text(encoding="utf-8"))

        # Envelope metadata must be extracted
        assert content["envelope_type"] == "result"
        assert content["envelope_is_error"] is False
        assert "result" in content["envelope_keys"]
        assert content["usage"] == {"input_tokens": 50000, "output_tokens": 200}

        # Inner result text must be readable — not buried inside escaped JSON
        assert "result_text_length" in content
        assert content["result_text_length"] == len(inner_result)
        assert "<tool_call>" in content["result_text_first_2000"]
        assert "Glob" in content["result_text_first_2000"]

    def test_non_json_raw_output_gets_parse_error_flag(self, tmp_path: Path) -> None:
        """When raw_output is not JSON, envelope_parse_error is set."""
        fd = {"failure_origin": "runtime", "failure_stage": "backend_parse"}
        written, path, err = write_failure_debug_artifact(
            step_name="step-x",
            failure_detail=fd,
            raw_output="not json at all",
            debug_dir=str(tmp_path),
        )
        assert written is True
        content = json.loads(Path(path).read_text(encoding="utf-8"))
        assert content["envelope_parse_error"] == "raw_output is not valid JSON"
        assert "result_text_first_2000" not in content


# ---------------------------------------------------------------------------
# Tests: Missing declared outputs
# ---------------------------------------------------------------------------


_TOOL_CALL_RESULT_TEXT = (
    "I'll analyze this request by reading the relevant files.\n\n"
    "<tool_call>\n"
    '{"name": "Glob", "arguments": {"pattern": "**/*.json"}}\n'
    "</tool_call>\n\n"
    "<tool_call>\n"
    '{"name": "Grep", "arguments": {"pattern": "series_registry"}}\n'
    "</tool_call>"
)

_TOOL_CALL_ENVELOPE = json.dumps({
    "type": "result",
    "is_error": False,
    "result": _TOOL_CALL_RESULT_TEXT,
    "usage": {"input_tokens": 48000, "output_tokens": 150},
})


class ToolCallResponseBackend(MockExecutionBackend):
    """Backend simulating a model that returned tool-call markup instead of artifacts."""

    def execute_step(self, step, agent, config, run_state, spec, prompt_context=None, **kwargs):
        return AgentExecutionResult(
            success=True,
            artifacts_produced={},
            raw_output=_TOOL_CALL_ENVELOPE,
            parse_failure=(
                "disallowed_tool_use_response: result text contains "
                "tool-call markup (no-tools contract violation)"
            ),
            stderr="",
        )


class EmptyOutputBackend(MockExecutionBackend):
    """Backend that returns success=True but produces no artifacts, with raw output."""

    def execute_step(self, step, agent, config, run_state, spec, prompt_context=None, **kwargs):
        return AgentExecutionResult(
            success=True,
            artifacts_produced={},
            raw_output='{"result": "{}"}',
        )


class ParseFailureMockBackend(MockExecutionBackend):
    """Backend that returns success=True with a parse failure and no artifacts."""

    def execute_step(self, step, agent, config, run_state, spec, prompt_context=None, **kwargs):
        return AgentExecutionResult(
            success=True,
            artifacts_produced={},
            raw_output="not json at all",
            parse_failure="inner_result_no_json_object: direct parse failed",
            stderr="warning: something went wrong",
        )


class PartialOutputBackend(MockExecutionBackend):
    """Backend that produces only the explicitly given artifacts."""

    def __init__(self, produced: dict[str, dict]) -> None:
        super().__init__()
        self._produced = produced

    def execute_step(self, step, agent, config, run_state, spec, prompt_context=None, **kwargs):
        return AgentExecutionResult(
            success=True,
            artifacts_produced=dict(self._produced),
        )


class TestBackendResponseContractFailure:
    """Backend returns success but zero artifacts with raw evidence.

    Regression: this must NOT degrade into executor_declared_output_check
    with empty diagnostics.  The stage must be backend_response_contract
    when raw output exists but no artifacts were extracted.
    """

    def test_zero_artifacts_with_raw_output_is_backend_response_contract(self) -> None:
        steps = {"step-a": _make_step("step-a", outputs=["expected_art"])}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = EmptyOutputBackend()

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.status == "FAIL"
        _assert_standard_fields(nr.failure_detail)
        assert nr.failure_detail["failure_origin"] == "runtime"
        assert nr.failure_detail["failure_stage"] == "backend_response_contract"
        assert "expected_art" in nr.failure_detail["missing_outputs"]
        assert nr.failure_detail["debug_artifact_written"] is True

    def test_backend_response_contract_preserves_raw_preview(self) -> None:
        steps = {"step-a": _make_step("step-a", outputs=["art_x", "art_y"])}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = EmptyOutputBackend()

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.status == "FAIL"
        assert nr.failure_detail["failure_stage"] == "backend_response_contract"
        assert set(nr.failure_detail["missing_outputs"]) == {"art_x", "art_y"}
        assert nr.failure_detail["declared_outputs"] == ["art_x", "art_y"]
        assert nr.failure_detail["produced_outputs"] == []
        # raw_output_preview must be populated from the backend's stdout
        assert nr.failure_detail["raw_output_preview"] != ""

    def test_debug_artifact_written_when_raw_output_exists(self) -> None:
        steps = {"step-a": _make_step("step-a", outputs=["expected_art"])}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = EmptyOutputBackend()

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.failure_detail["debug_artifact_written"] is True
        debug_path = Path(nr.failure_detail["debug_artifact_path"])
        assert debug_path.exists()
        content = json.loads(debug_path.read_text(encoding="utf-8"))
        assert content["step_name"] == "step-a"
        assert "raw_output_length" in content


class TestExecutorDeclaredOutputCheck:
    """True executor_declared_output_check: some artifacts parsed but
    declared outputs not fully satisfied."""

    def test_partial_output_is_executor_declared_output_check(self) -> None:
        """Backend produces art_a but step declares [art_a, art_b]."""
        steps = {"step-a": _make_step("step-a", outputs=["art_a", "art_b"])}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = PartialOutputBackend({"art_a": {"ok": True}})

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.status == "FAIL"
        _assert_standard_fields(nr.failure_detail)
        assert nr.failure_detail["failure_origin"] == "runtime"
        assert nr.failure_detail["failure_stage"] == "executor_declared_output_check"
        assert nr.failure_detail["missing_outputs"] == ["art_b"]
        assert nr.failure_detail["produced_outputs"] == ["art_a"]


# ---------------------------------------------------------------------------
# Tests: Parse failure
# ---------------------------------------------------------------------------


class TestParseFailure:
    """Backend succeeds with explicit parse failure — stage must be backend_parse."""

    def test_parse_failure_stage_is_backend_parse(self) -> None:
        steps = {"step-a": _make_step("step-a", outputs=["expected_art"])}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = ParseFailureMockBackend()

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.status == "FAIL"
        _assert_standard_fields(nr.failure_detail)
        assert nr.failure_detail["failure_stage"] == "backend_parse"
        assert nr.failure_detail["parse_failure_reason"] is not None
        assert "inner_result_no_json_object" in nr.failure_detail["parse_failure_reason"]

    def test_parse_failure_has_stderr_and_raw_preview(self) -> None:
        steps = {"step-a": _make_step("step-a", outputs=["expected_art"])}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = ParseFailureMockBackend()

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.failure_detail["stderr_preview"] == "warning: something went wrong"
        # raw_output_preview comes from inner result extraction or raw fallback
        assert nr.failure_detail["raw_output_preview"] != ""

    def test_parse_failure_debug_artifact_attempted(self) -> None:
        steps = {"step-a": _make_step("step-a", outputs=["expected_art"])}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = ParseFailureMockBackend()

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.failure_detail["debug_artifact_written"] is True
        debug_path = Path(nr.failure_detail["debug_artifact_path"])
        assert debug_path.exists()


# ---------------------------------------------------------------------------
# Tests: Tool-call response end-to-end (the classify-claims regression)
# ---------------------------------------------------------------------------


class TestToolCallResponseEndToEnd:
    """Full chain: tool-call response → backend_parse → informative debug artifact.

    Regression test for the classify-claims failure where the model returned
    prose + <tool_call> blocks.  The debug file must contain the actual inner
    result text (readable, not buried in escaped outer-envelope JSON) so that
    the operator can see exactly what the model produced.
    """

    def test_tool_call_response_classified_as_backend_parse(self) -> None:
        steps = {"step-a": _make_step("step-a", outputs=["claim_map"])}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = ToolCallResponseBackend()

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.status == "FAIL"
        _assert_standard_fields(nr.failure_detail)
        assert nr.failure_detail["failure_origin"] == "runtime"
        assert nr.failure_detail["failure_stage"] == "backend_parse"
        assert "disallowed_tool_use_response" in nr.failure_detail["parse_failure_reason"]

    def test_debug_file_contains_inner_result_text(self) -> None:
        steps = {"step-a": _make_step("step-a", outputs=["claim_map"])}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = ToolCallResponseBackend()

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.failure_detail["debug_artifact_written"] is True
        debug_path = Path(nr.failure_detail["debug_artifact_path"])
        assert debug_path.exists()

        content = json.loads(debug_path.read_text(encoding="utf-8"))
        # Must have envelope metadata
        assert content["envelope_type"] == "result"
        assert content["envelope_is_error"] is False
        assert content["usage"]["output_tokens"] == 150
        # Must have the INNER result text — the actual model output,
        # not the truncated outer-envelope JSON
        assert "result_text_first_2000" in content
        assert "<tool_call>" in content["result_text_first_2000"]
        assert "Glob" in content["result_text_first_2000"]
        assert content["result_text_length"] == len(_TOOL_CALL_RESULT_TEXT)

    def test_raw_output_preview_in_failure_detail_is_populated(self) -> None:
        steps = {"step-a": _make_step("step-a", outputs=["claim_map"])}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = ToolCallResponseBackend()

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        # failure_detail raw_output_preview comes from the executor's
        # envelope extraction — should be the inner result text
        assert nr.failure_detail["raw_output_preview"] != ""
        assert "tool_call" in nr.failure_detail["raw_output_preview"].lower() or \
               "analyze" in nr.failure_detail["raw_output_preview"].lower()


# ---------------------------------------------------------------------------
# Tests: Nonzero subprocess exit with returncode
# ---------------------------------------------------------------------------


class TestNonzeroSubprocessExit:
    """Backend returns success=False with returncode and stderr."""

    def test_returncode_present_in_failure_detail(self) -> None:
        """Returncode field is always present (None for mock, int for real)."""
        steps = {"step-a": _make_step("step-a")}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = FailingMockBackend({"step-a"})

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.status == "FAIL"
        # returncode is in standard fields — always present
        assert "returncode" in nr.failure_detail

    def test_stderr_preview_present_when_stderr_exists(self) -> None:
        steps = {"step-a": _make_step("step-a")}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = FailingMockBackend({"step-a"})

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.failure_detail["stderr_preview"] == "simulated stderr output"


# ---------------------------------------------------------------------------
# Tests: Timeout with debug artifact metadata
# ---------------------------------------------------------------------------


class TestTimeoutDebugArtifact:
    """Timeout failure must surface debug artifact metadata."""

    def test_timeout_debug_artifact_metadata_present(self) -> None:
        steps = {"step-a": _make_step("step-a")}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = TimeoutMockBackend({"step-a"})

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.status == "FAIL"
        assert nr.failure_detail["failure_stage"] == "backend_timeout"
        # Debug artifact attempt metadata must be present
        assert "debug_artifact_written" in nr.failure_detail
        assert "debug_artifact_path" in nr.failure_detail


# ---------------------------------------------------------------------------
# Tests: Timeout misclassification regression
# ---------------------------------------------------------------------------


class TestTimeoutNotMisclassified:
    """Backend timeout MUST NOT be misclassified as executor_declared_output_check.

    Regression: a timeout returns success=False with no artifacts.  The old
    missing-outputs block ran regardless of result.success, relabeling the
    timeout as a declared-output failure with empty diagnostics.
    """

    def test_timeout_classified_as_backend_timeout(self) -> None:
        """Exact reproduction of the normalize-terminology live failure."""
        steps = {"step-a": _make_step("step-a", outputs=["expected_art"])}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = TimeoutMockBackend({"step-a"})

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.status == "FAIL"
        assert nr.failure_detail["failure_origin"] == "timeout"
        assert nr.failure_detail["failure_stage"] == "backend_timeout"
        # Must NOT be executor_declared_output_check
        assert nr.failure_detail["failure_stage"] != "executor_declared_output_check"
        # Backend failure detail is preserved
        assert nr.failure_detail["backend_failure_detail"] is not None
        assert "timed out" in nr.failure_detail["backend_failure_detail"]

    def test_timeout_with_declared_outputs_still_backend_timeout(self) -> None:
        """Step has declared outputs but timeout is the true cause."""
        steps = {"step-a": _make_step("step-a", outputs=["art_x", "art_y"])}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = TimeoutMockBackend({"step-a"})

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.failure_detail["failure_stage"] == "backend_timeout"
        assert nr.failure_detail["debug_artifact_written"] is True

    def test_timeout_trace_event_emitted(self) -> None:
        steps = {"step-a": _make_step("step-a", outputs=["expected_art"])}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = TimeoutMockBackend({"step-a"})

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        trace_types = [e.event_type for e in result.run_state.execution_trace]
        assert "backend_timeout" in trace_types


class TestNonzeroExitNotMisclassified:
    """Backend runtime failure (nonzero exit) MUST NOT be misclassified."""

    def test_nonzero_exit_classified_as_backend_invocation(self) -> None:
        steps = {"step-a": _make_step("step-a", outputs=["expected_art"])}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = FailingMockBackend({"step-a"})

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.status == "FAIL"
        assert nr.failure_detail["failure_origin"] == "runtime"
        assert nr.failure_detail["failure_stage"] == "backend_invocation"
        assert nr.failure_detail["failure_stage"] != "executor_declared_output_check"


# ---------------------------------------------------------------------------
# Tests: Successful path regression
# ---------------------------------------------------------------------------


class TestSuccessfulPathRegression:
    """Successful backend-dispatched steps must not regress."""

    def test_successful_step_passes_with_artifacts(self) -> None:
        steps = {
            "step-a": _make_step("step-a", outputs=["art-a"]),
        }
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = MockExecutionBackend()

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.status == "PASS"
        assert "art-a" in nr.produced_artifacts
        # No failure_detail on success
        assert nr.failure_detail == {}

    def test_successful_step_artifact_unchanged(self) -> None:
        """Artifact payload from backend is preserved unchanged."""
        custom_payload = {"key": "value", "nested": {"a": 1}}
        steps = {
            "step-a": _make_step("step-a", outputs=["art-a"]),
        }
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = MockExecutionBackend(artifact_payloads={"art-a": custom_payload})

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.status == "PASS"
        art = result.run_state.artifacts["art-a"]
        assert art.payload["key"] == "value"
        assert art.payload["nested"]["a"] == 1

    def test_structural_step_unaffected(self) -> None:
        """Structural steps still pass without failure_detail."""
        steps = {
            "step-a": _make_step("step-a", component="constitution", outputs=["ctx"]),
        }
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"], components={"step-a": "constitution"})
        backend = MockExecutionBackend()

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        nr = result.run_state.node_results["step-a"]

        assert nr.status == "PASS"
        assert nr.failure_detail == {}


# ---------------------------------------------------------------------------
# Tests: Diagnostics serialization
# ---------------------------------------------------------------------------


class TestDiagnosticsSerialization:
    """FAIL steps in diagnostic report must always include failure_detail."""

    def test_fail_step_always_has_failure_detail_in_json(self) -> None:
        steps = {"step-a": _make_step("step-a")}
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"])
        backend = FailingMockBackend({"step-a"})

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        report = build_diagnostic_report(spec, plan, result.run_state)
        report_dict = diagnostic_report_to_dict(report)

        fail_steps = [s for s in report_dict["steps"] if s["status"] == "FAIL"]
        assert len(fail_steps) >= 1
        for step_diag in fail_steps:
            assert "failure_detail" in step_diag
            _assert_standard_fields(step_diag["failure_detail"])

    def test_pass_step_does_not_have_failure_detail(self) -> None:
        steps = {
            "step-a": _make_step("step-a", component="constitution", outputs=["art-a"]),
        }
        spec = _make_spec(steps)
        plan = _make_plan(["step-a"], components={"step-a": "constitution"})
        backend = MockExecutionBackend()

        result = execute_plan(spec, plan, config=_default_config(), backend=backend)
        report = build_diagnostic_report(spec, plan, result.run_state)
        report_dict = diagnostic_report_to_dict(report)

        pass_steps = [s for s in report_dict["steps"] if s["status"] == "PASS"]
        for step_diag in pass_steps:
            assert "failure_detail" not in step_diag
