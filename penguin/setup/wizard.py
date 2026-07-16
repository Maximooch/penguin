"""Workspace-first onboarding for Penguin."""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

import questionary
import yaml
from rich.console import Console

console = Console()

STYLE = questionary.Style(
    [
        ("qmark", "fg:cyan bold"),
        ("question", "fg:white bold"),
        ("answer", "fg:cyan bold"),
        ("pointer", "fg:cyan bold"),
        ("highlighted", "fg:cyan bold"),
        ("selected", "fg:green"),
        ("instruction", "fg:white"),
        ("text", "fg:white"),
        ("disabled", "fg:gray italic"),
    ]
)

WORKSPACE_DIRS = [
    "conversations",
    "memory_db",
    "logs",
    "notes",
    "projects",
    "context",
]

PROVIDERS: dict[str, dict[str, Any]] = {
    "OpenAI": {
        "id": "openai",
        "env": "OPENAI_API_KEY",
        "models": ["gpt-5.2", "gpt-5.1", "gpt-4.1"],
    },
    "Anthropic": {
        "id": "anthropic",
        "env": "ANTHROPIC_API_KEY",
        "models": ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"],
    },
    "OpenRouter": {
        "id": "openrouter",
        "env": "OPENROUTER_API_KEY",
        "client_preference": "openrouter",
        "models": [
            "openai/gpt-5.2",
            "anthropic/claude-sonnet-4-5",
            "google/gemini-3-pro-preview",
        ],
    },
    "Ollama (local)": {
        "id": "ollama",
        "env": None,
        "models": ["qwen3-coder", "gpt-oss:20b", "llama3.3"],
    },
}


def check_setup_dependencies() -> tuple[bool, list[str]]:
    required_packages = {
        "questionary": "questionary",
        "yaml": "PyYAML",
        "rich": "rich",
    }
    missing: list[str] = []
    for module_name, package_name in required_packages.items():
        try:
            __import__(module_name)
        except ImportError:
            missing.append(package_name)
    return not missing, missing


def display_dependency_install_instructions(missing_packages: list[str]) -> None:
    console.print("[bold red]Missing setup dependencies.[/bold red]")
    console.print(f"[yellow]Install:[/yellow] pip install {' '.join(missing_packages)}")


def _user_config_dir() -> Path:
    if os.name == "posix":
        return (
            Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "penguin"
        )
    return (
        Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "penguin"
    )


def get_config_path() -> Path:
    override = os.environ.get("PENGUIN_CONFIG_PATH")
    if override:
        return Path(override).expanduser()
    return _user_config_dir() / "config.yml"


def _setup_complete_path() -> Path:
    return get_config_path().parent / ".penguin_setup_complete"


def _load_config() -> dict[str, Any]:
    path = get_config_path()
    if not path.exists():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def check_config_completeness() -> bool:
    """Return whether required workspace onboarding is complete.

    Connecting an AI model and credential is optional and must not gate startup.
    """
    workspace = _load_config().get("workspace")
    if not isinstance(workspace, dict):
        return False
    raw_path = str(workspace.get("path", "")).strip()
    return bool(raw_path) and _workspace_ready(Path(raw_path).expanduser())


def check_provider_ready(config: dict[str, Any] | None = None) -> bool:
    config = config or _load_config()
    model = config.get("model")
    if not isinstance(model, dict):
        return False
    provider = str(model.get("provider", "")).strip().lower()
    model_id = str(model.get("default", "")).strip()
    if not provider or not model_id:
        return False
    if provider in {"ollama", "local"}:
        return True
    env_names = {
        "openai": ("OPENAI_API_KEY", "OPENAI_OAUTH_ACCESS_TOKEN"),
        "anthropic": ("ANTHROPIC_API_KEY",),
        "openrouter": ("OPENROUTER_API_KEY",),
        "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
        "mistral": ("MISTRAL_API_KEY",),
        "deepseek": ("DEEPSEEK_API_KEY",),
    }.get(provider, ())
    return any(str(os.getenv(name) or "").strip() for name in env_names)


def check_first_run() -> bool:
    # Existing workspace configs are onboarded even if they predate the marker.
    return not check_config_completeness()


def mark_setup_complete() -> None:
    path = _setup_complete_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    user = os.getenv("USERNAME") or os.getenv("USER", "user")
    path.write_text(
        f"Setup completed on {user}@{platform.node()} at {platform.system()}\n",
        encoding="utf-8",
    )


def _persist_api_key(provider: str, api_key: str) -> bool:
    try:
        env_dir = _user_config_dir()
        env_dir.mkdir(parents=True, exist_ok=True)
        env_path = env_dir / ".env"
        existing = (
            env_path.read_text(encoding="utf-8").splitlines()
            if env_path.exists()
            else []
        )
        key = f"{provider.upper()}_API_KEY"
        line = f"{key}={api_key}"
        for index, current in enumerate(existing):
            if current.startswith(f"{key}="):
                existing[index] = line
                break
        else:
            existing.append(line)
        env_path.touch(mode=0o600, exist_ok=True)
        os.chmod(env_path, 0o600)
        env_path.write_text("\n".join(existing) + "\n", encoding="utf-8")
        os.chmod(env_path, 0o600)
        os.environ[key] = api_key
        return True
    except OSError:
        return False


def save_config(config: dict[str, Any]) -> Path | None:
    path = get_config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        return path
    except OSError as exc:
        console.print(f"[bold red]Could not save configuration:[/bold red] {exc}")
        return None


def _workspace_ready(path: Path) -> bool:
    """Return whether an existing workspace is a writable directory."""
    return path.exists() and path.is_dir() and os.access(path, os.W_OK | os.X_OK)


def _validate_workspace(value: str) -> bool | str:
    raw = str(value or "").strip()
    if not raw:
        return "Workspace location is required"
    path = Path(raw).expanduser()
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".penguin-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return f"Penguin cannot write to this location: {exc}"
    return True


def _create_workspace(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for directory in WORKSPACE_DIRS:
        (path / directory).mkdir(parents=True, exist_ok=True)


async def _optional_model_setup(config: dict[str, Any]) -> None:
    choice = await questionary.select(
        "Connect an AI model?",
        choices=["Connect now", "Skip for now"],
        default="Connect now",
        style=STYLE,
    ).ask_async()
    if choice != "Connect now":
        # Fresh installs need an explicit empty model section so lower-precedence
        # package defaults cannot silently reconnect OpenRouter. On reruns, Skip
        # means "leave my current connection unchanged."
        config.setdefault("model", None)
        console.print(
            "[dim]Skipped. Run 'penguin config setup' to connect a model later.[/dim]"
        )
        return

    provider_choices = [*PROVIDERS, "Skip for now"]
    provider_label = await questionary.select(
        "Choose a provider:", choices=provider_choices, style=STYLE
    ).ask_async()
    if provider_label not in PROVIDERS:
        config.setdefault("model", None)
        return
    provider = PROVIDERS[provider_label]

    model_choices = [*provider["models"], "Custom model", "Skip for now"]
    model = await questionary.select(
        "Choose a model:", choices=model_choices, style=STYLE
    ).ask_async()
    if model == "Skip for now" or model is None:
        config.setdefault("model", None)
        return
    if model == "Custom model":
        model = await questionary.text(
            "Model identifier:",
            validate=lambda value: bool(str(value).strip())
            or "Model identifier is required",
            style=STYLE,
        ).ask_async()
        if model is None:
            config.setdefault("model", None)
            return

    config["model"] = {
        "default": str(model).strip(),
        "provider": provider["id"],
        "client_preference": provider.get("client_preference", "native"),
        "streaming_enabled": True,
        "temperature": 0.7,
    }

    env_name = provider["env"]
    if not env_name or os.getenv(env_name):
        if env_name:
            console.print(f"[green]Found {env_name} in the environment.[/green]")
        return
    credential_choice = await questionary.select(
        "Add a credential now?",
        choices=["Enter credential", "Skip for now"],
        default="Enter credential",
        style=STYLE,
    ).ask_async()
    if credential_choice != "Enter credential":
        console.print(f"[dim]Set {env_name} before sending a prompt.[/dim]")
        return
    api_key = await questionary.password(
        f"Enter {env_name}:",
        validate=lambda value: bool(str(value).strip()) or "Credential cannot be empty",
        style=STYLE,
    ).ask_async()
    if api_key and not _persist_api_key(provider["id"], str(api_key).strip()):
        console.print(
            f"[yellow]Could not save the credential. Set {env_name} manually.[/yellow]"
        )


async def run_setup_wizard() -> dict[str, Any]:
    """Run workspace-first onboarding; connecting an AI model is optional."""
    console.print("\n[bold cyan]Penguin setup[/bold cyan]")
    console.print(
        "Penguin needs a workspace for projects, conversations, memory, and logs. "
        "Connecting an AI model is optional.\n"
    )

    existing = _load_config()
    existing_workspace = (
        existing.get("workspace") if isinstance(existing.get("workspace"), dict) else {}
    )
    default_workspace = str(
        existing_workspace.get("path") or Path.home() / "penguin_workspace"
    )
    workspace_input = await questionary.text(
        "Workspace location:",
        default=default_workspace,
        validate=_validate_workspace,
        style=STYLE,
    ).ask_async()
    if workspace_input is None:
        return {"error": "Setup interrupted"}
    workspace_path = Path(str(workspace_input).strip()).expanduser().resolve()

    config = dict(existing)
    config["workspace"] = {
        **existing_workspace,
        "path": str(workspace_path),
        "create_dirs": WORKSPACE_DIRS,
    }
    await _optional_model_setup(config)

    try:
        _create_workspace(workspace_path)
    except OSError as exc:
        return {"error": f"Could not initialize workspace: {exc}"}
    saved = save_config(config)
    if saved is None:
        return {"error": "Failed to save configuration"}
    mark_setup_complete()

    console.print("\n[bold green]Penguin is ready.[/bold green]")
    console.print(f"Workspace: [cyan]{workspace_path}[/cyan]")
    model = config.get("model")
    if isinstance(model, dict) and model.get("default"):
        console.print(f"AI model: [cyan]{model['default']}[/cyan]")
        if not check_provider_ready(config):
            console.print(
                "[yellow]A credential is still needed before sending AI "
                "prompts.[/yellow]"
            )
    else:
        console.print("AI model: [dim]Not connected[/dim]")
        console.print("Run [cyan]penguin config setup[/cyan] whenever you are ready.")
    console.print(f"[dim]Configuration saved to {saved}[/dim]\n")
    return config


def test_provider_routing() -> None:
    """Print the provider/runtime mapping used by onboarding choices."""
    console.print("[bold cyan]Provider routing[/bold cyan]")
    for label, provider in PROVIDERS.items():
        preference = provider.get("client_preference", "native")
        console.print(
            f"{label}: provider={provider['id']}, client_preference={preference}"
        )


def open_in_default_editor(file_path: Path) -> bool:
    try:
        if platform.system() == "Windows":
            os.startfile(file_path)  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.run(["open", str(file_path)], check=True)
        else:
            if shutil.which("xdg-open") is None:
                return False
            subprocess.run(["xdg-open", str(file_path)], check=True)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def run_setup_wizard_sync() -> dict[str, Any]:
    deps_available, missing = check_setup_dependencies()
    if not deps_available:
        display_dependency_install_instructions(missing)
        return {"error": f"Missing dependencies: {', '.join(missing)}"}
    try:
        return asyncio.run(run_setup_wizard())
    except KeyboardInterrupt:
        console.print("\n[yellow]Setup interrupted.[/yellow]")
        return {"error": "Setup interrupted"}
    except Exception as exc:
        console.print(f"[red]Setup wizard error: {exc}[/red]")
        return {"error": str(exc)}
