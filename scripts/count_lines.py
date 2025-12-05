#!/usr/bin/env python
"""
Count lines of code in Penguin core.

Excludes:
- .gitignore patterns
- docs, misc, errors_log, __pycache__, node_modules
- Non-code files (images, binaries, etc.)
"""

import os
import fnmatch
from pathlib import Path
from collections import defaultdict

# Root directory to analyze
PENGUIN_CORE = Path(__file__).parent.parent / "penguin"

# Directories to always exclude
EXCLUDE_DIRS = {
    "__pycache__",
    "node_modules",
    "docs",
    "misc",
    "errors_log",
    ".git",
    ".venv",
    "venv",
    "env",
    ".env",
    "dist",
    "build",
    ".eggs",
    "eggs",
    ".pytest_cache",
    ".ruff_cache",
    ".vscode",
    ".idea",
    "junkdrawer",
    "hold",
    "testing",
    "logs",
    "embeddings",
    ".workspace",
    "example",
    "codeact",
    "notes",
    "reference",
    "ignore",
    ".crush",
    ".claude",
    "ct1",
    "chroma_test",
    "penguin_workspace",
}

# File patterns to exclude
EXCLUDE_PATTERNS = {
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.so",
    "*.dll",
    "*.exe",
    "*.o",
    "*.class",
    "*.egg",
    "*.egg-info",
    "*.log",
    "*.sql",
    "*.sqlite",
    "*.bak",
    "*.swp",
    "*~",
    ".DS_Store",
    "Thumbs.db",
    "*.jpg",
    "*.jpeg",
    "*.png",
    "*.gif",
    "*.ico",
    "*.svg",
    "*.mp4",
    "*.wav",
    "*.mp3",
    "uv.lock",
    "*.sublime-project",
    "*.sublime-workspace",
    ".aider*",
    "session_*.json",
    "cwm*.json",
    "cwm_turns.csv",
    ".penguin_setup_complete",
    ".gitignore",
}

# Code file extensions we care about
CODE_EXTENSIONS = {
    ".py": "Python",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
    ".md": "Markdown",
    ".txt": "Text",
    ".sh": "Shell",
    ".html": "HTML",
    ".css": "CSS",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (React)",
    ".jsx": "JavaScript (React)",
}


def should_exclude_file(filename: str) -> bool:
    """Check if file should be excluded based on patterns."""
    for pattern in EXCLUDE_PATTERNS:
        if fnmatch.fnmatch(filename, pattern):
            return True
    return False


def should_exclude_dir(dirname: str) -> bool:
    """Check if directory should be excluded."""
    return dirname in EXCLUDE_DIRS or dirname.startswith(".")


def count_lines(filepath: Path) -> tuple[int, int, int]:
    """
    Count lines in a file.
    
    Returns:
        Tuple of (total_lines, code_lines, blank_lines)
    """
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except (IOError, OSError):
        return 0, 0, 0
    
    total = len(lines)
    blank = sum(1 for line in lines if not line.strip())
    code = total - blank
    
    return total, code, blank


def analyze_directory(root_path: Path) -> dict:
    """
    Analyze a directory and count lines of code.
    
    Returns:
        Dictionary with analysis results.
    """
    results = {
        "by_extension": defaultdict(lambda: {"files": 0, "total": 0, "code": 0, "blank": 0}),
        "by_directory": defaultdict(lambda: {"files": 0, "total": 0, "code": 0, "blank": 0}),
        "files": [],
        "totals": {"files": 0, "total": 0, "code": 0, "blank": 0},
    }
    
    for dirpath, dirnames, filenames in os.walk(root_path):
        # Filter out excluded directories (modifies in place to prevent descending)
        dirnames[:] = [d for d in dirnames if not should_exclude_dir(d)]
        
        rel_dir = Path(dirpath).relative_to(root_path)
        top_level_dir = str(rel_dir).split(os.sep)[0] if str(rel_dir) != "." else "root"
        
        for filename in filenames:
            if should_exclude_file(filename):
                continue
            
            filepath = Path(dirpath) / filename
            ext = filepath.suffix.lower()
            
            # Only count recognized code files
            if ext not in CODE_EXTENSIONS:
                continue
            
            total, code, blank = count_lines(filepath)
            
            # Update by extension
            results["by_extension"][ext]["files"] += 1
            results["by_extension"][ext]["total"] += total
            results["by_extension"][ext]["code"] += code
            results["by_extension"][ext]["blank"] += blank
            
            # Update by directory
            results["by_directory"][top_level_dir]["files"] += 1
            results["by_directory"][top_level_dir]["total"] += total
            results["by_directory"][top_level_dir]["code"] += code
            results["by_directory"][top_level_dir]["blank"] += blank
            
            # Update totals
            results["totals"]["files"] += 1
            results["totals"]["total"] += total
            results["totals"]["code"] += code
            results["totals"]["blank"] += blank
            
            # Track individual files (for top files report)
            results["files"].append({
                "path": str(filepath.relative_to(root_path)),
                "ext": ext,
                "total": total,
                "code": code,
            })
    
    return results


def print_report(results: dict, root_path: Path) -> None:
    """Print a formatted report of the analysis."""
    
    print("\n" + "=" * 70)
    print(f"  PENGUIN CORE LINES OF CODE ANALYSIS")
    print(f"  Path: {root_path}")
    print("=" * 70)
    
    # Summary
    t = results["totals"]
    print(f"\n{'SUMMARY':^70}")
    print("-" * 70)
    print(f"  Total Files:        {t['files']:>10,}")
    print(f"  Total Lines:        {t['total']:>10,}")
    print(f"  Code Lines:         {t['code']:>10,}")
    print(f"  Blank Lines:        {t['blank']:>10,}")
    print(f"  Code Density:       {t['code']/t['total']*100 if t['total'] else 0:>9.1f}%")
    
    # By Extension
    print(f"\n{'BY FILE TYPE':^70}")
    print("-" * 70)
    print(f"  {'Extension':<12} {'Type':<18} {'Files':>8} {'Total':>10} {'Code':>10}")
    print("  " + "-" * 58)
    
    sorted_ext = sorted(
        results["by_extension"].items(),
        key=lambda x: x[1]["code"],
        reverse=True
    )
    
    for ext, data in sorted_ext:
        type_name = CODE_EXTENSIONS.get(ext, "Other")
        print(f"  {ext:<12} {type_name:<18} {data['files']:>8,} {data['total']:>10,} {data['code']:>10,}")
    
    # By Directory
    print(f"\n{'BY TOP-LEVEL DIRECTORY':^70}")
    print("-" * 70)
    print(f"  {'Directory':<25} {'Files':>8} {'Total':>10} {'Code':>10}")
    print("  " + "-" * 53)
    
    sorted_dirs = sorted(
        results["by_directory"].items(),
        key=lambda x: x[1]["code"],
        reverse=True
    )
    
    for dirname, data in sorted_dirs:
        print(f"  {dirname:<25} {data['files']:>8,} {data['total']:>10,} {data['code']:>10,}")
    
    # Top 15 largest files
    print(f"\n{'TOP 15 LARGEST FILES (by code lines)':^70}")
    print("-" * 70)
    
    top_files = sorted(results["files"], key=lambda x: x["code"], reverse=True)[:15]
    for i, f in enumerate(top_files, 1):
        print(f"  {i:>2}. {f['path']:<50} {f['code']:>6,}")
    
    # Python-specific stats (since this is a Python project)
    py_data = results["by_extension"].get(".py", {"files": 0, "code": 0})
    print(f"\n{'PYTHON CODE SUMMARY':^70}")
    print("-" * 70)
    print(f"  Python Files:       {py_data['files']:>10,}")
    print(f"  Python Code Lines:  {py_data['code']:>10,}")
    if py_data['files']:
        print(f"  Avg Lines/File:     {py_data['code']/py_data['files']:>10.1f}")
    
    print("\n" + "=" * 70)


def main():
    """Main entry point."""
    root_path = PENGUIN_CORE
    
    if not root_path.exists():
        print(f"Error: Path does not exist: {root_path}")
        return 1
    
    print(f"Analyzing: {root_path}")
    print("Excluding: __pycache__, node_modules, docs, misc, errors_log, etc.")
    
    results = analyze_directory(root_path)
    print_report(results, root_path)
    
    return 0


if __name__ == "__main__":
    exit(main())

