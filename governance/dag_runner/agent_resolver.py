"""
agent_resolver.py — Resolve agent bindings and load agent/skill files.

Resolves workflow step ``agent_binding`` to an ``AgentSpec``, then
resolves ``skill_bindings`` to SKILL.md file content on disk.

Fails closed if a declared agent or skill file is not found.
"""
from __future__ import annotations

from pathlib import Path

from governance.dag_runner.models import (
    AgentSpec,
    AssembledWorkflowSpec,
    WorkflowStep,
)


class AgentResolverError(RuntimeError):
    """Raised when agent or skill resolution fails."""


def resolve_agent(
    step: WorkflowStep,
    spec: AssembledWorkflowSpec,
) -> AgentSpec | None:
    """Resolve a step's ``agent_binding`` to the corresponding ``AgentSpec``.

    Returns ``None`` if the step has no ``agent_binding`` field.
    Raises ``AgentResolverError`` if the binding references an unknown agent.
    """
    agent_name = step.raw.get("agent_binding")
    if agent_name is None:
        return None

    if not isinstance(agent_name, str) or not agent_name.strip():
        raise AgentResolverError(
            f"Step '{step.name}': agent_binding is not a valid string: {agent_name!r}"
        )

    agent_name = agent_name.strip()
    agent = spec.agents.get(agent_name)
    if agent is None:
        raise AgentResolverError(
            f"Step '{step.name}': agent_binding '{agent_name}' not found in spec.agents."
        )

    return agent


def load_agent_file(agent_name: str, repo_root: Path) -> str:
    """Load the agent markdown file from ``.claude/agents/<name>.md``.

    Returns the file content as a string.
    Raises ``AgentResolverError`` if the file does not exist.
    """
    agent_path = repo_root / ".claude" / "agents" / f"{agent_name}.md"
    if not agent_path.is_file():
        raise AgentResolverError(
            f"Agent file not found: {agent_path}"
        )

    return agent_path.read_text(encoding="utf-8")


def resolve_skill_content(
    agent: AgentSpec,
    repo_root: Path,
) -> str:
    """Load the SKILL.md content for the agent's first skill binding.

    Returns the concatenated content of all bound skill files.
    Returns an empty string if the agent has no skill bindings
    (e.g. audit-coordinator-agent).
    Raises ``AgentResolverError`` if a declared skill file is missing.
    """
    if not agent.skill_bindings:
        return ""

    from governance.dag_runner.skill_resolver import load_skill

    parts: list[str] = []
    for skill_name in agent.skill_bindings:
        parts.append(load_skill(skill_name, repo_root))

    return "\n\n".join(parts)
