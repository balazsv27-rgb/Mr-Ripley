"""Shared fixtures and path setup for layer2 unit tests."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root is on sys.path so `layer2` package is importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
