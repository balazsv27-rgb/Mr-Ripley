"""Shared fixtures for governance DAG runner tests."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_sessions(tmp_path, monkeypatch):
    """Route all session creation to tmp_path to avoid polluting the repo."""
    monkeypatch.setattr(
        "governance.dag_runner.session._DEFAULT_SESSIONS_BASE",
        tmp_path / "sessions",
    )
    monkeypatch.setattr(
        "governance.dag_runner.session._DEFAULT_POINTER_PATH",
        tmp_path / "current_session.json",
    )
