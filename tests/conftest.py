import asyncio
import os
import sys
from pathlib import Path

import pytest

pytest_plugins = ("pytest_asyncio",)

_AMBIENT_PROVIDER_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GITHUB_TOKEN",
    "GOOGLE_API_KEY",
    "OPENAI_ACCOUNT_ID",
    "OPENAI_API_KEY",
    "OPENAI_OAUTH_ACCESS_TOKEN",
    "OPENAI_OAUTH_EXPIRES_AT_MS",
    "OPENAI_OAUTH_REFRESH_TOKEN",
    "OPENROUTER_API_KEY",
)

# Ensure a writable workspace early to avoid import-time logging failures
_ws = Path(
    os.environ.get(
        "PENGUIN_WORKSPACE",
        str(Path(__file__).resolve().parent.parent / "tmp_workspace"),
    )
)
os.environ.setdefault("PENGUIN_WORKSPACE", str(_ws))
_ws.mkdir(parents=True, exist_ok=True)

# Add the project's root source directory ('penguin/') to the Python path
# so that tests can perform absolute imports like 'from penguin.agent import ...'
# This is executed by pytest before it collects any tests.
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture
def event_loop():
    """Compatibility fixture for legacy tests on pytest-asyncio 1.x."""
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


@pytest.fixture(autouse=True)
def isolate_provider_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep default tests independent from developer/provider credentials."""
    for env_name in _AMBIENT_PROVIDER_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setenv(
        "PENGUIN_PROVIDER_CREDENTIALS_STORE",
        str(tmp_path / "provider_credentials.json"),
    )
    monkeypatch.setenv(
        "PENGUIN_PROVIDER_AUTH_STORE",
        str(tmp_path / "provider_auth.json"),
    )
