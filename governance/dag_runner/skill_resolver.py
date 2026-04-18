"""
skill_resolver.py — Load SKILL.md files by name.

Loads skill definitions from ``.claude/skills/<name>/SKILL.md``.
Caches loaded content for reuse across steps.
"""
from __future__ import annotations

from pathlib import Path

from governance.dag_runner.models import AssembledWorkflowSpec


class SkillResolverError(RuntimeError):
    """Raised when a skill file cannot be loaded."""


_cache: dict[str, str] = {}


def load_skill(name: str, repo_root: Path) -> str:
    """Load a single SKILL.md file by skill name.

    Returns the file content as a string.
    Raises ``SkillResolverError`` if the file does not exist.
    """
    cache_key = f"{repo_root}::{name}"
    if cache_key in _cache:
        return _cache[cache_key]

    skill_path = repo_root / ".claude" / "skills" / name / "SKILL.md"
    if not skill_path.is_file():
        raise SkillResolverError(
            f"Skill file not found: {skill_path}"
        )

    content = skill_path.read_text(encoding="utf-8")
    _cache[cache_key] = content
    return content


def load_all_skills(
    spec: AssembledWorkflowSpec,
    repo_root: Path,
) -> dict[str, str]:
    """Load all declared skills from the assembled spec.

    Returns a dict mapping skill name to SKILL.md content.
    Raises ``SkillResolverError`` if any declared skill file is missing.
    """
    result: dict[str, str] = {}
    for skill_name in spec.skills:
        result[skill_name] = load_skill(skill_name, repo_root)
    return result


def clear_cache() -> None:
    """Clear the skill content cache (useful in tests)."""
    _cache.clear()
