from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from pathlib import Path

from penguin.setup import wizard


def test_workspace_only_config_is_complete(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump({"workspace": {"path": str(tmp_path / "workspace")}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PENGUIN_CONFIG_PATH", str(config_path))

    assert wizard.check_config_completeness() is True
    assert wizard.check_first_run() is False


class _Prompt:
    def __init__(self, answer):
        self.answer = answer

    async def ask_async(self):
        return self.answer


def test_onboarding_can_skip_ai_without_openrouter_or_model_config(
    monkeypatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.yml"
    workspace_path = tmp_path / "workspace"
    monkeypatch.setenv("PENGUIN_CONFIG_PATH", str(config_path))
    monkeypatch.setattr(
        wizard.questionary,
        "text",
        lambda *args, **kwargs: _Prompt(str(workspace_path)),
    )
    monkeypatch.setattr(
        wizard.questionary,
        "select",
        lambda *args, **kwargs: _Prompt("Skip for now"),
        raising=False,
    )

    result = wizard.run_setup_wizard_sync()

    assert "error" not in result
    assert result["workspace"]["path"] == str(workspace_path.resolve())
    assert result["model"] is None
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved["model"] is None
    assert (config_path.parent / ".penguin_setup_complete").exists()
    for directory in wizard.WORKSPACE_DIRS:
        assert (workspace_path / directory).is_dir()


def test_onboarding_skip_ai_overrides_inherited_default_model(
    monkeypatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.yml"
    workspace_path = tmp_path / "workspace"
    monkeypatch.setenv("PENGUIN_CONFIG_PATH", str(config_path))
    monkeypatch.setattr(
        wizard.questionary,
        "text",
        lambda *args, **kwargs: _Prompt(str(workspace_path)),
    )
    monkeypatch.setattr(
        wizard.questionary,
        "select",
        lambda *args, **kwargs: _Prompt("Skip for now"),
    )

    result = wizard.run_setup_wizard_sync()

    assert result["model"] is None
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved["model"] is None


def test_optional_model_setup_uses_provider_runtime_mapping(monkeypatch) -> None:
    answers = iter(["Connect now", "OpenRouter", "openai/gpt-5.2", "Skip for now"])
    monkeypatch.setattr(
        wizard.questionary,
        "select",
        lambda *args, **kwargs: _Prompt(next(answers)),
    )
    config: dict = {}

    import asyncio

    asyncio.run(wizard._optional_model_setup(config))

    assert config["model"]["provider"] == "openrouter"
    assert config["model"]["client_preference"] == "openrouter"


def test_rerunning_onboarding_preserves_existing_config_and_workspace_default(
    monkeypatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.yml"
    workspace_path = tmp_path / "existing-workspace"
    config_path.write_text(
        yaml.safe_dump(
            {
                "workspace": {"path": str(workspace_path), "custom": "keep"},
                "diagnostics": {"enabled": True},
                "model": None,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PENGUIN_CONFIG_PATH", str(config_path))
    seen_defaults: list[str] = []

    def _text(*args, **kwargs):
        seen_defaults.append(kwargs.get("default"))
        return _Prompt(kwargs.get("default"))

    monkeypatch.setattr(wizard.questionary, "text", _text)
    monkeypatch.setattr(
        wizard.questionary,
        "select",
        lambda *args, **kwargs: _Prompt("Skip for now"),
    )

    result = wizard.run_setup_wizard_sync()

    assert seen_defaults == [str(workspace_path)]
    assert result["workspace"]["custom"] == "keep"
    assert result["diagnostics"] == {"enabled": True}
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved["diagnostics"] == {"enabled": True}
    assert saved["workspace"]["custom"] == "keep"


def test_rerunning_onboarding_skip_preserves_existing_model(
    monkeypatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.yml"
    workspace_path = tmp_path / "existing-workspace"
    existing_model = {
        "default": "gpt-5.2",
        "provider": "openai",
        "client_preference": "native",
    }
    config_path.write_text(
        yaml.safe_dump(
            {
                "workspace": {"path": str(workspace_path)},
                "model": existing_model,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PENGUIN_CONFIG_PATH", str(config_path))
    monkeypatch.setattr(
        wizard.questionary,
        "text",
        lambda *args, **kwargs: _Prompt(kwargs.get("default")),
    )
    monkeypatch.setattr(
        wizard.questionary,
        "select",
        lambda *args, **kwargs: _Prompt("Skip for now"),
    )

    result = wizard.run_setup_wizard_sync()

    assert result["model"] == existing_model
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved["model"] == existing_model


def test_persist_api_key_preserves_existing_env_entries(
    monkeypatch, tmp_path: Path
) -> None:
    config_home = tmp_path / "config"
    env_path = config_home / "penguin" / ".env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text("OTHER_SETTING=keep\nOPENAI_API_KEY=old\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert wizard._persist_api_key("openai", "new-secret") is True

    assert env_path.read_text(encoding="utf-8").splitlines() == [
        "OTHER_SETTING=keep",
        "OPENAI_API_KEY=new-secret",
    ]
    assert wizard.os.environ["OPENAI_API_KEY"] == "new-secret"
