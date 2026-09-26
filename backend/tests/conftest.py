"""Tests explicitly opt into local unauthenticated mode; deployments fail closed."""
import pytest


@pytest.fixture(autouse=True)
def local_api_environment(monkeypatch):
    monkeypatch.setenv("LIBEREYE_ALLOW_INSECURE", "1")
    monkeypatch.delenv("LIBEREYE_API_TOKEN", raising=False)
    from libereye.cloud_sessions import sessions
    sessions._sessions.clear()
    yield
    sessions._sessions.clear()
