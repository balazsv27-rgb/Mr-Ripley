"""
Shared artifact store for Mr. Ripley governance hooks.

Artifacts are resolved via the active-session pointer at:
    .claude/run/current_session.json

When the pointer exists, artifacts are read from/written to the session's
artifact directory.  When absent, falls back to the legacy flat directory
at .claude/run/artifacts/ for backward compatibility.

Envelope schema:
  {
    "artifact": "<name>",
    "produced_by": "<workflow step id>",
    "session": "<session_id>",
    "timestamp": "<iso8601>",
    "data": { ... }
  }

Hook scripts call read_artifact(name) to get the data block.
"""

import json
from pathlib import Path


# Resolved relative to the project root (two levels up from .claude/hooks/lib/)
_HOOKS_LIB_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _HOOKS_LIB_DIR.parent.parent.parent

# Legacy flat directory (backward compat)
ARTIFACT_DIR = _PROJECT_ROOT / ".claude" / "run" / "artifacts"

# Active-session pointer path
_POINTER_PATH = _PROJECT_ROOT / ".claude" / "run" / "current_session.json"


def _resolve_artifact_dir() -> Path:
    """Resolve the active session's artifact directory.

    Reads the session pointer file.  If it exists and points to a valid
    session directory, returns that session's ``artifacts/`` path.
    Otherwise falls back to the legacy flat directory.
    """
    if _POINTER_PATH.is_file():
        try:
            with _POINTER_PATH.open("r", encoding="utf-8") as f:
                pointer = json.load(f)
            session_dir = pointer.get("session_dir", "")
            if session_dir:
                candidate = Path(session_dir) / "artifacts"
                if candidate.is_dir():
                    return candidate
        except (json.JSONDecodeError, OSError, KeyError):
            pass
    return ARTIFACT_DIR


class ArtifactNotFound(Exception):
    """Raised when a required artifact file does not exist in the store."""


class ArtifactMalformed(Exception):
    """Raised when an artifact file exists but cannot be parsed or is missing the data block."""


def read_artifact(name: str) -> dict:
    """
    Read an artifact's data block by name.

    Resolves the active session directory via the pointer file, falling
    back to the legacy flat directory when no pointer is available.

    Raises:
        ArtifactNotFound  — file does not exist
        ArtifactMalformed — file exists but is not valid JSON or has no 'data' key
    """
    art_dir = _resolve_artifact_dir()
    path = art_dir / f"{name}.json"
    if not path.exists():
        raise ArtifactNotFound(
            f"Artifact '{name}' not found at {path}. "
            "The workflow step that produces this artifact may not have run yet."
        )
    try:
        with path.open("r", encoding="utf-8") as f:
            envelope = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        raise ArtifactMalformed(
            f"Artifact '{name}' at {path} could not be parsed: {exc}"
        ) from exc

    if "data" not in envelope:
        raise ArtifactMalformed(
            f"Artifact '{name}' at {path} is missing the required 'data' key."
        )

    return envelope["data"]


def artifact_exists(name: str) -> bool:
    """Return True if the artifact file exists in the store."""
    art_dir = _resolve_artifact_dir()
    return (art_dir / f"{name}.json").exists()


def write_artifact(name: str, data: dict, produced_by: str = "", session: str = "") -> None:
    """
    Write an artifact envelope to the store.

    Resolves the active session directory via the pointer file, falling
    back to the legacy flat directory when no pointer is available.
    Creates the artifact directory if it does not exist.
    """
    import datetime

    art_dir = _resolve_artifact_dir()
    art_dir.mkdir(parents=True, exist_ok=True)
    envelope = {
        "artifact": name,
        "produced_by": produced_by,
        "session": session,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "data": data,
    }
    path = art_dir / f"{name}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(envelope, f, indent=2)
