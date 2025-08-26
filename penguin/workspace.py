"""Deprecated workspace helpers.

Use WORKSPACE_PATH from `penguin.config` and guarded file ops in
`penguin.tools.core.support` instead.
"""

import os
from pathlib import Path

from penguin.config import WORKSPACE_PATH


def ensure_workspace_exists() -> None:
    Path(WORKSPACE_PATH).mkdir(parents=True, exist_ok=True)


def get_workspace_path(*paths) -> str:
    return str(Path(WORKSPACE_PATH, *paths))


def list_workspace_contents():
    return os.listdir(WORKSPACE_PATH)


def create_workspace_directory(directory):
    full_path = Path(WORKSPACE_PATH, directory)
    full_path.mkdir(parents=True, exist_ok=True)
    return str(full_path)


def create_workspace_file(file_path, content=""):
    full_path = Path(WORKSPACE_PATH, file_path)
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content, encoding="utf-8")
    return str(full_path)


def read_workspace_file(file_path):
    full_path = Path(WORKSPACE_PATH, file_path)
    return full_path.read_text(encoding="utf-8")


def write_workspace_file(file_path, content):
    full_path = Path(WORKSPACE_PATH, file_path)
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content, encoding="utf-8")
    return str(full_path)
