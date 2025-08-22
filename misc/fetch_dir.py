#!/usr/bin/env python3
import os
from pathlib import Path
from importlib import import_module

"""
This script is used to fetch the path to the config.yml file.

I should make a `penguin config` command that just opens the config.yml file in the default editor. A LOT simpler.
"""

def find_config_path() -> Path | None:
    paths = []

    # 1) Explicit env override
    env = os.getenv("PENGUIN_CONFIG_PATH")
    if env:
        paths.append(Path(env))

    # 2) User config (~/.config/penguin/config.yml on macOS/Linux)
    if os.name == "posix":
        config_base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    else:
        config_base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    paths.append(config_base / "penguin" / "config.yml")

    # 3) Dev repo config (project_root/penguin/config.yml)
    try:
        cfg = import_module("penguin.config")
        project_root = cfg.get_project_root()
        if not str(project_root).endswith(".penguin"):
            paths.append(project_root / "penguin" / "config.yml")
    except Exception:
        pass

    # 4) Package default (installed path)
    try:
        cfg_mod = import_module("penguin.config")
        paths.append(Path(cfg_mod.__file__).parent / "config.yml")
    except Exception:
        pass

    for p in paths:
        if p and p.exists():
            return p.resolve()
    return None

if __name__ == "__main__":
    p = find_config_path()
    if not p:
        print("No config.yml found.")
    else:
        print(str(p))
        print("dir:", str(p.parent))