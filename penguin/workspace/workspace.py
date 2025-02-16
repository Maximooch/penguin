import os

from config import WORKSPACE_PATH


def ensure_workspace_exists():
    """Ensure that the workspace directory exists."""
    os.makedirs(WORKSPACE_PATH, exist_ok=True)


def get_workspace_path(*paths):
    """Get the full path within the workspace."""
    return os.path.join(WORKSPACE_PATH, *paths)


def list_workspace_contents():
    """List all files and directories in the workspace."""
    return os.listdir(WORKSPACE_PATH)


def create_workspace_directory(directory):
    """Create a new directory in the workspace."""
    full_path = get_workspace_path(directory)
    os.makedirs(full_path, exist_ok=True)
    return full_path


def create_workspace_file(file_path, content=""):
    """Create a new file in the workspace with optional content."""
    full_path = get_workspace_path(file_path)
    with open(full_path, "w") as f:
        f.write(content)
    return full_path


def read_workspace_file(file_path):
    """Read the contents of a file in the workspace."""
    full_path = get_workspace_path(file_path)
    with open(full_path) as f:
        return f.read()


def write_workspace_file(file_path, content):
    """Write content to a file in the workspace."""
    full_path = get_workspace_path(file_path)
    with open(full_path, "w") as f:
        f.write(content)
    return full_path
