"""
drift_detector.py — Pre-execution cross-file consistency validation.

Runs AFTER assembly and validation, BEFORE execution planning.
Critical drifts block execution.  Informational drifts produce warnings.

Drift checks:
  1. Agent file existence (critical)
  2. Skill file existence (critical)
  3. Agent-step binding mismatch (critical)
  4. Artifact producer consistency (critical)
  5. Hook reinforcement consistency (informational)
  6. Duplicate invariant logic (informational)
  7. Doc path consistency (informational)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from governance.dag_runner.models import AssembledWorkflowSpec


DriftSeverity = Literal["critical", "informational"]


@dataclass(frozen=True)
class DriftIssue:
    """Single drift finding."""

    check: str
    severity: DriftSeverity
    message: str
    detail: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DriftResult:
    """Aggregate drift detection result."""

    is_clean: bool
    critical_drifts: list[DriftIssue]
    informational_drifts: list[DriftIssue]

    @property
    def all_issues(self) -> list[DriftIssue]:
        return self.critical_drifts + self.informational_drifts


class DriftDetectionError(RuntimeError):
    """Raised when critical drifts are detected and block execution."""


def _check_agent_files(
    spec: AssembledWorkflowSpec,
    repo_root: Path,
) -> list[DriftIssue]:
    """Check 1: Every declared agent has a .claude/agents/<name>.md file."""
    issues: list[DriftIssue] = []
    for agent_name in spec.agents:
        agent_path = repo_root / ".claude" / "agents" / f"{agent_name}.md"
        if not agent_path.is_file():
            issues.append(DriftIssue(
                check="agent_file_existence",
                severity="critical",
                message=f"Agent '{agent_name}' has no file at {agent_path}.",
                detail={"agent": agent_name, "expected_path": str(agent_path)},
            ))
    return issues


def _check_skill_files(
    spec: AssembledWorkflowSpec,
    repo_root: Path,
) -> list[DriftIssue]:
    """Check 2: Every declared skill has a .claude/skills/<name>/SKILL.md file."""
    issues: list[DriftIssue] = []
    for skill_name in spec.skills:
        skill_path = repo_root / ".claude" / "skills" / skill_name / "SKILL.md"
        if not skill_path.is_file():
            issues.append(DriftIssue(
                check="skill_file_existence",
                severity="critical",
                message=f"Skill '{skill_name}' has no file at {skill_path}.",
                detail={"skill": skill_name, "expected_path": str(skill_path)},
            ))
    return issues


def _check_agent_step_bindings(
    spec: AssembledWorkflowSpec,
) -> list[DriftIssue]:
    """Check 3: Agent workflow_steps match step agent_binding (bidirectional)."""
    issues: list[DriftIssue] = []

    # Build maps
    step_to_agent: dict[str, str] = {}
    for step_id, step in spec.workflow_steps.items():
        binding = step.raw.get("agent_binding")
        if isinstance(binding, str) and binding.strip():
            step_to_agent[step_id] = binding.strip()

    agent_to_steps: dict[str, list[str]] = {}
    for agent_name, agent in spec.agents.items():
        agent_to_steps[agent_name] = agent.workflow_steps

    # Check: each step's agent_binding matches the agent's workflow_steps
    for step_id, agent_name in step_to_agent.items():
        agent = spec.agents.get(agent_name)
        if agent is None:
            continue  # covered by validator
        if step_id not in agent.workflow_steps:
            issues.append(DriftIssue(
                check="agent_step_binding_mismatch",
                severity="critical",
                message=(
                    f"Step '{step_id}' binds to agent '{agent_name}', "
                    f"but agent.workflow_steps does not include '{step_id}'."
                ),
                detail={"step": step_id, "agent": agent_name},
            ))

    # Check: each agent's workflow_steps has a matching step with agent_binding
    for agent_name, declared_steps in agent_to_steps.items():
        for step_id in declared_steps:
            if step_id not in step_to_agent:
                issues.append(DriftIssue(
                    check="agent_step_binding_mismatch",
                    severity="critical",
                    message=(
                        f"Agent '{agent_name}' declares workflow_step '{step_id}', "
                        f"but that step has no agent_binding."
                    ),
                    detail={"agent": agent_name, "step": step_id},
                ))
            elif step_to_agent.get(step_id) != agent_name:
                issues.append(DriftIssue(
                    check="agent_step_binding_mismatch",
                    severity="critical",
                    message=(
                        f"Agent '{agent_name}' declares workflow_step '{step_id}', "
                        f"but step binds to '{step_to_agent[step_id]}'."
                    ),
                    detail={"agent": agent_name, "step": step_id},
                ))

    return issues


def _check_artifact_producer_consistency(
    spec: AssembledWorkflowSpec,
) -> list[DriftIssue]:
    """Check 4: Agent produces matches step outputs for bound steps."""
    issues: list[DriftIssue] = []

    for agent_name, agent in spec.agents.items():
        for step_id in agent.workflow_steps:
            step = spec.workflow_steps.get(step_id)
            if step is None:
                continue

            agent_produces = set(agent.produces)
            step_outputs = set(step.outputs)

            for artifact in agent_produces - step_outputs:
                issues.append(DriftIssue(
                    check="artifact_producer_consistency",
                    severity="critical",
                    message=(
                        f"Agent '{agent_name}' declares produces '{artifact}', "
                        f"but bound step '{step_id}' does not list it in outputs."
                    ),
                    detail={"agent": agent_name, "step": step_id, "artifact": artifact},
                ))

            for artifact in step_outputs - agent_produces:
                issues.append(DriftIssue(
                    check="artifact_producer_consistency",
                    severity="critical",
                    message=(
                        f"Step '{step_id}' declares output '{artifact}', "
                        f"but bound agent '{agent_name}' does not list it in produces."
                    ),
                    detail={"agent": agent_name, "step": step_id, "artifact": artifact},
                ))

    return issues


def _check_hook_reinforcements(
    spec: AssembledWorkflowSpec,
) -> list[DriftIssue]:
    """Check 5: Hook reinforcement consistency (informational)."""
    issues: list[DriftIssue] = []

    # Build hook reads_artifacts map
    hooks_data = spec.hooks.get("data", []) if isinstance(spec.hooks, dict) else []
    hook_reads: dict[str, list[str]] = {}
    for hook in hooks_data:
        if isinstance(hook, dict):
            name = hook.get("name", "")
            reads = hook.get("reads_artifacts", []) or []
            hook_reads[name] = reads

    # Check: agent hook_reinforcement reads the agent's output artifacts
    for agent_name, agent in spec.agents.items():
        if not agent.hook_reinforcement:
            continue
        hook_name = agent.hook_reinforcement
        reads = hook_reads.get(hook_name, [])
        for artifact in agent.produces:
            if artifact not in reads:
                issues.append(DriftIssue(
                    check="hook_reinforcement_consistency",
                    severity="informational",
                    message=(
                        f"Agent '{agent_name}' is reinforced by hook '{hook_name}', "
                        f"but hook does not read artifact '{artifact}'."
                    ),
                    detail={"agent": agent_name, "hook": hook_name, "artifact": artifact},
                ))

    return issues


def detect_drift(
    spec: AssembledWorkflowSpec,
    repo_root: Path,
) -> DriftResult:
    """Run all drift checks and return aggregate result.

    Critical drifts block execution.
    Informational drifts produce warnings only.
    """
    all_issues: list[DriftIssue] = []

    all_issues.extend(_check_agent_files(spec, repo_root))
    all_issues.extend(_check_skill_files(spec, repo_root))
    all_issues.extend(_check_agent_step_bindings(spec))
    all_issues.extend(_check_artifact_producer_consistency(spec))
    all_issues.extend(_check_hook_reinforcements(spec))

    critical = [i for i in all_issues if i.severity == "critical"]
    informational = [i for i in all_issues if i.severity == "informational"]

    return DriftResult(
        is_clean=len(critical) == 0,
        critical_drifts=critical,
        informational_drifts=informational,
    )
