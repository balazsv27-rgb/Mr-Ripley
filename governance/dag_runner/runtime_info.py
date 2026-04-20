"""
runtime_info.py — Runtime provenance and backend execution context reporting.

Provides module-path self-reporting and backend isolation metadata so
operators can verify exactly which code files were imported and what
execution context the Claude CLI subprocess inherited.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any


_PROVENANCE_MODULES = (
    "governance",
    "governance.dag_runner.cli",
    "governance.dag_runner.executor",
    "governance.dag_runner.execution_backend",
    "governance.dag_runner.prompt_assembly",
    "governance.dag_runner.path_policy",
)


def build_runtime_provenance() -> dict[str, Any]:
    """Build runtime provenance metadata from the current process.

    Reports the Python executable, version, cwd, sys.path head, and
    the resolved file paths of critical governance modules.
    """
    module_files: dict[str, str | None] = {}
    for mod_name in _PROVENANCE_MODULES:
        mod = sys.modules.get(mod_name)
        if mod is None:
            module_files[mod_name] = None
        else:
            f = getattr(mod, "__file__", None)
            module_files[mod_name] = str(f) if f else None

    return {
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "cwd": os.getcwd(),
        "sys_path_head": sys.path[:5],
        "module_files": module_files,
    }


def build_backend_execution_context(
    *,
    backend: str,
    isolation_mode: str,
    subprocess_cwd: str,
    claude_command: str,
    tools_argument: str,
    model: str,
    isolation_limitations: list[str] | None = None,
) -> dict[str, Any]:
    """Build backend execution context metadata for diagnostics."""
    ctx: dict[str, Any] = {
        "backend": backend,
        "isolation_mode": isolation_mode,
        "subprocess_cwd": subprocess_cwd,
        "claude_command": claude_command,
        "tools_argument": tools_argument,
        "model": model,
    }
    if isolation_limitations:
        ctx["isolation_limitations"] = isolation_limitations
    return ctx


def get_isolated_cwd() -> str:
    """Return a neutral working directory for isolated backend execution.

    Uses the system temp directory — guaranteed to exist and to NOT
    contain .claude/settings.json or any repo-local Claude Code context.
    """
    return tempfile.gettempdir()
