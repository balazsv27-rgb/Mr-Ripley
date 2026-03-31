from __future__ import annotations

import argparse
import sys
from pathlib import Path

from governance.dag_runner.assembler import AssemblerError, assemble_workflow_spec
from governance.dag_runner.blockers import BlockerError, analyze_blockers
from governance.dag_runner.executor import ExecutorError, execute_plan
from governance.dag_runner.loader import DEFAULT_WORKFLOW_PATH, LoaderError, load_workflow_packages
from governance.dag_runner.planner import PlannerError, build_execution_plan
from governance.dag_runner.state_store import (
    DEFAULT_STATE_PATH,
    StateStoreError,
    build_stored_run_state,
    write_run_state,
)
from governance.dag_runner.validator import ValidationError, validate_or_raise, validate_workflow_spec
from governance.dag_runner.verdict import VerdictError, compute_verdict


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dag-runner",
        description="Mr. Ripley governance DAG runner v1 CLI",
    )
    parser.add_argument(
        "--workflow",
        type=str,
        default=str(DEFAULT_WORKFLOW_PATH),
        help="Path to the root workflow YAML file.",
    )
    parser.add_argument(
        "--show-steps",
        action="store_true",
        help="Print the ordered workflow steps.",
    )
    parser.add_argument(
        "--write-state",
        action="store_true",
        help="Write persisted run state JSON.",
    )
    parser.add_argument(
        "--state-path",
        type=str,
        default=str(DEFAULT_STATE_PATH),
        help="Output path for persisted run state JSON.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    workflow_path = Path(args.workflow)
    state_path = Path(args.state_path)

    try:
        loaded = load_workflow_packages(workflow_path)
        spec = assemble_workflow_spec(loaded)
        validate_or_raise(spec)
        validation_result = validate_workflow_spec(spec)
        plan = build_execution_plan(spec)
        blocker_summary = analyze_blockers(spec, plan)
        verdict = compute_verdict(validation_result, blocker_summary)
        execution_result = execute_plan(spec, plan, verdict_status=verdict.status)

    except (
        LoaderError,
        AssemblerError,
        ValidationError,
        PlannerError,
        BlockerError,
        VerdictError,
        ExecutorError,
    ) as exc:
        print("DAG runner failed.", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1

    print("DAG runner summary")
    print("------------------")
    print(f"Workflow: {plan.workflow_name}")
    print(f"Workflow file: {loaded.workflow_path}")
    print(f"Loaded packages: {len(loaded.packages)}")
    print(f"Workflow steps: {len(spec.workflow_steps)}")
    print(f"Skills: {len(spec.skills)}")
    print(f"Artifacts: {len(spec.artifacts)}")
    print(f"Blocking conditions: {len(spec.blocking_conditions)}")
    print(f"Stage gates: {len(spec.stage_gates)}")
    print(f"Subagents: {len(spec.subagents)}")
    print("Validation: PASS")
    print(f"Planned steps: {len(plan.ordered_steps)}")
    print(f"Executed steps: {len(execution_result.run_state.node_results)}")
    print(f"Recorded trace events: {len(execution_result.run_state.execution_trace)}")
    print(f"Verdict: {verdict.status.upper()}")

    if verdict.reasons:
        print("Verdict reasons:")
        for reason in verdict.reasons:
            print(f"  - {reason}")

    if args.show_steps:
        print()
        print("Execution order")
        print("---------------")
        for index, node in enumerate(plan.ordered_steps, start=1):
            print(f"{index:02d}. {node.step_id} [{node.component}]")

    if args.write_state:
        try:
            state = build_stored_run_state(
                loaded=loaded,
                spec=spec,
                validation_result=validation_result,
                plan=plan,
                blocker_summary=blocker_summary,
                verdict=verdict,
                execution_result=execution_result,
            )
            written_path = write_run_state(state, output_path=state_path)
        except StateStoreError as exc:
            print("Failed to persist run state.", file=sys.stderr)
            print(str(exc), file=sys.stderr)
            return 1

        print()
        print(f"Run state written: {written_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())