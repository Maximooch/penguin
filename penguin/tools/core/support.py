import base64
import difflib
import io
import os
import traceback
from pathlib import Path
from penguin.utils.path_utils import enforce_allowed_path, get_default_write_root
import glob
import fnmatch
import stat
import time
import shutil
from collections import defaultdict
from typing import Optional

from PIL import Image  # type: ignore


def create_folder(path):
    try:
        os.makedirs(path, exist_ok=True)
        return f"Folder created: {os.path.abspath(path)}"
    except Exception as e:
        return f"Error creating folder: {str(e)}"


def create_file(path: str, content: str = "") -> str:
    try:
        print(f"Attempting to create file at: {os.path.abspath(path)}")
        print(f"Current working directory: {os.getcwd()}")

        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

        root_env = os.environ.get('PENGUIN_WRITE_ROOT', '').lower()
        root_pref = root_env if root_env in ('project', 'workspace') else get_default_write_root()
        safe_path = enforce_allowed_path(Path(path), root_pref=root_pref)
        with open(safe_path, "w") as f:
            f.write(content)
        return f"File created successfully at {os.path.abspath(safe_path)}"
    except Exception as e:
        return f"Error creating file: {str(e)}\nStack trace: {traceback.format_exc()}"


def generate_and_apply_diff(original_content, new_content, full_path, encoding):
    print(f"Applying diff to {full_path} with encoding {encoding}")
    diff = list(
        difflib.unified_diff(
            original_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{full_path}",
            tofile=f"b/{full_path}",
            n=3,
        )
    )

    if not diff:
        return "No changes detected."

    try:
        root_env = os.environ.get('PENGUIN_WRITE_ROOT', '').lower()
        root_pref = root_env if root_env in ('project', 'workspace') else get_default_write_root()
        safe_full = enforce_allowed_path(Path(full_path), root_pref=root_pref)
        with open(safe_full, "w", encoding=encoding) as f:
            f.write(new_content)
        return f"Changes applied to {safe_full}:\n" + "".join(diff)
    except Exception as e:
        return f"Error applying changes: {str(e)}"


def write_to_file(path, content):
    full_path = path
    encodings = ["utf-8", "latin-1", "utf-16"]

    for encoding in encodings:
        try:
            if os.path.exists(full_path):
                root_env = os.environ.get('PENGUIN_WRITE_ROOT', '').lower()
                root_pref = root_env if root_env in ('project', 'workspace') else get_default_write_root()
                safe_full = enforce_allowed_path(Path(full_path), root_pref=root_pref)
                with open(safe_full, encoding=encoding) as f:
                    original_content = f.read()
                result = generate_and_apply_diff(
                    original_content, content, str(safe_full), encoding
                )
            else:
                root_env = os.environ.get('PENGUIN_WRITE_ROOT', '').lower()
                root_pref = root_env if root_env in ('project', 'workspace') else get_default_write_root()
                safe_full = enforce_allowed_path(Path(full_path), root_pref=root_pref)
                with open(safe_full, "w", encoding=encoding) as f:
                    f.write(content)
                result = f"New file created and content written to: {safe_full}"
            # Return after successful write
            return result
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        except Exception as e:
            print(f"Error with encoding '{encoding}': {str(e)}")
            continue
    return f"Error writing to file: Unable to encode with encodings: {', '.join(encodings)}"


def read_file(path):
    full_path = path
    encodings = ["utf-8", "latin-1", "utf-16"]
    for encoding in encodings:
        try:
            safe_full = enforce_allowed_path(Path(full_path), root_pref='auto')
            with open(safe_full, encoding=encoding) as f:
                content = f.read()
            return content
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return f"Error reading file: {str(e)}"
    return (
        f"Error reading file: Unable to decode with encodings: {', '.join(encodings)}"
    )


def list_files(path="."):
    try:
        full_path = os.path.normpath(path)

        if not os.path.exists(full_path):
            return f"Error: Directory does not exist: {path}"

        if not os.path.isdir(full_path):
            return f"Error: Not a directory: {path}"

        files = os.listdir(full_path)
        return "\n".join(
            [
                f"{f} ({'directory' if os.path.isdir(os.path.join(full_path, f)) else 'file'})"
                for f in files
            ]
        )
    except Exception as e:
        return f"Error listing files: {str(e)}"


def find_file(filename: str, search_path: str = ".") -> list[str]:
    full_search_path = Path(search_path)
    matches = list(full_search_path.rglob(filename))
    return [str(path.relative_to(full_search_path)) for path in matches]


def encode_image_to_base64(image_path):
    try:
        with Image.open(image_path) as img:
            max_size = (1024, 1024)
            img.thumbnail(max_size, Image.DEFAULT_STRATEGY)
            if img.mode != "RGB":
                img = img.convert("RGB")
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format="JPEG")
            return base64.b64encode(img_byte_arr.getvalue()).decode("utf-8")
    except Exception as e:
        return f"Error encoding image: {str(e)}"


# =============================================================================
# ENHANCED TOOLS - WITH CLEAR PATH FEEDBACK
# =============================================================================

def list_files_filtered(path=".", ignore_patterns=None, group_by_type=False, show_hidden=False, workspace_path=None):
    """
    Enhanced file listing with filtering and optional grouping.
    Always prints the actual path being listed to prevent path confusion.
    """
    try:
        # Handle workspace-relative paths
        if workspace_path and not os.path.isabs(path):
            target_path = Path(workspace_path) / path
        else:
            target_path = Path(path)
        
        target_path = target_path.resolve()
        
        # Clear feedback about what path we're actually listing
        print(f"Listing files in: {target_path}")
        
        if not target_path.exists():
            return f"Error: Directory does not exist: {target_path}"
        
        if not target_path.is_dir():
            return f"Error: Not a directory: {target_path}"
        
        # Default ignore patterns to avoid clutter
        default_ignores = [
            '.git', '__pycache__', '*.pyc', '.DS_Store', 'node_modules', 
            '.pytest_cache', '*.egg-info', '.env', '.venv', 'venv',
            '.mypy_cache', '.tox', 'dist', 'build', '.idea', '.vscode'
        ]
        
        all_ignores = default_ignores + (ignore_patterns or [])
        
        # Collect files with metadata
        files_data = []
        for item in target_path.iterdir():
            # Skip hidden files unless requested
            if not show_hidden and item.name.startswith('.'):
                continue
                
            # Check ignore patterns
            if any(fnmatch.fnmatch(item.name, pattern) for pattern in all_ignores):
                continue
                
            try:
                stat_info = item.stat()
                file_info = {
                    'name': item.name,
                    'type': 'directory' if item.is_dir() else 'file',
                    'size': stat_info.st_size if item.is_file() else 0,
                    'modified': time.ctime(stat_info.st_mtime),
                    'path': str(item)
                }
                files_data.append(file_info)
            except (OSError, PermissionError):
                # Skip files we can't access
                continue
        
        if not files_data:
            return f"No files found in: {target_path}"
        
        # Sort by type (directories first), then by name
        files_data.sort(key=lambda x: (x['type'] == 'file', x['name'].lower()))
        
        if group_by_type:
            # Group by file extension
            grouped = defaultdict(list)
            for file_info in files_data:
                if file_info['type'] == 'directory':
                    grouped['directories'].append(file_info)
                else:
                    ext = Path(file_info['name']).suffix.lower() or 'no_extension'
                    grouped[ext].append(file_info)
            
            result = [f"Files in: {target_path}\n"]
            for group, items in grouped.items():
                result.append(f"\n{group.upper()}:")
                for item in items:
                    if item['type'] == 'file':
                        result.append(f"  {item['name']} ({item['size']} bytes)")
                    else:
                        result.append(f"  {item['name']}/")
            return "\n".join(result)
        else:
            # Simple list format
            result = [f"Files in: {target_path}\n"]
            for item in files_data:
                if item['type'] == 'file':
                    result.append(f"{item['name']} ({item['size']} bytes)")
                else:
                    result.append(f"{item['name']}/")
            return "\n".join(result)
            
    except Exception as e:
        return f"Error listing files in {path}: {str(e)}"


def enhanced_diff(file1, file2, context_lines=3, semantic=True):
    """
    Enhanced diff with semantic analysis and clear path feedback.
    """
    try:
        # Convert to pathlib for robust path handling
        path1 = Path(file1).resolve()
        path2 = Path(file2).resolve()
        
        # Clear feedback about what files we're comparing
        print(f"Comparing files:")
        print(f"  File 1: {path1}")
        print(f"  File 2: {path2}")
        
        # Check if files exist
        if not path1.exists():
            return f"Error: File does not exist: {path1}"
        if not path2.exists():
            return f"Error: File does not exist: {path2}"
            
        # Read file contents
        try:
            content1 = path1.read_text(encoding='utf-8')
            content2 = path2.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            # Try other encodings
            for encoding in ['latin-1', 'utf-16']:
                try:
                    content1 = path1.read_text(encoding=encoding)
                    content2 = path2.read_text(encoding=encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                return f"Error: Unable to decode files with common encodings"
        
        # Generate unified diff
        diff = list(difflib.unified_diff(
            content1.splitlines(keepends=True),
            content2.splitlines(keepends=True),
            fromfile=str(path1),
            tofile=str(path2),
            n=context_lines
        ))
        
        if not diff:
            return f"No differences found between:\n  {path1}\n  {path2}"
        
        # For Python files, add semantic analysis
        if semantic and path1.suffix == '.py' and path2.suffix == '.py':
            try:
                import ast
                tree1 = ast.parse(content1)
                tree2 = ast.parse(content2)
                
                # Extract function and class definitions
                def extract_definitions(tree):
                    functions = []
                    classes = []
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef):
                            functions.append(node.name)
                        elif isinstance(node, ast.ClassDef):
                            classes.append(node.name)
                    return functions, classes
                
                funcs1, classes1 = extract_definitions(tree1)
                funcs2, classes2 = extract_definitions(tree2)
                
                # Analyze semantic changes
                semantic_info = []
                
                added_funcs = set(funcs2) - set(funcs1)
                removed_funcs = set(funcs1) - set(funcs2)
                added_classes = set(classes2) - set(classes1)
                removed_classes = set(classes1) - set(classes2)
                
                if added_funcs:
                    semantic_info.append(f"Added functions: {', '.join(added_funcs)}")
                if removed_funcs:
                    semantic_info.append(f"Removed functions: {', '.join(removed_funcs)}")
                if added_classes:
                    semantic_info.append(f"Added classes: {', '.join(added_classes)}")
                if removed_classes:
                    semantic_info.append(f"Removed classes: {', '.join(removed_classes)}")
                
                if semantic_info:
                    semantic_summary = "\n".join(semantic_info)
                    return f"Semantic changes:\n{semantic_summary}\n\nDetailed diff:\n{''.join(diff)}"
            except SyntaxError:
                # Fall back to regular diff if syntax error
                pass
        
        return f"Diff between {path1} and {path2}:\n{''.join(diff)}"
        
    except Exception as e:
        return f"Error comparing files: {str(e)}"


def find_files_enhanced(pattern, search_path=".", include_hidden=False, file_type=None, workspace_path=None):
    """
    Enhanced file finding with pattern matching and filtering.
    Always prints the search path to prevent confusion.
    """
    try:
        # Handle workspace-relative paths
        if workspace_path and not os.path.isabs(search_path):
            target_path = Path(workspace_path) / search_path
        else:
            target_path = Path(search_path)
        
        target_path = target_path.resolve()
        
        # Clear feedback about what we're searching
        print(f"Searching for '{pattern}' in: {target_path}")
        
        if not target_path.exists():
            return f"Error: Search path does not exist: {target_path}"
        
        if not target_path.is_dir():
            return f"Error: Search path is not a directory: {target_path}"
        
        # Use glob for pattern matching
        matches = []
        
        # Search recursively
        for item in target_path.rglob(pattern):
            # Skip hidden files unless requested
            if not include_hidden and any(part.startswith('.') for part in item.parts):
                continue
                
            # Filter by type if specified
            if file_type:
                if file_type == 'file' and not item.is_file():
                    continue
                elif file_type == 'directory' and not item.is_dir():
                    continue
            
            # Get relative path for cleaner output
            try:
                relative_path = item.relative_to(target_path)
                matches.append({
                    'path': str(relative_path),
                    'full_path': str(item),
                    'type': 'directory' if item.is_dir() else 'file',
                    'size': item.stat().st_size if item.is_file() else 0
                })
            except ValueError:
                # Item is not relative to target_path
                matches.append({
                    'path': str(item),
                    'full_path': str(item),
                    'type': 'directory' if item.is_dir() else 'file',
                    'size': item.stat().st_size if item.is_file() else 0
                })
        
        if not matches:
            return f"No files matching '{pattern}' found in: {target_path}"
        
        # Sort by path
        matches.sort(key=lambda x: x['path'])
        
        # Format results
        result = [f"Found {len(matches)} matches for '{pattern}' in: {target_path}\n"]
        for match in matches:
            if match['type'] == 'file':
                result.append(f"  {match['path']} ({match['size']} bytes)")
            else:
                result.append(f"  {match['path']}/")
        
        return "\n".join(result)
        
    except Exception as e:
        return f"Error searching for files: {str(e)}"


def analyze_project_structure(directory=".", include_external=False, workspace_path=None):
    """
    Analyze project structure and dependencies.
    Always prints the directory being analyzed.
    """
    try:
        # Handle workspace-relative paths
        if workspace_path and not os.path.isabs(directory):
            target_path = Path(workspace_path) / directory
        else:
            target_path = Path(directory)
        
        target_path = target_path.resolve()
        
        # Clear feedback about what we're analyzing
        print(f"Analyzing project structure in: {target_path}")
        
        if not target_path.exists():
            return f"Error: Directory does not exist: {target_path}"
        
        if not target_path.is_dir():
            return f"Error: Not a directory: {target_path}"
        
        # Find all Python files
        python_files = list(target_path.rglob("*.py"))
        
        if not python_files:
            return f"No Python files found in: {target_path}"
        
        # Analyze structure
        import ast
        
        dependency_graph = defaultdict(set)
        all_functions = []
        all_classes = []
        file_stats = {}
        
        for py_file in python_files:
            try:
                content = py_file.read_text(encoding='utf-8')
                tree = ast.parse(content)
                
                # Get relative path for cleaner output
                relative_path = py_file.relative_to(target_path)
                
                # Count lines
                lines = len(content.splitlines())
                
                # Extract imports
                imports = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports.append(alias.name)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            imports.append(node.module)
                
                # Extract functions and classes
                functions = []
                classes = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        functions.append(node.name)
                        all_functions.append(f"{relative_path}:{node.name}")
                    elif isinstance(node, ast.ClassDef):
                        classes.append(node.name)
                        all_classes.append(f"{relative_path}:{node.name}")
                
                # Store file stats
                file_stats[str(relative_path)] = {
                    'lines': lines,
                    'functions': len(functions),
                    'classes': len(classes),
                    'imports': len(imports)
                }
                
                # Build dependency graph
                for imp in imports:
                    if include_external or not _is_external_import(imp):
                        dependency_graph[str(relative_path)].add(imp)
                        
            except (SyntaxError, UnicodeDecodeError) as e:
                # Skip files we can't parse
                continue
        
        # Generate summary
        total_lines = sum(stats['lines'] for stats in file_stats.values())
        total_functions = len(all_functions)
        total_classes = len(all_classes)
        
        result = [
            f"Project Structure Analysis for: {target_path}",
            f"Files analyzed: {len(file_stats)}",
            f"Total lines: {total_lines}",
            f"Total functions: {total_functions}",
            f"Total classes: {total_classes}",
            "",
            "File breakdown:"
        ]
        
        # Sort files by lines (largest first)
        sorted_files = sorted(file_stats.items(), key=lambda x: x[1]['lines'], reverse=True)
        
        for file_path, stats in sorted_files[:10]:  # Show top 10
            result.append(f"  {file_path}: {stats['lines']} lines, {stats['functions']} functions, {stats['classes']} classes")
        
        if len(sorted_files) > 10:
            result.append(f"  ... and {len(sorted_files) - 10} more files")
        
        # Show most common imports
        if dependency_graph:
            all_imports = []
            for imports in dependency_graph.values():
                all_imports.extend(imports)
            
            from collections import Counter
            common_imports = Counter(all_imports).most_common(5)
            
            result.append("")
            result.append("Most common imports:")
            for imp, count in common_imports:
                result.append(f"  {imp}: {count} files")
        
        return "\n".join(result)
        
    except Exception as e:
        return f"Error analyzing project structure: {str(e)}"


def _is_external_import(import_name):
    """Check if an import is external (not local to the project)."""
    external_patterns = [
        'os', 'sys', 'json', 'asyncio', 'logging', 'pathlib', 'datetime', 'time',
        'typing', 'collections', 'itertools', 'functools', 'operator', 'math',
        'requests', 'httpx', 'flask', 'django', 'fastapi', 'numpy', 'pandas',
        'torch', 'tensorflow', 'sklearn', 'matplotlib', 'seaborn',
        'pytest', 'unittest', 'mock', 'click', 'argparse'
    ]
    return any(import_name.startswith(pattern) for pattern in external_patterns)


def apply_diff_to_file(file_path, diff_content, backup=True, workspace_path=None, return_json=False):
    """
    Apply a unified diff to a file to make actual edits.
    This is for EDITING files, not just comparing them.
    """
    try:
        # Handle workspace-relative paths
        if workspace_path and not os.path.isabs(file_path):
            target_path = Path(workspace_path) / file_path
        else:
            target_path = Path(file_path)
        
        target_path = target_path.resolve()
        
        # Clear feedback about what file we're editing
        print(f"Applying diff to file: {target_path}")
        
        if not target_path.exists():
            return f"Error: File does not exist: {target_path}"
        
        # Create backup if requested
        if backup:
            backup_path = target_path.with_suffix(target_path.suffix + '.bak')
            shutil.copy2(target_path, backup_path)
            print(f"Backup created: {backup_path}")
        
        # Read original content without newline translation to detect CRLF
        try:
            raw = target_path.read_bytes()
            try:
                original_content = raw.decode('utf-8')
            except UnicodeDecodeError:
                for encoding in ['latin-1', 'utf-16']:
                    try:
                        original_content = raw.decode(encoding)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    return f"Error: Unable to decode file with common encodings"
        except Exception as e:
            return f"Error reading file: {str(e)}"
        
        # Parse and apply the diff
        try:
            modified_content = _apply_unified_diff(original_content, diff_content)

            # If the patcher signals a failure, return that up
            if isinstance(modified_content, dict) and modified_content.get("error"):
                # Restore from backup if we created one
                if backup:
                    try:
                        backup_path = target_path.with_suffix(target_path.suffix + '.bak')
                        if backup_path.exists():
                            shutil.copy2(backup_path, target_path)
                    except Exception:
                        pass
                # Log failure details for reproduction
                log_path = _log_diff_failure(file_path, diff_content, original_content, workspace_path)
                err_msg = f"Error applying diff: {modified_content['error']}"
                if log_path:
                    err_msg += f" (logged at {log_path})"
                return err_msg

            # Write modified content back preserving original newline style if consistent
            newline = None
            if '\n' in original_content:
                crlf_pairs = original_content.count('\r\n')
                total_lf = original_content.count('\n')
                lone_lf = total_lf - crlf_pairs
                # Preserve CRLF if it is present and at least as common as lone LF
                if crlf_pairs > 0 and crlf_pairs >= lone_lf:
                    newline = '\r\n'
            # write_text can't set newline directly; emulate by normalizing
            if newline:
                # Normalize by re-joining on target newline to avoid double substitutions
                parts = modified_content.splitlines(keepends=False)
                normed = newline.join(parts)
                if modified_content.endswith('\n'):
                    normed += newline
                target_path.write_bytes(normed.encode('utf-8'))
            else:
                target_path.write_text(modified_content, encoding='utf-8')

            print(f"Diff applied successfully to: {target_path}")
            if return_json:
                import json
                analysis = _analyze_diff(diff_content)
                result = {
                    "status": "success",
                    "file": str(target_path),
                    "newline_style": "CRLF" if newline == '\r\n' else "LF",
                    "backup_created": bool(backup),
                    "analysis": analysis,
                }
                return json.dumps(result)
            else:
                return f"Successfully applied diff to {target_path}"

        except Exception as e:
            # Attempt to restore from backup
            if backup:
                try:
                    backup_path = target_path.with_suffix(target_path.suffix + '.bak')
                    if backup_path.exists():
                        shutil.copy2(backup_path, target_path)
                except Exception:
                    pass
            # Log unexpected failure
            log_path = _log_diff_failure(file_path, diff_content, original_content, workspace_path)
            msg = f"Error applying diff: {str(e)}"
            if log_path:
                msg += f" (logged at {log_path})"
            return msg
        
    except Exception as e:
        return f"Error processing diff application: {str(e)}"


def _apply_unified_diff(original_content, diff_content):
    """
    Apply a unified diff to content with basic validation.

    - Preserves line endings by operating on keepends=True sequences
    - Validates context lines before applying changes
    - Supports multiple hunks

    Returns the modified content on success, or {'error': msg} on failure.
    """
    import re

    # Work with explicit line endings preserved
    orig_lines = original_content.splitlines(keepends=True)
    diff_lines = diff_content.splitlines(keepends=False)

    # Reject multi-file patches (more than one file header in a single diff)
    header_count = sum(1 for l in diff_lines if l.startswith('--- '))
    if header_count > 1:
        return {"error": "Multi-file patches are not supported by apply_diff_to_file"}

    # Skip headers (---, +++) if present
    idx = 0
    while idx < len(diff_lines) and (diff_lines[idx].startswith('---') or diff_lines[idx].startswith('+++')):
        idx += 1

    # Parse hunks
    hunks = []
    while idx < len(diff_lines):
        header = diff_lines[idx]
        if not header.startswith('@@'):
            # Skip non-hunk noise
            idx += 1
            continue
        m = re.match(r"@@ -(?P<o_start>\d+)(?:,(?P<o_cnt>\d+))? \+(?P<n_start>\d+)(?:,(?P<n_cnt>\d+))? @@", header)
        if not m:
            return {"error": f"Invalid hunk header: {header}"}
        o_start = int(m.group('o_start')) - 1
        o_cnt = int(m.group('o_cnt') or '1')
        # new range not used for application, but parsed for completeness

        idx += 1
        ops = []
        while idx < len(diff_lines):
            line = diff_lines[idx]
            if line.startswith('@@'):
                break
            if line == r"\ No newline at end of file":
                idx += 1
                continue
            if not line:
                # Empty context line is valid; treat as space with empty
                ops.append(('context', ''))
                idx += 1
                continue
            tag = line[0]
            content = line[1:]
            if tag == ' ':
                ops.append(('context', content))
            elif tag == '+':
                ops.append(('add', content))
            elif tag == '-':
                ops.append(('del', content))
            else:
                return {"error": f"Unexpected diff line: {line}"}
            idx += 1
        hunks.append((o_start, o_cnt, ops))

    # Apply hunks
    result = list(orig_lines)
    for o_start, o_cnt, ops in reversed(hunks):
        # Compute expected original slice from ops (context + deletions only)
        expected_old = []
        for typ, txt in ops:
            if typ in ('context', 'del'):
                # Re-add newline to align with keepends in orig_lines
                expected_old.append(txt + '\n')
        # Slice from original
        old_slice = result[o_start:o_start + o_cnt]
        # Compare ignoring trailing newline differences which diffs sometimes elide
        def _norm(seq):
            return [s.rstrip('\r\n') for s in seq]
        if _norm(old_slice) != _norm(expected_old):
            return {"error": "Context mismatch while applying diff (file changed since diff was generated)"}

        # Build replacement slice (context + additions)
        replacement = []
        for typ, txt in ops:
            if typ == 'context':
                replacement.append(txt + '\n')
            elif typ == 'add':
                replacement.append(txt + '\n')
            # deletions are omitted

        result[o_start:o_start + o_cnt] = replacement

    return ''.join(result)


def _analyze_diff(diff_content: str) -> dict:
    """Return a simple analysis dict: hunks, adds, dels, contexts."""
    adds = dels = ctx = hunks = 0
    for line in diff_content.splitlines():
        if line.startswith('@@'):
            hunks += 1
        elif line.startswith('+') and not line.startswith('+++'):
            adds += 1
        elif line.startswith('-') and not line.startswith('---'):
            dels += 1
        elif line.startswith(' '):
            ctx += 1
    return {"hunks": hunks, "adds": adds, "dels": dels, "context": ctx}


def _log_diff_failure(file_path: str, diff_content: str, original_content: str, workspace_path: str | None) -> str | None:
    """Log failing diff and original content to errors_log/diffs; return path directory."""
    try:
        from datetime import datetime
        base = Path(workspace_path or ".") / "errors_log" / "diffs"
        base.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        dirp = base / f"failure_{ts}"
        dirp.mkdir(parents=True, exist_ok=True)
        (dirp / "target.txt").write_text(original_content, encoding="utf-8", errors="ignore")
        (dirp / "patch.diff").write_text(diff_content, encoding="utf-8", errors="ignore")
        (dirp / "file_path.txt").write_text(str(file_path), encoding="utf-8", errors="ignore")
        return str(dirp)
    except Exception:
        return None


def preview_unified_diff(diff_content: str) -> str:
    """Produce a human-friendly summary of a unified diff's hunks and line ops."""
    a = _analyze_diff(diff_content)
    parts = [
        "Diff preview:",
        f"  hunks: {a['hunks']}",
        f"  additions: {a['adds']}",
        f"  deletions: {a['dels']}",
        f"  context: {a['context']}",
    ]
    return "\n".join(parts)


def _split_multifile_unified_patch(patch_text: str) -> list[dict]:
    """Split a unified diff containing multiple file patches into parts.

    Returns a list of { 'from': from_path, 'to': to_path, 'content': file_patch_text }.
    """
    lines = patch_text.splitlines()
    parts = []
    i = 0
    current = None
    buf = []
    from_path = to_path = None
    while i < len(lines):
        line = lines[i]
        if line.startswith('--- '):
            # flush previous
            if buf and from_path is not None and to_path is not None:
                parts.append({'from': from_path, 'to': to_path, 'content': "\n".join(buf) + "\n"})
                buf = []
                from_path = to_path = None
            from_path = line[4:].strip()
            buf.append(line)
            # expect +++ next
            if i + 1 < len(lines) and lines[i + 1].startswith('+++ '):
                i += 1
                to_path = lines[i][4:].strip()
                buf.append(lines[i])
            else:
                # malformed but continue collecting
                pass
        else:
            buf.append(line)
        i += 1
    if buf and from_path is not None and to_path is not None:
        parts.append({'from': from_path, 'to': to_path, 'content': "\n".join(buf) + "\n"})
    return parts


def _strip_prefix(path_str: str) -> str:
    # Drop common diff prefixes like a/ and b/
    if path_str.startswith('a/') or path_str.startswith('b/'):
        return path_str[2:]
    return path_str


def apply_unified_patch(patch_text: str, workspace_path: Optional[str] = None, backup: bool = True, return_json: bool = False) -> str:
    """Apply a unified patch that may contain multiple files.

    Performs best-effort transactional behavior: if any file fails, previously-applied
    files are restored from their backups.
    """
    file_patches = _split_multifile_unified_patch(patch_text)
    if not file_patches:
        return "Error applying diff: No file patches found"

    applied = []
    results = []
    for fp in file_patches:
        to_path = _strip_prefix(fp['to'])
        # Resolve target path
        target = Path(to_path)
        if not target.is_absolute():
            base = Path(workspace_path or ".")
            target = (base / to_path).resolve()
        # Apply
        res = apply_diff_to_file(str(target), fp['content'], backup=backup, workspace_path=workspace_path, return_json=return_json)
        results.append(res)
        if isinstance(res, str) and res.startswith("Error applying diff"):
            # rollback previously applied files
            for prev in applied:
                try:
                    p = Path(prev)
                    bak = p.with_suffix(p.suffix + '.bak')
                    if bak.exists():
                        shutil.copy2(bak, p)
                except Exception:
                    pass
            return res
        else:
            applied.append(str(target))

    if return_json:
        import json
        return json.dumps({"status": "success", "files": applied})
    return f"Successfully applied patch to {len(applied)} file(s)"


def generate_diff_patch(original_content, new_content, file_path="file"):
    """
    Generate a unified diff patch that can be applied with apply_diff_to_file.
    """
    diff = list(difflib.unified_diff(
        original_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        n=3
    ))
    
    return ''.join(diff)


def edit_file_with_pattern(file_path, search_pattern, replacement, backup=True, workspace_path=None):
    """
    Edit a file by searching for a pattern and replacing it.
    This is another way to edit files programmatically.
    """
    try:
        # Handle workspace-relative paths
        if workspace_path and not os.path.isabs(file_path):
            target_path = Path(workspace_path) / file_path
        else:
            target_path = Path(file_path)
        
        target_path = target_path.resolve()
        
        # Clear feedback about what file we're editing
        print(f"Editing file with pattern replacement: {target_path}")
        
        if not target_path.exists():
            return f"Error: File does not exist: {target_path}"
        
        # Create backup if requested
        if backup:
            backup_path = target_path.with_suffix(target_path.suffix + '.bak')
            shutil.copy2(target_path, backup_path)
            print(f"Backup created: {backup_path}")
        
        # Read, modify, and write content
        try:
            original_content = target_path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            for encoding in ['latin-1', 'utf-16']:
                try:
                    original_content = target_path.read_text(encoding=encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                return f"Error: Unable to decode file with common encodings"
        
        # Apply pattern replacement
        import re
        modified_content = re.sub(search_pattern, replacement, original_content)
        
        # Check if anything changed
        if modified_content == original_content:
            print(f"No changes made to: {target_path}")
            return f"No matches found for pattern in {target_path}"
        
        # Write modified content back
        target_path.write_text(modified_content, encoding='utf-8')
        
        print(f"Pattern replacement applied to: {target_path}")
        
        # Generate diff to show what changed
        diff = generate_diff_patch(original_content, modified_content, str(target_path))
        
        return f"Successfully edited {target_path}:\n{diff}"
        
    except Exception as e:
        return f"Error editing file: {str(e)}"


def edit_file_at_line(file_path, line_number, new_content, operation="replace", backup=True, workspace_path=None):
    """
    Edit a file at a specific line number.
    This makes it easy to target specific lines for editing.
    
    Args:
        file_path: Path to the file to edit
        line_number: Line number to edit (1-based)
        new_content: New content for the line
        operation: "replace", "insert_before", "insert_after", or "delete"
        backup: Create backup file
        workspace_path: Workspace path for relative paths
    """
    try:
        # Handle workspace-relative paths
        if workspace_path and not os.path.isabs(file_path):
            target_path = Path(workspace_path) / file_path
        else:
            target_path = Path(file_path)
        
        target_path = target_path.resolve()
        
        # Clear feedback about what file we're editing
        print(f"Editing file at line {line_number}: {target_path}")
        
        if not target_path.exists():
            return f"Error: File does not exist: {target_path}"
        
        # Create backup if requested
        if backup:
            backup_path = target_path.with_suffix(target_path.suffix + '.bak')
            shutil.copy2(target_path, backup_path)
            print(f"Backup created: {backup_path}")
        
        # Read original content
        try:
            original_content = target_path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            for encoding in ['latin-1', 'utf-16']:
                try:
                    original_content = target_path.read_text(encoding=encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                return f"Error: Unable to decode file with common encodings"
        
        original_lines = original_content.splitlines()
        
        # Convert to 0-based indexing
        line_index = line_number - 1
        
        # Validate line number
        if line_index < 0 or line_index >= len(original_lines):
            return f"Error: Line {line_number} does not exist (file has {len(original_lines)} lines)"
        
        # Apply the operation
        modified_lines = original_lines.copy()
        
        if operation == "replace":
            modified_lines[line_index] = new_content
        elif operation == "insert_before":
            modified_lines.insert(line_index, new_content)
        elif operation == "insert_after":
            modified_lines.insert(line_index + 1, new_content)
        elif operation == "delete":
            modified_lines.pop(line_index)
        else:
            return f"Error: Unknown operation '{operation}'. Use 'replace', 'insert_before', 'insert_after', or 'delete'"
        
        # Write modified content back
        modified_content = '\n'.join(modified_lines)
        target_path.write_text(modified_content, encoding='utf-8')
        
        print(f"Line {line_number} operation '{operation}' applied to: {target_path}")
        
        # Generate diff to show what changed
        diff = generate_diff_patch(original_content, modified_content, str(target_path))
        
        return f"Successfully edited {target_path} at line {line_number}:\n{diff}"
        
    except Exception as e:
        return f"Error editing file at line {line_number}: {str(e)}"


def enhanced_write_to_file(path, content, backup=True, workspace_path=None):
    """
    Enhanced file writing with clear path feedback and optional backup.
    """
    try:
        # Handle workspace-relative paths
        if workspace_path and not os.path.isabs(path):
            target_path = Path(workspace_path) / path
        else:
            target_path = Path(path)
        
        target_path = target_path.resolve()
        
        # Clear feedback about what file we're writing to
        print(f"Writing to file: {target_path}")
        
        # Create parent directories if needed
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Check if file exists and create backup if requested
        if target_path.exists() and backup:
            backup_path = target_path.with_suffix(target_path.suffix + '.bak')
            backup_path.write_text(target_path.read_text())
            print(f"Backup created: {backup_path}")
        
        # Try different encodings
        encodings = ["utf-8", "latin-1", "utf-16"]
        
        for encoding in encodings:
            try:
                if target_path.exists():
                    # Generate diff for existing file
                    try:
                        original_content = target_path.read_text(encoding=encoding)
                        result = generate_and_apply_diff(
                            original_content, content, str(target_path), encoding
                        )
                        print(f"File updated: {target_path}")
                        return result
                    except UnicodeDecodeError:
                        continue
                else:
                    # Create new file
                    target_path.write_text(content, encoding=encoding)
                    print(f"New file created: {target_path}")
                    return f"New file created: {target_path}"
                    
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
            except Exception as e:
                print(f"Error with encoding '{encoding}': {str(e)}")
                continue
        
        return f"Error writing to file: Unable to encode with encodings: {', '.join(encodings)}"
        
    except Exception as e:
        return f"Error writing to file {path}: {str(e)}"


def enhanced_read_file(path, show_line_numbers=False, max_lines=None, workspace_path=None):
    """
    Enhanced file reading with clear path feedback and options.
    """
    try:
        # Handle workspace-relative paths
        if workspace_path and not os.path.isabs(path):
            target_path = Path(workspace_path) / path
        else:
            target_path = Path(path)
        
        target_path = target_path.resolve()
        
        # Clear feedback about what file we're reading
        print(f"Reading file: {target_path}")
        
        if not target_path.exists():
            return f"Error: File does not exist: {target_path}"
        
        if not target_path.is_file():
            return f"Error: Not a file: {target_path}"
        
        # Try different encodings
        encodings = ["utf-8", "latin-1", "utf-16"]
        
        for encoding in encodings:
            try:
                content = target_path.read_text(encoding=encoding)
                
                # Apply line limit if specified
                if max_lines:
                    lines = content.splitlines()
                    if len(lines) > max_lines:
                        content = '\n'.join(lines[:max_lines])
                        content += f"\n... (truncated, showing first {max_lines} lines of {len(lines)})"
                
                # Add line numbers if requested
                if show_line_numbers:
                    lines = content.splitlines()
                    numbered_lines = []
                    for i, line in enumerate(lines, 1):
                        numbered_lines.append(f"{i:4d}: {line}")
                    content = '\n'.join(numbered_lines)
                
                print(f"File read successfully: {target_path} ({len(content)} characters)")
                return content
                
            except UnicodeDecodeError:
                continue
        
        return f"Error reading file: Unable to decode with encodings: {', '.join(encodings)}"
        
    except Exception as e:
        return f"Error reading file {path}: {str(e)}"


# =============================================================================
# COMMENTED OUT OLD TOOLS (replaced by enhanced versions above)
# =============================================================================

# def list_files(path="."):
#     """REPLACED BY: list_files_filtered"""
#     try:
#         full_path = os.path.normpath(path)
#         if not os.path.exists(full_path):
#             return f"Error: Directory does not exist: {path}"
#         if not os.path.isdir(full_path):
#             return f"Error: Not a directory: {path}"
#         files = os.listdir(full_path)
#         return "\n".join([
#             f"{f} ({'directory' if os.path.isdir(os.path.join(full_path, f)) else 'file'})"
#             for f in files
#         ])
#     except Exception as e:
#         return f"Error listing files: {str(e)}"

# def find_file(filename: str, search_path: str = ".") -> list[str]:
#     """REPLACED BY: find_files_enhanced"""
#     full_search_path = Path(search_path)
#     matches = list(full_search_path.rglob(filename))
#     return [str(path.relative_to(full_search_path)) for path in matches]

# def write_to_file(path, content):
#     """REPLACED BY: enhanced_write_to_file"""
#     # ... (original implementation)

# def read_file(path):
#     """REPLACED BY: enhanced_read_file"""
#     # ... (original implementation)


# Example usage:
# print(create_folder("test_folder"))
# print(create_file("test_file.txt", "Hello, World!"))
# print(enhanced_write_to_file("test_file.txt", "Updated content"))
# print(enhanced_read_file("test_file.txt"))
# print(list_files_filtered())
# print(encode_image_to_base64("test_image.jpg"))
