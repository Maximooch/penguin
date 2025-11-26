"""
Path Utilities for Penguin Security.

Provides path normalization, validation, and security checks:
- Normalize paths (expand ~, resolve symlinks, make absolute)
- Detect path traversal attempts
- Check symlink escapes
- Validate paths against boundaries
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Set, Tuple


class PathSecurityError(Exception):
    """Raised when a path fails security validation."""
    pass


class PathTraversalError(PathSecurityError):
    """Raised when path traversal is detected."""
    pass


class SymlinkEscapeError(PathSecurityError):
    """Raised when a symlink points outside allowed boundaries."""
    pass


def normalize_path(
    path_str: str,
    base_dir: Optional[Path] = None,
    resolve_symlinks: bool = True,
) -> Path:
    """Normalize a path to an absolute, resolved form.
    
    Args:
        path_str: The path string to normalize
        base_dir: Base directory for relative paths (default: cwd)
        resolve_symlinks: Whether to resolve symlinks (default: True)
    
    Returns:
        Normalized absolute Path
    
    Raises:
        PathSecurityError: If path is invalid
    """
    if not path_str or not path_str.strip():
        raise PathSecurityError("Empty path")
    
    try:
        path = Path(path_str).expanduser()
        
        # Make absolute if relative
        if not path.is_absolute():
            base = base_dir or Path.cwd()
            path = base / path
        
        # Resolve symlinks and normalize
        if resolve_symlinks:
            return path.resolve()
        else:
            # Normalize without following symlinks
            return Path(os.path.normpath(str(path)))
            
    except (OSError, RuntimeError, ValueError) as e:
        raise PathSecurityError(f"Invalid path '{path_str}': {e}") from e


def detect_traversal(path_str: str) -> bool:
    """Detect path traversal patterns in a path string.
    
    Checks for:
    - .. components that escape directories
    - Null bytes (path truncation attacks)
    - Unusual encodings
    
    Args:
        path_str: The path string to check
    
    Returns:
        True if traversal patterns detected, False otherwise
    """
    if not path_str:
        return False
    
    # Check for null bytes (path truncation attack)
    if "\x00" in path_str:
        return True
    
    # Normalize and check for .. escapes
    parts = Path(path_str).parts
    depth = 0
    for part in parts:
        if part == "..":
            depth -= 1
            if depth < 0:
                # Escaped above starting directory
                return True
        elif part not in (".", "", "/", "\\"):
            depth += 1
    
    return False


def check_symlink_escape(
    path: Path,
    boundaries: List[Path],
    check_parents: bool = True,
) -> Optional[Path]:
    """Check if a path or its parents contain symlinks pointing outside boundaries.
    
    Args:
        path: The path to check
        boundaries: List of allowed boundary directories
        check_parents: Whether to check parent directories for symlinks
    
    Returns:
        The escaping symlink path if found, None otherwise
    """
    if not path.exists():
        return None
    
    paths_to_check = [path]
    if check_parents:
        paths_to_check.extend(path.parents)
    
    for p in paths_to_check:
        if p.is_symlink():
            try:
                target = p.resolve()
                if not is_within_any_boundary(target, boundaries):
                    return p
            except (OSError, RuntimeError):
                # Can't resolve - treat as suspicious
                return p
    
    return None


def is_within_boundary(path: Path, boundary: Path) -> bool:
    """Check if a path is within a boundary directory.
    
    Args:
        path: The path to check (should be resolved/absolute)
        boundary: The boundary directory
    
    Returns:
        True if path is within boundary, False otherwise
    """
    try:
        path.relative_to(boundary)
        return True
    except ValueError:
        return False


def is_within_any_boundary(path: Path, boundaries: List[Path]) -> bool:
    """Check if a path is within any of the boundary directories.
    
    Args:
        path: The path to check (should be resolved/absolute)
        boundaries: List of allowed boundary directories
    
    Returns:
        True if path is within any boundary, False otherwise
    """
    return any(is_within_boundary(path, b) for b in boundaries)


def validate_path_security(
    path_str: str,
    boundaries: List[Path],
    base_dir: Optional[Path] = None,
    allow_symlinks: bool = False,
) -> Path:
    """Validate a path for security concerns.
    
    Performs:
    1. Traversal detection
    2. Path normalization
    3. Boundary checking
    4. Symlink escape detection (if allow_symlinks=False)
    
    Args:
        path_str: The path to validate
        boundaries: List of allowed boundary directories
        base_dir: Base directory for relative paths
        allow_symlinks: Whether to allow symlinks
    
    Returns:
        Validated and normalized Path
    
    Raises:
        PathTraversalError: If path traversal detected
        SymlinkEscapeError: If symlink escapes boundaries
        PathSecurityError: For other security issues
    """
    # Check for traversal patterns
    if detect_traversal(path_str):
        raise PathTraversalError(f"Path traversal detected in '{path_str}'")
    
    # Normalize the path
    resolved = normalize_path(path_str, base_dir, resolve_symlinks=True)
    
    # Check symlinks
    if not allow_symlinks:
        escape_path = check_symlink_escape(resolved, boundaries)
        if escape_path:
            raise SymlinkEscapeError(
                f"Symlink '{escape_path}' points outside allowed boundaries"
            )
    
    # Check boundaries
    if not is_within_any_boundary(resolved, boundaries):
        raise PathSecurityError(
            f"Path '{resolved}' is outside allowed boundaries: {boundaries}"
        )
    
    return resolved


def get_safe_relative_path(
    path: Path,
    base: Path,
    fallback: str = "<external>",
) -> str:
    """Get a relative path, falling back to a safe representation if outside base.
    
    Useful for logging and display without exposing full paths.
    
    Args:
        path: The path to convert
        base: The base directory
        fallback: String to use if path is outside base
    
    Returns:
        Relative path string or fallback
    """
    try:
        return str(path.relative_to(base))
    except ValueError:
        return fallback


def sanitize_filename(filename: str, replacement: str = "_") -> str:
    """Sanitize a filename by removing/replacing dangerous characters.
    
    Args:
        filename: The filename to sanitize
        replacement: Character to replace dangerous chars with
    
    Returns:
        Sanitized filename
    """
    # Characters that are dangerous or reserved on various systems
    dangerous = set('/\\:*?"<>|\x00')
    
    result = []
    for char in filename:
        if char in dangerous or ord(char) < 32:
            result.append(replacement)
        else:
            result.append(char)
    
    sanitized = "".join(result)
    
    # Remove leading/trailing dots and spaces
    sanitized = sanitized.strip(". ")
    
    # Ensure not empty
    if not sanitized:
        sanitized = "unnamed"
    
    return sanitized

