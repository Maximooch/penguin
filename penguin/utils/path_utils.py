# This file isn't being used for anything, yet; maybe never.

# In penguin/utils/path_utils.py (create this file)
import os
from config import WORKSPACE_PATH

def normalize_path(path):
    # Remove any leading slashes or backslashes
    path = path.lstrip('/\\')
    # Remove 'workspace/' prefix if present
    if path.startswith('workspace/'):
        path = path[len('workspace/'):]
    # Normalize the path to prevent directory traversal
    full_path = os.path.normpath(os.path.join(WORKSPACE_PATH, path))
    # Security check
    if not full_path.startswith(os.path.abspath(WORKSPACE_PATH)):
        raise ValueError("Attempted to access a file outside of the workspace.")
    return full_path