"""
path_policy.py — Path-bounded file access enforcement.

Validates that prompt assembly reads ONLY files within an explicitly
allowed set of paths.  Violations raise ``PathPolicyViolation`` and
propagate as fail-closed step failures.

This is assembly-time enforcement only.  The CLI backend receives
text on stdin and has zero file access.  TAPM runtime enforcement
(V2C) requires a separate ``ToolCallInterceptor``.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path


class PathPolicyViolation(RuntimeError):
    """Raised when a file path violates the active path policy."""


@dataclass(frozen=True)
class PathPolicy:
    """Declarative policy for allowed/denied file access during prompt assembly."""

    allowed_roots: list[Path] = field(default_factory=list)
    allowed_patterns: list[str] = field(default_factory=list)
    denied_patterns: list[str] = field(default_factory=list)
    max_file_size_bytes: int = 1_048_576  # 1 MB


def validate_path(path: Path, policy: PathPolicy) -> None:
    """Validate a file path against the policy.

    Raises ``PathPolicyViolation`` if the path is not allowed.

    Checks in order (fail-closed):
    1. Path must resolve to a location under an allowed root.
    2. Path must NOT match any denied pattern.
    3. Path must match at least one allowed pattern.
    4. If the file exists, it must not exceed ``max_file_size_bytes``.
    """
    resolved = path.resolve()

    # 1. Must be under an allowed root
    under_root = any(
        _is_under(resolved, root.resolve()) for root in policy.allowed_roots
    )
    if not under_root:
        raise PathPolicyViolation(
            f"Path outside allowed roots: {resolved}"
        )

    # 2. Must not match denied patterns (check against relative path from root)
    rel_path = _relative_to_any_root(resolved, policy.allowed_roots)
    rel_str = str(rel_path).replace("\\", "/")
    for pattern in policy.denied_patterns:
        if fnmatch.fnmatch(rel_str, pattern):
            raise PathPolicyViolation(
                f"Path matches denied pattern '{pattern}': {rel_str}"
            )
        # Also check the filename alone for simple patterns
        if fnmatch.fnmatch(resolved.name, pattern):
            raise PathPolicyViolation(
                f"Filename matches denied pattern '{pattern}': {resolved.name}"
            )

    # 3. Must match at least one allowed pattern
    matched = any(
        fnmatch.fnmatch(rel_str, pattern)
        for pattern in policy.allowed_patterns
    )
    if not matched:
        raise PathPolicyViolation(
            f"Path does not match any allowed pattern: {rel_str}"
        )

    # 4. File size check (only if file exists)
    if resolved.is_file():
        try:
            size = resolved.stat().st_size
            if size > policy.max_file_size_bytes:
                raise PathPolicyViolation(
                    f"File exceeds max size ({size} > {policy.max_file_size_bytes}): "
                    f"{resolved}"
                )
        except OSError:
            pass


def default_governance_policy(repo_root: Path) -> PathPolicy:
    """Return the standard V2B governance path policy.

    Allowed:
    - ``.claude/agents/<name>.md`` — agent instruction files
    - ``.claude/skills/<name>/SKILL.md`` — skill instruction files
    - ``*.md`` in repo root — canonical documents
    - ``Documentation/*.md`` — documentation files

    Denied (always blocked):
    - ``.env``, ``*.key``, ``*.pem``, ``*.secret`` — credentials
    - ``.git/**`` — git internals
    - ``**/__pycache__/**`` — cache
    - ``node_modules/**``, ``venv/**``, ``.venv/**`` — dependency dirs
    """
    return PathPolicy(
        allowed_roots=[repo_root.resolve()],
        allowed_patterns=[
            ".claude/agents/*.md",
            ".claude/skills/*/SKILL.md",
            "*.md",
            "Documentation/*.md",
            # Layer-2 code (read-only evidence for governance inspection)
            "layer2/*.py",
            "layer2/adapters/*.py",
            "layer2/config/*.json",
            "layer2/config/*.py",
            # Runtime metadata
            "latest_snapshot.json",
            # Workflow packages (governance self-inspection)
            ".claude/workflows/packages/*.yaml",
        ],
        denied_patterns=[
            ".env",
            "*.key",
            "*.pem",
            "*.secret",
            ".git/*",
            "**/__pycache__/**",
            "node_modules/*",
            "venv/*",
            ".venv/*",
        ],
        max_file_size_bytes=1_048_576,
    )


def _is_under(path: Path, root: Path) -> bool:
    """Check if path is under root (resolved)."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _relative_to_any_root(path: Path, roots: list[Path]) -> Path:
    """Get relative path from the first matching root."""
    resolved = path.resolve()
    for root in roots:
        r = root.resolve()
        try:
            return resolved.relative_to(r)
        except ValueError:
            continue
    return resolved
