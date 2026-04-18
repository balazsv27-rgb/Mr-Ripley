"""
prompt_assembly.py — Assemble bounded prompt context for each workflow step.

Constructs a ``PromptAssemblyContext`` with deterministic priority-ordered
assembly and token budget enforcement.

Assembly order (priority, highest first):
1. Skill SKILL.md content (never truncated)
2. Agent .md file content
3. Upstream artifact payloads (ordered by production step in DAG order)
4. Canonical document paths (from agent.consumes)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from governance.dag_runner.agent_resolver import (
    AgentResolverError,
    load_agent_file,
    resolve_agent,
    resolve_skill_content,
)
from governance.dag_runner.input_bounding import (
    BoundedInput,
    bound_inputs,
    estimate_tokens,
)
from governance.dag_runner.models import (
    AgentSpec,
    AssembledWorkflowSpec,
    GovernanceRunState,
    WorkflowStep,
)


class PromptAssemblyError(RuntimeError):
    """Raised when prompt assembly fails."""


def _get_repo_root() -> Path:
    """Resolve the project repo root (two levels up from governance/dag_runner/)."""
    return Path(__file__).resolve().parent.parent.parent


def _gather_artifact_inputs(
    step: WorkflowStep,
    agent: AgentSpec | None,
    run_state: GovernanceRunState,
) -> dict[str, dict[str, Any]]:
    """Gather upstream artifact payloads for this step's inputs."""
    result: dict[str, dict[str, Any]] = {}

    # Collect input names from step.raw and agent.consumes
    input_names: list[str] = []
    raw_inputs = step.raw.get("inputs", []) or []
    if isinstance(raw_inputs, list):
        input_names.extend(str(i) for i in raw_inputs)

    if agent is not None:
        for c in agent.consumes:
            if c not in input_names:
                input_names.append(c)

    for name in input_names:
        artifact = run_state.artifacts.get(name)
        if artifact is not None and artifact.status == "present":
            result[name] = artifact.payload

    return result


def _gather_document_paths(
    agent: AgentSpec | None,
    repo_root: Path,
) -> list[str]:
    """Gather canonical document paths from agent.consumes.

    Only includes paths that resolve to existing files.
    """
    if agent is None:
        return []

    paths: list[str] = []
    for consume_name in agent.consumes:
        # Skip artifact references (artifacts are handled separately)
        if consume_name.startswith("canonical_docs"):
            continue

        # Check common document locations
        for candidate in [
            repo_root / consume_name,
            repo_root / "Documentation" / consume_name,
        ]:
            if candidate.is_file():
                paths.append(str(candidate))
                break

    return paths


def assemble_step_prompt(
    step: WorkflowStep,
    spec: AssembledWorkflowSpec,
    run_state: GovernanceRunState,
    repo_root: Path | None = None,
    token_budget: int = 100_000,
) -> dict[str, Any]:
    """Assemble bounded prompt context for a single workflow step.

    Returns a dict with:
      - ``agent``: resolved AgentSpec (or None)
      - ``skill_content``: concatenated SKILL.md content
      - ``agent_instructions``: agent .md file content
      - ``artifact_inputs``: upstream artifact payloads
      - ``document_paths``: resolved canonical doc paths
      - ``token_budget``: the budget
      - ``truncated``: whether any input was truncated
      - ``truncation_events``: list of truncation events (if any)
    """
    if repo_root is None:
        repo_root = _get_repo_root()

    # Resolve agent
    agent = resolve_agent(step, spec)

    # Resolve skill content
    skill_content = ""
    if agent is not None:
        try:
            skill_content = resolve_skill_content(agent, repo_root)
        except AgentResolverError:
            skill_content = ""

    # Load agent instructions
    agent_instructions = ""
    if agent is not None:
        try:
            agent_instructions = load_agent_file(agent.name, repo_root)
        except AgentResolverError:
            agent_instructions = ""

    # Gather artifact inputs
    artifact_inputs = _gather_artifact_inputs(step, agent, run_state)

    # Gather document paths
    document_paths = _gather_document_paths(agent, repo_root)

    # Build bounded inputs
    bounded = []
    if skill_content:
        bounded.append(BoundedInput(
            name="skill_instructions",
            content=skill_content,
            priority=1,
        ))
    if agent_instructions:
        bounded.append(BoundedInput(
            name="agent_instructions",
            content=agent_instructions,
            priority=2,
        ))

    # Artifact payloads as serialized JSON strings
    import json
    for art_name, art_payload in artifact_inputs.items():
        bounded.append(BoundedInput(
            name=f"artifact:{art_name}",
            content=json.dumps(art_payload, indent=2),
            priority=3,
        ))

    # Document content (read files)
    for doc_path in document_paths:
        try:
            doc_content = Path(doc_path).read_text(encoding="utf-8")
            bounded.append(BoundedInput(
                name=f"doc:{doc_path}",
                content=doc_content,
                priority=4,
            ))
        except (OSError, UnicodeDecodeError):
            pass

    # Apply token budget
    bounding_result = bound_inputs(bounded, token_budget)

    return {
        "agent": agent,
        "skill_content": skill_content if not any(
            b.name == "skill_instructions" and b.truncated for b in bounding_result.inputs
        ) else next(
            (b.content for b in bounding_result.inputs if b.name == "skill_instructions"), ""
        ),
        "agent_instructions": next(
            (b.content for b in bounding_result.inputs if b.name == "agent_instructions"),
            "",
        ),
        "artifact_inputs": artifact_inputs,
        "document_paths": document_paths,
        "token_budget": token_budget,
        "truncated": bounding_result.truncated,
        "truncation_events": bounding_result.truncation_events,
    }
