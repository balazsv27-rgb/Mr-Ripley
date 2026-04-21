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
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from governance.dag_runner.path_policy import PathPolicy

from governance.dag_runner.agent_resolver import (
    AgentResolverError,
    load_agent_file,
    resolve_agent,
    resolve_skill_content,
)
from governance.dag_runner.skill_resolver import SkillResolverError
from governance.dag_runner.input_bounding import (
    BoundedInput,
    bound_inputs,
    estimate_tokens,
)
from governance.dag_runner.models import (
    AgentSpec,
    AssembledWorkflowSpec,
    GovernanceRunState,
    PromptContext,
    WorkflowStep,
)


class PromptAssemblyError(RuntimeError):
    """Raised when prompt assembly fails."""


# Section delimiters for the assembled prompt text.
_SECTION_DELIM = "\n\n" + "=" * 60 + "\n"


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


def _validate_file_read(
    path: Path,
    path_policy: "PathPolicy | None",
) -> None:
    """Validate a file path against the active policy, if any.

    Raises ``PathPolicyViolation`` when the path violates the policy.
    No-op when ``path_policy is None`` (V2A backward compat / mock usage).
    """
    if path_policy is None:
        return
    from governance.dag_runner.path_policy import validate_path
    validate_path(path, path_policy)


def assemble_step_prompt(
    step: WorkflowStep,
    spec: AssembledWorkflowSpec,
    run_state: GovernanceRunState,
    repo_root: Path | None = None,
    token_budget: int = 100_000,
    path_policy: "PathPolicy | None" = None,
) -> dict[str, Any]:
    """Assemble bounded prompt context for a single workflow step.

    Returns a dict with:
      - ``agent``: resolved AgentSpec (or None)
      - ``skill_content``: concatenated SKILL.md content
      - ``agent_instructions``: agent .md file content
      - ``artifact_inputs``: upstream artifact payloads
      - ``document_paths``: resolved canonical doc paths
      - ``token_budget``: the budget
      - ``token_estimate``: estimated total token count after bounding
      - ``truncated``: whether any input was truncated
      - ``truncation_events``: list of truncation events (if any)

    When ``path_policy`` is provided, every file read is validated
    against the policy before reading.  Violations raise
    ``PathPolicyViolation`` (fail-closed).
    """
    if repo_root is None:
        repo_root = _get_repo_root()

    # Resolve agent
    agent = resolve_agent(step, spec)

    # Resolve skill content (path policy validated inside agent_resolver
    # at the skill_resolver level; we validate the resolved paths here)
    skill_content = ""
    if agent is not None:
        try:
            # Validate skill file paths before reading
            if path_policy is not None and agent.skill_bindings:
                for skill_name in agent.skill_bindings:
                    skill_path = repo_root / ".claude" / "skills" / skill_name / "SKILL.md"
                    _validate_file_read(skill_path, path_policy)
            skill_content = resolve_skill_content(agent, repo_root)
        except (AgentResolverError, SkillResolverError):
            skill_content = ""

    # Load agent instructions
    agent_instructions = ""
    if agent is not None:
        try:
            agent_path = repo_root / ".claude" / "agents" / f"{agent.name}.md"
            _validate_file_read(agent_path, path_policy)
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

    # Document content (read files with path policy validation)
    for doc_path in document_paths:
        try:
            resolved = Path(doc_path).resolve()
            _validate_file_read(resolved, path_policy)
            doc_content = resolved.read_text(encoding="utf-8")
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
        "step_name": step.name,
        "expected_outputs": list(step.outputs),
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
        "token_estimate": bounding_result.total_tokens,
        "truncated": bounding_result.truncated,
        "truncation_events": bounding_result.truncation_events,
    }


def build_prompt_composition_metadata(context: dict[str, Any]) -> dict[str, Any]:
    """Extract prompt composition metadata from an assembly context dict.

    Returns a flat dict of diagnostic fields suitable for inclusion in
    timeout debug artifacts and execution trace events.
    """
    artifact_inputs = context.get("artifact_inputs", {})
    document_paths = context.get("document_paths", [])
    return {
        "step_name": context.get("step_name", ""),
        "skill_content_length": len(context.get("skill_content", "")),
        "agent_instructions_length": len(context.get("agent_instructions", "")),
        "artifact_input_names": sorted(artifact_inputs.keys()),
        "artifact_input_count": len(artifact_inputs),
        "document_paths": list(document_paths),
        "document_count": len(document_paths),
        "token_estimate": context.get("token_estimate", 0),
        "token_budget": context.get("token_budget", 100_000),
        "truncated": context.get("truncated", False),
        "truncation_events": context.get("truncation_events", []),
        "expected_outputs": context.get("expected_outputs", []),
    }


def build_prompt_text(context: dict[str, Any]) -> str:
    """Build the assembled prompt text from a prompt assembly context dict.

    Concatenates sections in priority order with clear delimiters:
    1. Skill instructions (highest priority)
    2. Agent instructions
    3. Upstream artifact payloads (serialized JSON)
    4. Document content

    Each non-empty section is separated by a delimiter for parseability.
    """
    import json

    sections: list[str] = []

    skill = context.get("skill_content", "")
    if skill:
        sections.append(f"[SKILL INSTRUCTIONS]{_SECTION_DELIM}{skill}")

    agent_inst = context.get("agent_instructions", "")
    if agent_inst:
        sections.append(f"[AGENT INSTRUCTIONS]{_SECTION_DELIM}{agent_inst}")

    artifacts = context.get("artifact_inputs", {})
    if artifacts:
        art_text = json.dumps(artifacts, indent=2)
        sections.append(f"[UPSTREAM ARTIFACTS]{_SECTION_DELIM}{art_text}")

    doc_paths = context.get("document_paths", [])
    if doc_paths:
        sections.append(f"[DOCUMENT PATHS]{_SECTION_DELIM}" + "\n".join(doc_paths))

    # Output format specification — required for backend-dispatched steps
    expected_outputs = context.get("expected_outputs", [])
    step_name = context.get("step_name", "")
    if expected_outputs and step_name:
        artifact_examples = ", ".join(
            f'"{o}": {{"produced_by": "{step_name}", ...your analysis fields...}}'
            for o in expected_outputs
        )
        format_section = (
            f"[REQUIRED OUTPUT FORMAT]{_SECTION_DELIM}"
            f"CRITICAL: Your entire response must be a single valid JSON object and nothing else.\n"
            f"Do NOT include any text, explanation, or commentary before or after the JSON.\n"
            f"Do NOT wrap in markdown code fences.\n"
            f"Do NOT attempt to read files like ctx.json, governance_context.json, or any artifact files — "
            f"all upstream artifacts are already provided in the [UPSTREAM ARTIFACTS] section above.\n"
            f"Even if you cannot fully complete the analysis, you MUST still respond with ONLY the JSON object.\n\n"
            f"Required structure:\n"
            f'{{"artifacts": {{{artifact_examples}}}}}\n\n'
            f"Rules:\n"
            f'- Each artifact MUST be a JSON object with a "produced_by" field set to "{step_name}".\n'
            f"- Include your analysis results as additional fields within each artifact object.\n"
            f"- You must produce ALL of the listed artifacts: {', '.join(expected_outputs)}.\n"
            f"- The top-level response must be a single JSON object with one key: \"artifacts\".\n"
            f'- Artifact names must match exactly: {", ".join(expected_outputs)}.'
        )
        sections.append(format_section)

    return (_SECTION_DELIM).join(sections)


def build_prompt_context(context: dict[str, Any]) -> PromptContext:
    """Convert a prompt assembly dict to a ``PromptContext``."""
    return PromptContext(
        assembled_prompt=build_prompt_text(context),
        agent=context.get("agent"),
        skill_content=context.get("skill_content", ""),
        agent_instructions=context.get("agent_instructions", ""),
        artifact_inputs=context.get("artifact_inputs", {}),
        document_paths=context.get("document_paths", []),
        token_budget=context.get("token_budget", 100_000),
        token_estimate=context.get("token_estimate", 0),
        truncated=context.get("truncated", False),
        truncation_events=context.get("truncation_events", []),
    )
