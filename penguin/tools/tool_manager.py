import base64
import logging
import os
import subprocess
import asyncio
from typing import Any, Callable, Dict, List, Optional, Union
import datetime
import json
from pathlib import Path
import time
import re
from collections import defaultdict

# from utils.log_error import log_error
# from .core.support import create_folder, create_file, write_to_file, read_file, list_files, encode_image_to_base64, find_file
from penguin.config import config, WORKSPACE_PATH
from penguin.utils.path_utils import get_allowed_roots, get_default_write_root
from penguin.memory.summary_notes import SummaryNotes
from penguin.utils import FileMap
from penguin.utils.profiling import profile_operation, profile_startup_phase, profiler

# from .old2_memory_search import MemorySearch
from penguin.utils.notebook import NotebookExecutor

from penguin.tools.core.declarative_memory_tool import DeclarativeMemoryTool
from penguin.tools.core.grep_search import GrepSearch
from penguin.tools.core.lint_python import lint_python
# from penguin.tools.core.memory_search import MemorySearcher  # Import the new memory searcher
from penguin.tools.core.perplexity_tool import PerplexityProvider
# from penguin.tools.core.workspace_search import CodeIndexer
from penguin.tools.browser_tools import (
    browser_manager, BrowserNavigationTool, BrowserInteractionTool, BrowserScreenshotTool
)
from penguin.tools.core.task_tools import TaskTools

# Lazy import for PyDoll to avoid breaking if pydoll-python is not installed
_pydoll_tools_imported = False
_pydoll_import_error = None

def _ensure_pydoll_imports():
    """Lazy import PyDoll tools only when needed."""
    global _pydoll_tools_imported, _pydoll_import_error
    global pydoll_browser_manager, PyDollBrowserNavigationTool, PyDollBrowserInteractionTool
    global PyDollBrowserScreenshotTool, PyDollBrowserScrollTool
    
    if not _pydoll_tools_imported and _pydoll_import_error is None:
        try:
            from penguin.tools.pydoll_tools import (
                pydoll_browser_manager as _pbm,
                PyDollBrowserNavigationTool as _nav,
                PyDollBrowserInteractionTool as _interact,
                PyDollBrowserScreenshotTool as _screenshot,
                PyDollBrowserScrollTool as _scroll,
            )
            pydoll_browser_manager = _pbm
            PyDollBrowserNavigationTool = _nav
            PyDollBrowserInteractionTool = _interact
            PyDollBrowserScreenshotTool = _screenshot
            PyDollBrowserScrollTool = _scroll
            _pydoll_tools_imported = True
        except Exception as e:
            _pydoll_import_error = e
            logger.warning(f"PyDoll tools not available: {e}")
    
    if _pydoll_import_error:
        raise ImportError(f"PyDoll tools unavailable: {_pydoll_import_error}")

# Initialize placeholders
pydoll_browser_manager = None
PyDollBrowserNavigationTool = None
PyDollBrowserInteractionTool = None
PyDollBrowserScreenshotTool = None
PyDollBrowserScrollTool = None
# from penguin.llm.model_manager import ModelManager
from penguin.memory.provider import MemoryProvider

# Repository management tools
from penguin.tools.repository_tools import (
    create_improvement_pr,
    create_feature_pr, 
    create_bugfix_pr,
    get_repository_status,
    commit_and_push_changes,
    create_and_switch_branch
)

# Security/Permission imports (lazy to avoid circular imports at module load)
_permission_enforcer_imported = False
_PermissionEnforcer = None
_WorkspaceBoundaryPolicy = None
_PermissionMode = None
_PermissionResult = None
_PermissionDeniedError = None
_check_tool_permission = None

def _ensure_permission_imports():
    """Lazy import permission modules to avoid circular imports."""
    global _permission_enforcer_imported, _PermissionEnforcer, _WorkspaceBoundaryPolicy
    global _PermissionMode, _PermissionResult, _PermissionDeniedError, _check_tool_permission
    
    if not _permission_enforcer_imported:
        try:
            from penguin.security import (
                PermissionEnforcer,
                WorkspaceBoundaryPolicy,
                PermissionMode,
                PermissionResult,
                PermissionDeniedError,
            )
            from penguin.security.tool_permissions import check_tool_permission
            
            _PermissionEnforcer = PermissionEnforcer
            _WorkspaceBoundaryPolicy = WorkspaceBoundaryPolicy
            _PermissionMode = PermissionMode
            _PermissionResult = PermissionResult
            _PermissionDeniedError = PermissionDeniedError
            _check_tool_permission = check_tool_permission
            _permission_enforcer_imported = True
        except ImportError as e:
            logger.warning(f"Permission system not available: {e}")
            _permission_enforcer_imported = True  # Don't retry

logger = logging.getLogger(__name__) # Add logger

class ToolManager:
    def __init__(self, config: Dict[str, Any], log_error_func: Callable, fast_startup: bool = False):
        """
        Initialize ToolManager with true lazy loading for optimal startup performance.
        
        Args:
            config: Configuration dictionary
            log_error_func: Error logging function
            fast_startup: If True, defer ALL heavy operations until first use
        """
        # Fix HuggingFace tokenizers parallelism warning early, before any model loading
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        
        with profile_startup_phase("ToolManager.__init__"):
            logger.info("Initializing ToolManager with true lazy loading...")
            self.config = config
            self.log_error = log_error_func
            self.fast_startup = fast_startup
            # Resolve the active project root (prefer env override, then git-root)
            project_root_env = os.environ.get('PENGUIN_PROJECT_ROOT')
            if project_root_env:
                try:
                    self.project_root = str(Path(project_root_env).expanduser().resolve())
                    logger.info("ToolManager env override project_root=%s", self.project_root)
                except Exception:
                    logger.warning("Invalid PENGUIN_PROJECT_ROOT=%s; falling back to auto-detect", project_root_env)
                    project_root_env = None
            if not project_root_env:
                try:
                    prj_root, _ws_root, *_ = get_allowed_roots()
                    self.project_root = str(prj_root)
                except Exception:
                    # Fallback to current working directory
                    self.project_root = os.getcwd()
            # Determine active file root (project or workspace)
            self.workspace_root = str(WORKSPACE_PATH)
            root_pref_env = os.environ.get('PENGUIN_WRITE_ROOT', '').lower()
            if root_pref_env in ('project', 'workspace'):
                self.file_root_mode = root_pref_env
            else:
                self.file_root_mode = get_default_write_root()
            self._file_root = self.project_root if self.file_root_mode == 'project' else self.workspace_root
            logger.info(
                "ToolManager init: project_root=%s workspace_root=%s mode=%s file_root=%s",
                self.project_root,
                self.workspace_root,
                self.file_root_mode,
                self._file_root,
            )
            
            # Track what's been initialized - expanded for all tools
            self._lazy_initialized = {
                'declarative_memory_tool': False,
                'grep_search': False,
                'file_map': False,
                'summary_notes_tool': False,
                'notebook_executor': False,
                'perplexity_provider': False,
                'memory_provider': False,
                'memory_indexing': False,
                'browser_tools': False,
                'pydoll_tools': False,
                'task_tools': False,
            }
            
            # Placeholder attributes for ALL lazy loading
            self._declarative_memory_tool = None
            self._task_tools = None
            self._grep_search = None
            self._file_map = None
            self._summary_notes_tool = None
            self._notebook_executor = None
            self._perplexity_provider = None
            self._memory_provider = None
            self._indexing_task = None
            self._indexing_completed = False
            
            # Browser tools placeholders
            self._browser_navigation_tool = None
            self._browser_interaction_tool = None
            self._browser_screenshot_tool = None
            
            # PyDoll tools placeholders
            self._pydoll_browser_navigation_tool = None
            self._pydoll_browser_interaction_tool = None
            self._pydoll_browser_screenshot_tool = None
            self._pydoll_browser_scroll_tool = None

            # PenguinCore reference for sub-agent tools
            self._core = None

            # Permission enforcer (lazy initialized)
            self._permission_enforcer = None
            self._permission_enabled = os.environ.get("PENGUIN_YOLO", "").lower() not in ("1", "true", "yes")
            
            # Tool registry - just map names to module paths, no actual loading
            self._tool_registry = {
                'create_folder': 'penguin.tools.core.support.create_folder',
                'create_file': 'penguin.tools.core.support.create_file',
                'write_to_file': 'penguin.tools.core.support.enhanced_write_to_file',
                'read_file': 'penguin.tools.core.support.enhanced_read_file',
                'list_files': 'penguin.tools.core.support.list_files_filtered',
                'find_file': 'penguin.tools.core.support.find_files_enhanced',
                'encode_image_to_base64': 'penguin.tools.core.support.encode_image_to_base64',
                # New enhanced tools
                'enhanced_diff': 'penguin.tools.core.support.enhanced_diff',
                'analyze_project': 'penguin.tools.core.support.analyze_project_structure',
                'apply_diff': 'penguin.tools.core.support.apply_diff_to_file',
                'edit_with_pattern': 'penguin.tools.core.support.edit_file_with_pattern',
                'add_declarative_note': 'self.declarative_memory_tool.add_note',
                'grep_search': 'self.grep_search.search',
                'memory_search': 'self.perform_memory_search',
                'code_execution': 'self.notebook_executor.execute_code',
                'get_file_map': 'self.file_map.get_formatted_file_map',
                'lint_python': 'penguin.tools.core.lint_python.lint_python',
                'execute_command': 'self.execute_command',
                'add_summary_note': 'self.summary_notes_tool.add_summary',
                'perplexity_search': 'self.perplexity_provider.search',
                'browser_navigate': 'self.browser_navigation_tool.execute',
                'browser_interact': 'self.browser_interaction_tool.execute',
                'browser_screenshot': 'self.browser_screenshot_tool.execute',
                'pydoll_browser_navigate': 'self.pydoll_browser_navigation_tool.execute',
                'pydoll_browser_interact': 'self.pydoll_browser_interaction_tool.execute',
                'pydoll_browser_screenshot': 'self.pydoll_browser_screenshot_tool.execute',
                'pydoll_browser_scroll': 'self.pydoll_browser_scroll_tool.execute',
                'analyze_codebase': 'self.analyze_codebase',
                'reindex_workspace': 'self.reindex_workspace',
                'finish_response': 'self.task_tools.finish_response',
                'finish_task': 'self.task_tools.finish_task',
                'task_completed': 'self.task_tools.task_completed',  # Deprecated alias
            }
            
            # Cached tool instances for performance
            self._tool_instances = {}
            
            # Tool definitions (lightweight schema only)
            with profile_operation("ToolManager.define_tool_schemas"):
                self.tools = self._define_tool_schemas()

            # Handle both dict-style and dataclass-style config access
            try:
                if hasattr(config, 'diagnostics') and hasattr(config.diagnostics, 'enabled'):
                    # Dataclass-style config
                    self.diagnostics_enabled = config.diagnostics.enabled
                elif hasattr(config, 'get'):
                    # Dict-style config
                    self.diagnostics_enabled = config.get("diagnostics", {}).get("enabled", False)
                else:
                    # Fallback
                    self.diagnostics_enabled = False
            except Exception:
                self.diagnostics_enabled = False
            
            # In true lazy loading mode, we don't initialize ANYTHING until first use
            logger.info(f"ToolManager initialized with true lazy loading. Fast startup: {fast_startup}")

    def _define_tool_schemas(self) -> List[Dict[str, Any]]:
        """Define tool schemas without any initialization - pure schema definitions."""
        return [
            {
                "name": "create_folder",
                "description": "Create a new folder at the specified path. Use this when you need to create a new directory in the project structure.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "The path where the folder should be created",
                        }
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "finish_response",
                "description": "Signal that your response is complete. Call when you've answered the user and have no more actions to take. This stops the response loop.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "Optional brief summary of your response.",
                        }
                    },
                    "required": [],
                },
            },
            {
                "name": "finish_task",
                "description": "Signal that you believe the task objective is achieved. The task will be marked for human review (not auto-completed). Call this in task/autonomous mode when done.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "Summary of what was accomplished. This becomes the review note.",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["done", "partial", "blocked"],
                            "description": "Completion status: done (objective met), partial (some progress), blocked (cannot proceed).",
                        }
                    },
                    "required": [],
                },
            },
            # Deprecated: kept for backward compatibility
            {
                "name": "task_completed",
                "description": "DEPRECATED: Use finish_task instead. Signals task completion.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "A concise summary of what was accomplished.",
                        }
                    },
                    "required": [],
                },
            },
            {
                "name": "multiedit_apply",
                "description": "Apply multiple diffs atomically. Accepts unified multi-file patch or per-file block format. Dry-run by default.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Unified patch or multiedit block"},
                        "apply": {"type": "boolean", "description": "Apply changes (default true)"},
                    },
                    "required": ["content"],
                },
            },
            {
                "name": "create_file",
                "description": "Create a new file at the specified path with optional content. Use this when you need to create a new file in the project structure.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "The path where the file should be created",
                        },
                        "content": {
                            "type": "string",
                            "description": "The initial content of the file (optional)",
                        },
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "write_to_file",
                "description": "Enhanced file writing with diff generation and backup options. Shows the exact path being written to and creates backups by default. If the file exists, shows what changed.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "The path of the file to write to",
                        },
                        "content": {
                            "type": "string",
                            "description": "The full content to write to the file",
                        },
                        "backup": {
                            "type": "boolean",
                            "description": "Create backup of existing file (default: true)",
                        }
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "read_file",
                "description": "Enhanced file reading with options for line numbers and truncation. Always shows the exact path being read.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "The path of the file to read",
                        },
                        "show_line_numbers": {
                            "type": "boolean",
                            "description": "Show line numbers in output (default: false)",
                        },
                        "max_lines": {
                            "type": "integer",
                            "description": "Maximum number of lines to read (optional)",
                        }
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "list_files",
                "description": "Enhanced file listing with filtering and grouping options. Automatically filters out clutter like .git, __pycache__, node_modules, etc. Always shows the exact path being listed.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "The path of the folder to list (default: current directory)",
                        },
                        "group_by_type": {
                            "type": "boolean",
                            "description": "Group files by type/extension (default: false)",
                        },
                        "show_hidden": {
                            "type": "boolean",
                            "description": "Show hidden files starting with . (default: false)",
                        },
                        "ignore_patterns": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Additional patterns to ignore (beyond defaults)",
                        }
                    },
                },
            },
            {
                "name": "add_declarative_note",
                "description": "Add a declarative memory note about the user, project, or workflow.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": "The category of the note (e.g., 'user', 'project', 'workflow')",
                        },
                        "content": {
                            "type": "string",
                            "description": "The content of the note",
                        },
                    },
                    "required": ["category", "content"],
                },
            },
            {
                "name": "grep_search",
                "description": "Perform a grep-like search on the conversation history and files.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "The search pattern (regex). Multiple patterns can be separated by '|'",
                        },
                        "k": {
                            "type": "integer",
                            "description": "The number of results to return (default: 5)",
                        },
                        "case_sensitive": {
                            "type": "boolean",
                            "description": "Whether the search should be case-sensitive (default: false)",
                        },
                        "search_files": {
                            "type": "boolean",
                            "description": "Whether to search in files as well as conversation history (default: true)",
                        },
                    },
                    "required": ["pattern"],
                },
            },
            {
                "name": "memory_search",
                "description": "Search through conversation history and declarative memory using keyword and semantic matching.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The search query"},
                        "k": {
                            "type": "integer",
                            "description": "The number of results to return (default: 5)",
                        },
                        "memory_type": {"type": "string", "description": "Optional memory type filter"},
                        "categories": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "code_execution",
                "description": "Execute a snippet of Python code.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "The Python code to execute",
                        }
                    },
                    "required": ["code"],
                },
            },
            {
                "name": "get_file_map",
                "description": "Get the current file map of the project structure. You can specify a subdirectory to get a partial map.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "directory": {
                            "type": "string",
                            "description": "The directory to map (optional, defaults to root project directory)",
                        }
                    },
                },
            },
            {
                "name": "find_file",
                "description": "Enhanced file finding with pattern matching and filtering. Supports glob patterns like '*.py' or exact filenames. Always shows the search path being used.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "The pattern or name of the file to find (supports glob patterns)",
                        },
                        "search_path": {
                            "type": "string",
                            "description": "The path to start the search from (optional, defaults to root project directory)",
                        },
                        "include_hidden": {
                            "type": "boolean",
                            "description": "Include hidden files/directories (default: false)",
                        },
                        "file_type": {
                            "type": "string",
                            "enum": ["file", "directory"],
                            "description": "Filter by file type (optional)",
                        }
                    },
                    "required": ["filename"],
                },
            },
            {
                "name": "lint_python",
                "description": "Lint Python code or files using multiple linters (Flake8, Pylint, mypy, and Bandit).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "target": {
                            "type": "string",
                            "description": "The Python code snippet, file path, or directory to lint",
                        },
                        "is_file": {
                            "type": "boolean",
                            "description": "Whether the target is a file/directory path (true) or a code snippet (false)",
                        },
                    },
                    "required": ["target", "is_file"],
                },
            },
            {
                "name": "execute_command",
                "description": "Execute a shell command in the project root directory.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The shell command to execute",
                        }
                    },
                    "required": ["command"],
                },
            },
            {
                "name": "add_summary_note",
                "description": "Add a summary note for the current session.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": "The category of the summary (e.g., 'session', 'conversation')",
                        },
                        "content": {
                            "type": "string",
                            "description": "The content of the summary",
                        },
                    },
                    "required": ["category", "content"],
                },
            },
            {
                "name": "perplexity_search",
                "description": "Perform a web search using Perplexity API to get up-to-date information or additional context.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The search query"},
                        "max_results": {
                            "type": "integer",
                            "description": "The maximum number of results to return (default: 5)",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "browser_navigate",
                "description": "Navigate to a URL in the browser. Use this to open websites and web applications.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The full URL to navigate to (e.g., https://www.example.com)"
                        }
                    },
                    "required": ["url"]
                }
            },
            {
                "name": "browser_interact",
                "description": "Interact with elements on the current webpage. Use this for clicking buttons, filling forms, or submitting data.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["click", "input", "submit"],
                            "description": "The type of interaction to perform"
                        },
                        "selector": {
                            "type": "string",
                            "description": "CSS selector or XPath to identify the element"
                        },
                        "text": {
                            "type": "string",
                            "description": "Text to input (only required for 'input' action)"
                        }
                    },
                    "required": ["action", "selector"]
                }
            },
            {
                "name": "browser_screenshot",
                "description": "Capture a screenshot of the current webpage. Use this to see the page content visually or for verification.",
                "input_schema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "pydoll_browser_navigate",
                "description": "Navigate to a URL in the browser using PyDoll (no WebDriver required)",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "Full URL to navigate to"
                        }
                    },
                    "required": ["url"]
                }
            },
            {
                "name": "pydoll_browser_interact",
                "description": "Interact with page elements using PyDoll (no WebDriver required)",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["click", "input", "submit"]
                        },
                        "selector": {
                            "type": "string"
                        },
                        "selector_type": {
                            "type": "string",
                            "enum": ["css", "xpath", "id", "class_name"],
                            "default": "css"
                        },
                        "text": {
                            "type": "string",
                            "optional": True
                        }
                    },
                    "required": ["action", "selector"]
                }
            },
            {
                "name": "pydoll_browser_screenshot",
                "description": "Capture visible page content as image using PyDoll (no WebDriver required)",
                "input_schema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "pydoll_browser_scroll",
                "description": "Scroll the page or an element using PyDoll.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string", "enum": ["to", "by", "element", "page"]},
                        "to": {"type": "string", "enum": ["top", "bottom", "up", "down", "home", "end", "pageup", "pagedown"]},
                        "delta_y": {"type": "integer"},
                        "delta_x": {"type": "integer"},
                        "repeat": {"type": "integer"},
                        "selector": {"type": "string"},
                        "selector_type": {"type": "string", "enum": ["css", "xpath", "id", "class_name"]},
                        "behavior": {"type": "string", "enum": ["auto", "smooth"]}
                    },
                    "required": ["mode"]
                }
            },
            {
                "name": "analyze_codebase",
                "description": "Analyze codebase structure and dependencies using AST analysis.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "directory": {"type": "string", "description": "Directory to analyze (defaults to workspace root)"},
                        "analysis_type": {"type": "string", "enum": ["dependencies", "complexity", "patterns", "all"], "default": "all"},
                        "include_external": {"type": "boolean", "default": False},
                    },
                },
            },
            {
                "name": "reindex_workspace",
                "description": "Re-index workspace files into the active MemoryProvider.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "directory": {"type": "string", "description": "Directory to index (defaults to workspace root)"},
                        "force_full": {"type": "boolean", "default": False},
                        "file_types": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            {
                "name": "enhanced_diff",
                "description": "Compare two files with enhanced diff analysis. For Python files, shows semantic changes like added/removed functions and classes.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "file1": {
                            "type": "string",
                            "description": "Path to the first file to compare",
                        },
                        "file2": {
                            "type": "string", 
                            "description": "Path to the second file to compare",
                        },
                        "context_lines": {
                            "type": "integer",
                            "description": "Number of context lines to show (default: 3)",
                        },
                        "semantic": {
                            "type": "boolean",
                            "description": "Enable semantic analysis for Python files (default: true)",
                        }
                    },
                    "required": ["file1", "file2"],
                },
            },
            {
                "name": "analyze_project",
                "description": "Analyze project structure and dependencies using AST analysis. Shows file stats, imports, functions, and classes.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "directory": {
                            "type": "string",
                            "description": "Directory to analyze (default: current directory)",
                        },
                        "include_external": {
                            "type": "boolean",
                            "description": "Include external imports in analysis (default: false)",
                        }
                    },
                },
            },
            {
                "name": "apply_diff",
                "description": "Apply a unified diff to a file to make actual edits. This EDITS the file, not just compares it.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Path to the file to edit",
                        },
                        "diff_content": {
                            "type": "string",
                            "description": "The unified diff content to apply",
                        },
                        "backup": {
                            "type": "boolean",
                            "description": "Create backup of original file (default: true)",
                        }
                    },
                    "required": ["file_path", "diff_content"],
                },
            },
            {
                "name": "edit_with_pattern",
                "description": "Edit a file by finding and replacing text patterns using regex. This EDITS the file directly.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Path to the file to edit",
                        },
                        "search_pattern": {
                            "type": "string",
                            "description": "Regular expression pattern to search for",
                        },
                        "replacement": {
                            "type": "string",
                            "description": "Text to replace matches with",
                        },
                        "backup": {
                            "type": "boolean",
                            "description": "Create backup of original file (default: true)",
                        }
                    },
                    "required": ["file_path", "search_pattern", "replacement"],
                },
            },
            # Repository management tools
            {
                "name": "create_improvement_pr",
                "description": "Create a pull request for improvements to a GitHub repository. Use this when you make enhancements, optimizations, or general improvements to a codebase.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo_owner": {
                            "type": "string",
                            "description": "GitHub repository owner"
                        },
                        "repo_name": {
                            "type": "string",
                            "description": "GitHub repository name"
                        },
                        "title": {
                            "type": "string",
                            "description": "Title of the improvement PR"
                        },
                        "description": {
                            "type": "string", 
                            "description": "Detailed description of the improvements made"
                        },
                        "files_changed": {
                            "type": "string",
                            "description": "Comma-separated list of files that were changed (optional)"
                        }
                    },
                    "required": ["repo_owner", "repo_name", "title", "description"]
                }
            },
            {
                "name": "create_feature_pr",
                "description": "Create a pull request for a new feature in a GitHub repository. Use this when adding new functionality or capabilities to a codebase.",
                "input_schema": {
                    "type": "object", 
                    "properties": {
                        "repo_owner": {
                            "type": "string",
                            "description": "GitHub repository owner"
                        },
                        "repo_name": {
                            "type": "string",
                            "description": "GitHub repository name"
                        },
                        "feature_name": {
                            "type": "string",
                            "description": "Name of the new feature"
                        },
                        "description": {
                            "type": "string",
                            "description": "Description of what the feature does"
                        },
                        "implementation_notes": {
                            "type": "string",
                            "description": "Additional implementation details (optional)"
                        },
                        "files_modified": {
                            "type": "string",
                            "description": "Comma-separated list of files that were modified (optional)"
                        }
                    },
                    "required": ["repo_owner", "repo_name", "feature_name", "description"]
                }
            },
            {
                "name": "create_bugfix_pr",
                "description": "Create a pull request for a bug fix in a GitHub repository. Use this when fixing bugs, errors, or issues in a codebase.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo_owner": {
                            "type": "string",
                            "description": "GitHub repository owner"
                        },
                        "repo_name": {
                            "type": "string",
                            "description": "GitHub repository name"
                        },
                        "bug_description": {
                            "type": "string",
                            "description": "Description of the bug that was fixed"
                        },
                        "fix_description": {
                            "type": "string",
                            "description": "Description of how the bug was fixed"
                        },
                        "files_fixed": {
                            "type": "string",
                            "description": "Comma-separated list of files that were fixed (optional)"
                        }
                    },
                    "required": ["repo_owner", "repo_name", "bug_description", "fix_description"]
                }
            },
            {
                "name": "get_repository_status",
                "description": "Get the current status of a GitHub repository including branch, changed files, and GitHub configuration.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo_owner": {
                            "type": "string",
                            "description": "GitHub repository owner"
                        },
                        "repo_name": {
                            "type": "string",
                            "description": "GitHub repository name"
                        }
                    },
                    "required": ["repo_owner", "repo_name"]
                }
            },
            {
                "name": "commit_and_push_changes",
                "description": "Commit and push changes to the current branch in a GitHub repository. Use this to save your work before creating PRs.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo_owner": {
                            "type": "string",
                            "description": "GitHub repository owner"
                        },
                        "repo_name": {
                            "type": "string",
                            "description": "GitHub repository name"
                        },
                        "commit_message": {
                            "type": "string",
                            "description": "Commit message describing the changes"
                        },
                        "files_to_add": {
                            "type": "string", 
                            "description": "Comma-separated list of files to add, or leave empty to add all changes (optional)"
                        }
                    },
                    "required": ["repo_owner", "repo_name", "commit_message"]
                }
            },
            {
                "name": "create_and_switch_branch",
                "description": "Create a new git branch and switch to it in a GitHub repository. Use this before making changes that you want to turn into a PR.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo_owner": {
                            "type": "string",
                            "description": "GitHub repository owner"
                        },
                        "repo_name": {
                            "type": "string",
                            "description": "GitHub repository name"
                        },
                        "branch_name": {
                            "type": "string",
                            "description": "Name of the new branch to create"
                        }
                    },
                    "required": ["repo_owner", "repo_name", "branch_name"]
                }
            },
            # ================================================================
            # Sub-Agent / Multi-Agent Tools
            # ================================================================
            {
                "name": "send_message",
                "description": "Send a message to another agent or broadcast to a channel. Use for inter-agent coordination.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "The message content to send"
                        },
                        "target": {
                            "type": "string",
                            "description": "Single recipient agent ID (e.g., 'planner', 'implementer'). Omit to reach human operator."
                        },
                        "targets": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Multiple recipient agent IDs for broadcasting"
                        },
                        "channel": {
                            "type": "string",
                            "description": "Logical channel/room identifier (e.g., 'dev-room')"
                        },
                        "message_type": {
                            "type": "string",
                            "enum": ["message", "status", "action", "event"],
                            "description": "Type of message (default: 'message')"
                        },
                        "metadata": {
                            "type": "object",
                            "description": "Arbitrary key/value metadata to attach"
                        }
                    },
                    "required": ["content"]
                }
            },
            {
                "name": "spawn_sub_agent",
                "description": "Create a new sub-agent with isolated or shared session/context. The sub-agent can be used for parallel tasks.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Unique identifier for the sub-agent (required)"
                        },
                        "parent": {
                            "type": "string",
                            "description": "Parent agent ID (default: current agent)"
                        },
                        "persona": {
                            "type": "string",
                            "description": "Persona configuration name to apply"
                        },
                        "system_prompt": {
                            "type": "string",
                            "description": "Custom system prompt for the sub-agent"
                        },
                        "share_session": {
                            "type": "boolean",
                            "description": "Share parent's session (default: false)"
                        },
                        "share_context_window": {
                            "type": "boolean",
                            "description": "Share parent's context window (default: false)"
                        },
                        "shared_context_window_max_tokens": {
                            "type": "integer",
                            "description": "Token limit when using isolated context window"
                        },
                        "model_config_id": {
                            "type": "string",
                            "description": "Model configuration override"
                        },
                        "model_overrides": {
                            "type": "object",
                            "description": "Model parameter overrides"
                        },
                        "model_output_max_tokens": {
                            "type": "integer",
                            "description": "Max output tokens for the sub-agent"
                        },
                        "default_tools": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of tool names available to sub-agent (metadata only)"
                        },
                        "initial_prompt": {
                            "type": "string",
                            "description": "Initial message to send to the sub-agent after spawn"
                        },
                        "background": {
                            "type": "boolean",
                            "description": "Run agent in background (default: false). When true with initial_prompt, agent executes concurrently."
                        }
                    },
                    "required": ["id"]
                }
            },
            {
                "name": "stop_sub_agent",
                "description": "Pause a running sub-agent. Messages still log but engine-driven actions stop.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "The sub-agent ID to pause"
                        }
                    },
                    "required": ["id"]
                }
            },
            {
                "name": "resume_sub_agent",
                "description": "Resume a paused sub-agent.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "The sub-agent ID to resume"
                        }
                    },
                    "required": ["id"]
                }
            },
            {
                "name": "get_agent_status",
                "description": "Get status of background agents. Query a specific agent or get all agent statuses.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Specific agent ID to query (optional, returns all if omitted)"
                        },
                        "include_result": {
                            "type": "boolean",
                            "description": "Include result content in response (default: false)"
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "wait_for_agents",
                "description": "Wait for one or more background agents to complete.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of agent IDs to wait for (waits for all if omitted)"
                        },
                        "timeout": {
                            "type": "number",
                            "description": "Timeout in seconds (optional)"
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "get_context_info",
                "description": "Get context window sharing information for agents.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Agent ID to query (default: current agent)"
                        },
                        "include_stats": {
                            "type": "boolean",
                            "description": "Include token usage stats (default: false)"
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "sync_context",
                "description": "Synchronize context from parent to child agent (for agents with isolated context windows).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "parent": {
                            "type": "string",
                            "description": "Parent agent ID (source)"
                        },
                        "child": {
                            "type": "string",
                            "description": "Child agent ID (destination)"
                        },
                        "replace": {
                            "type": "boolean",
                            "description": "Replace existing context (default: false, appends)"
                        }
                    },
                    "required": ["parent", "child"]
                }
            },
            {
                "name": "delegate",
                "description": "Send a task to a specific sub-agent with delegation tracking.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "child": {
                            "type": "string",
                            "description": "Target sub-agent ID"
                        },
                        "content": {
                            "type": "string",
                            "description": "Task content to delegate"
                        },
                        "parent": {
                            "type": "string",
                            "description": "Parent agent ID (default: current agent)"
                        },
                        "channel": {
                            "type": "string",
                            "description": "Logical channel for the delegation"
                        },
                        "metadata": {
                            "type": "object",
                            "description": "Additional metadata (e.g., priority, deadline)"
                        },
                        "background": {
                            "type": "boolean",
                            "description": "Run delegated task in background (default: false)"
                        },
                        "wait": {
                            "type": "boolean",
                            "description": "Wait for result when background=true (default: false)"
                        },
                        "timeout": {
                            "type": "number",
                            "description": "Timeout in seconds when wait=true"
                        }
                    },
                    "required": ["child", "content"]
                }
            },
            {
                "name": "delegate_explore_task",
                "description": "Spawn a lightweight sub-agent to autonomously explore a codebase. Returns a summary.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "What to explore/analyze (e.g., 'Summarize the architecture')"
                        },
                        "directory": {
                            "type": "string",
                            "description": "Starting directory (default: current)"
                        },
                        "max_iterations": {
                            "type": "integer",
                            "description": "Max tool rounds (default: 100, max: 100)"
                        }
                    },
                    "required": ["task"]
                }
            },
        ]

    async def _background_initialize_async_components(self):
        """Background task to initialize async components and perform indexing."""
        try:
            with profile_operation("ToolManager.background_memory_init"):
                logger.info("Background: Initializing memory provider and starting indexing...")
                await self._ensure_memory_provider_and_index()
                self._indexing_completed = True
                logger.info("Background: Memory provider initialization and indexing completed")
        except Exception as e:
            logger.error(f"Background memory initialization failed: {e}", exc_info=True)

    async def _ensure_memory_provider_and_index(self):
        """Ensure memory provider is initialized and perform initial indexing."""
        if not self._memory_provider:
            with profile_operation("ToolManager.memory_provider_creation"):
                memory_config = {}
                try:
                    if hasattr(self.config, 'get'):
                        memory_config = self.config.get("memory", {})
                    elif hasattr(self.config, '__dict__'):
                        config_dict = self.config.__dict__
                        memory_config = config_dict.get("memory", {})
                    else:
                        memory_config = {}
                except Exception:
                    memory_config = {}
                self._memory_provider = self._initialize_memory_provider(memory_config)
        
        if not self._memory_provider:
            return
            
        with profile_operation("ToolManager.memory_provider_initialize"):
            await self._memory_provider.initialize()

        # Use generic IncrementalIndexer for initial scan
        try:
            with profile_operation("ToolManager.incremental_indexing"):
                from penguin.memory.indexing.incremental import IncrementalIndexer

                # Get workspace path with safe config access
                try:
                    if hasattr(self.config, 'get'):
                        workspace_path = Path(self.config.get("workspace", {}).get("path", "."))
                    elif hasattr(self.config, 'workspace_path'):
                        workspace_path = Path(self.config.workspace_path)
                    elif hasattr(self.config, '__dict__'):
                        config_dict = self.config.__dict__
                        workspace_path = Path(config_dict.get("workspace", {}).get("path", "."))
                    else:
                        workspace_path = Path(".")
                except Exception:
                    workspace_path = Path(".")
                notes_dir = workspace_path / "notes"
                conv_dir = workspace_path / "conversations"

                indexer_config = {
                    "workspace_path": str(workspace_path),
                }
                indexer = IncrementalIndexer(self._memory_provider, indexer_config)

                await indexer.start_workers(num_workers=2)

                # Only index the focused sub-directories to keep startup responsive
                if notes_dir.exists():
                    await indexer.sync_directory(str(notes_dir), force_full=False)
                if conv_dir.exists():
                    await indexer.sync_directory(str(conv_dir), force_full=False)

                await indexer.stop_workers()
                logger.info("Focused indexing of notes & conversations complete.")
        except Exception as e:
            logger.error(f"IncrementalIndexer failed: {e}. Falling back to simple indexing.")
            with profile_operation("ToolManager.fallback_indexing"):
                await self._initial_indexing()

    def _initialize_memory_provider(self, memory_config: Dict[str, Any]) -> Optional[MemoryProvider]:
        """Initialize the memory provider based on configuration."""
        if not memory_config.get("enabled", True):
            return None
        
        from penguin.memory.providers.factory import MemoryProviderFactory
        return MemoryProviderFactory.create_provider(memory_config)

    # Lazy loading properties with profiling
    @property
    def task_tools(self):
        """Lazy load task tools."""
        if not self._lazy_initialized['task_tools']:
            self._task_tools = TaskTools()
            self._lazy_initialized['task_tools'] = True
        return self._task_tools

    @property
    def declarative_memory_tool(self):
        if not self._lazy_initialized['declarative_memory_tool']:
            with profile_operation("ToolManager.lazy_load_declarative_memory_tool"):
                logger.debug("Lazy-loading declarative memory tool")
                self._declarative_memory_tool = DeclarativeMemoryTool()
                self._lazy_initialized['declarative_memory_tool'] = True
        return self._declarative_memory_tool
    
    @property
    def grep_search(self):
        if not self._lazy_initialized['grep_search']:
            with profile_operation("ToolManager.lazy_load_grep_search"):
                logger.debug("Lazy-loading grep search")
                self._grep_search = GrepSearch(root_dir=os.path.join(WORKSPACE_PATH, "logs"))
                self._lazy_initialized['grep_search'] = True
        return self._grep_search
    
    @property
    def file_map(self):
        if not self._lazy_initialized['file_map']:
            with profile_operation("ToolManager.lazy_load_file_map"):
                logger.debug("Lazy-loading file map")
                # Map the active file root (project/workspace)
                self._file_map = FileMap(self._file_root)
                self._lazy_initialized['file_map'] = True
        return self._file_map
    
    @property
    def summary_notes_tool(self):
        if not self._lazy_initialized['summary_notes_tool']:
            with profile_operation("ToolManager.lazy_load_summary_notes_tool"):
                logger.debug("Lazy-loading summary notes tool")
                # Use WORKSPACE_PATH for summary notes
                summary_notes_path = os.path.join(WORKSPACE_PATH, "notes", "summary_notes.yml")
                self._summary_notes_tool = SummaryNotes(summary_notes_path)
                self._lazy_initialized['summary_notes_tool'] = True
        return self._summary_notes_tool
    
    @property
    def notebook_executor(self):
        if not self._lazy_initialized['notebook_executor']:
            with profile_operation("ToolManager.lazy_load_notebook_executor"):
                logger.debug("Lazy-loading notebook executor")
                self._notebook_executor = NotebookExecutor()
                # Execute code relative to the selected file root when invoked
                try:
                    self._notebook_executor.active_directory = self._file_root
                except Exception:
                    pass
                self._lazy_initialized['notebook_executor'] = True
        return self._notebook_executor
    
    @property
    def perplexity_provider(self):
        if not self._lazy_initialized['perplexity_provider']:
            with profile_operation("ToolManager.lazy_load_perplexity_provider"):
                logger.debug("Lazy-loading perplexity provider")
                self._perplexity_provider = PerplexityProvider()
                self._lazy_initialized['perplexity_provider'] = True
        return self._perplexity_provider
    
    @property
    def permission_enforcer(self):
        """Lazy load permission enforcer with workspace boundary policy."""
        if self._permission_enforcer is None and self._permission_enabled:
            _ensure_permission_imports()
            if _PermissionEnforcer is not None:
                with profile_operation("ToolManager.lazy_load_permission_enforcer"):
                    logger.debug("Lazy-loading permission enforcer")
                    # Create enforcer with WORKSPACE mode by default
                    mode = _PermissionMode.WORKSPACE
                    yolo = os.environ.get("PENGUIN_YOLO", "").lower() in ("1", "true", "yes")
                    
                    self._permission_enforcer = _PermissionEnforcer(
                        mode=mode,
                        yolo=yolo,
                        audit_all=True,
                    )
                    
                    # Add workspace boundary policy
                    if _WorkspaceBoundaryPolicy is not None:
                        boundary_policy = _WorkspaceBoundaryPolicy(
                            workspace_root=self.workspace_root,
                            project_root=self.project_root,
                            mode=mode,
                        )
                        self._permission_enforcer.add_policy(boundary_policy)
                        logger.info(
                            f"Permission enforcer initialized: mode={mode.value}, "
                            f"workspace={self.workspace_root}, project={self.project_root}"
                        )
                    
                    # Configure audit logger from config if available
                    self._configure_audit_logger()
        return self._permission_enforcer
    
    def _configure_audit_logger(self) -> None:
        """Configure the audit logger from SecurityConfig if available."""
        try:
            from penguin.config import SecurityConfig
            from penguin.security.audit import configure_from_config
            
            # Get security config from our stored config dict
            security_data = self.config.get("security", {}) if self.config else {}
            if security_data:
                security_config = SecurityConfig.from_dict(security_data)
                configure_from_config(
                    audit_config=security_config.audit,
                    workspace_root=self.workspace_root,
                )
                logger.debug(
                    f"Audit logger configured: enabled={security_config.audit.enabled}, "
                    f"log_file={security_config.audit.log_file}"
                )
        except ImportError as e:
            logger.debug(f"Could not configure audit logger: {e}")
        except Exception as e:
            logger.warning(f"Failed to configure audit logger: {e}")
    
    def check_tool_permission(self, tool_name: str, tool_input: dict, context: dict = None) -> tuple:
        """Check if a tool execution is allowed.
        
        Args:
            tool_name: Name of the tool
            tool_input: Input parameters
            context: Additional context (agent_id, etc.)
        
        Returns:
            Tuple of (PermissionResult, reason) or (None, None) if permissions disabled
        """
        if not self._permission_enabled or self.permission_enforcer is None:
            return None, None
        
        _ensure_permission_imports()
        if _check_tool_permission is None:
            return None, None
        
        return _check_tool_permission(tool_name, tool_input, self.permission_enforcer, context)
    
    async def ensure_memory_provider(self) -> Optional[MemoryProvider]:
        """Ensure memory provider is initialized. Used for lazy loading."""
        if not self._lazy_initialized['memory_provider']:
            with profile_operation("ToolManager.lazy_load_memory_provider"):
                logger.debug("Lazy-loading memory provider")
                if not self._memory_provider:
                    memory_config = {}
                    try:
                        if hasattr(self.config, 'get'):
                            memory_config = self.config.get("memory", {})
                        elif hasattr(self.config, '__dict__'):
                            config_dict = self.config.__dict__
                            memory_config = config_dict.get("memory", {})
                        else:
                            memory_config = {}
                    except Exception:
                        memory_config = {}
                    
                    self._memory_provider = self._initialize_memory_provider(memory_config)
                
                if self._memory_provider:
                    await self._memory_provider.initialize()
                    
                    # Start background indexing if not already done
                    if not self._indexing_completed and not self._indexing_task:
                        try:
                            loop = asyncio.get_event_loop()
                            self._indexing_task = loop.create_task(self._background_initialize_async_components())
                            logger.info("Started background indexing task (lazy loaded)")
                        except RuntimeError:
                            # No event loop - do synchronous initialization
                            logger.info("No event loop - performing immediate indexing")
                            await self._ensure_memory_provider_and_index()
                            self._indexing_completed = True
                
                self._lazy_initialized['memory_provider'] = True
        
        return self._memory_provider
    
    @property
    def code_indexer(self):
        # Code indexer is currently disabled - raise helpful error
        raise NotImplementedError("Code indexer is currently disabled for performance reasons.")
    
    @property
    def memory_searcher(self):
        # Memory searcher is currently disabled - raise helpful error
        raise NotImplementedError("Memory searcher is currently disabled. Use memory_search via ToolManager instead.")
    
    # Browser tools lazy loading
    @property
    def browser_navigation_tool(self):
        if not self._lazy_initialized['browser_tools']:
            with profile_operation("ToolManager.lazy_load_browser_tools"):
                logger.debug("Lazy-loading browser tools")
                self._browser_navigation_tool = BrowserNavigationTool()
                self._browser_interaction_tool = BrowserInteractionTool()  
                self._browser_screenshot_tool = BrowserScreenshotTool()
                self._lazy_initialized['browser_tools'] = True
        return self._browser_navigation_tool
    
    @property
    def browser_interaction_tool(self):
        if not self._lazy_initialized['browser_tools']:
            with profile_operation("ToolManager.lazy_load_browser_tools"):
                logger.debug("Lazy-loading browser tools")
                self._browser_navigation_tool = BrowserNavigationTool()
                self._browser_interaction_tool = BrowserInteractionTool()  
                self._browser_screenshot_tool = BrowserScreenshotTool()
                self._lazy_initialized['browser_tools'] = True
        return self._browser_interaction_tool
    
    @property
    def browser_screenshot_tool(self):
        if not self._lazy_initialized['browser_tools']:
            with profile_operation("ToolManager.lazy_load_browser_tools"):
                logger.debug("Lazy-loading browser tools")
                self._browser_navigation_tool = BrowserNavigationTool()
                self._browser_interaction_tool = BrowserInteractionTool()  
                self._browser_screenshot_tool = BrowserScreenshotTool()
                self._lazy_initialized['browser_tools'] = True
        return self._browser_screenshot_tool
    
    # PyDoll tools lazy loading
    @property
    def pydoll_browser_navigation_tool(self):
        if not self._lazy_initialized['pydoll_tools']:
            with profile_operation("ToolManager.lazy_load_pydoll_tools"):
                logger.debug("Lazy-loading PyDoll browser tools")
                _ensure_pydoll_imports()  # Lazy import PyDoll modules
                self._pydoll_browser_navigation_tool = PyDollBrowserNavigationTool()
                self._pydoll_browser_interaction_tool = PyDollBrowserInteractionTool()
                self._pydoll_browser_screenshot_tool = PyDollBrowserScreenshotTool()
                self._pydoll_browser_scroll_tool = PyDollBrowserScrollTool()
                self._lazy_initialized['pydoll_tools'] = True
        return self._pydoll_browser_navigation_tool
    
    @property
    def pydoll_browser_interaction_tool(self):
        if not self._lazy_initialized['pydoll_tools']:
            with profile_operation("ToolManager.lazy_load_pydoll_tools"):
                logger.debug("Lazy-loading PyDoll browser tools")
                _ensure_pydoll_imports()  # Lazy import PyDoll modules
                self._pydoll_browser_navigation_tool = PyDollBrowserNavigationTool()
                self._pydoll_browser_interaction_tool = PyDollBrowserInteractionTool()
                self._pydoll_browser_screenshot_tool = PyDollBrowserScreenshotTool()
                self._pydoll_browser_scroll_tool = PyDollBrowserScrollTool()
                self._lazy_initialized['pydoll_tools'] = True
        return self._pydoll_browser_interaction_tool
    
    @property
    def pydoll_browser_screenshot_tool(self):
        if not self._lazy_initialized['pydoll_tools']:
            with profile_operation("ToolManager.lazy_load_pydoll_tools"):
                logger.debug("Lazy-loading PyDoll browser tools")
                _ensure_pydoll_imports()  # Lazy import PyDoll modules
                self._pydoll_browser_navigation_tool = PyDollBrowserNavigationTool()
                self._pydoll_browser_interaction_tool = PyDollBrowserInteractionTool()
                self._pydoll_browser_screenshot_tool = PyDollBrowserScreenshotTool()
                self._pydoll_browser_scroll_tool = PyDollBrowserScrollTool()
                self._lazy_initialized['pydoll_tools'] = True
        return self._pydoll_browser_screenshot_tool
    
    @property
    def pydoll_browser_scroll_tool(self):
        if not self._lazy_initialized['pydoll_tools']:
            with profile_operation("ToolManager.lazy_load_pydoll_tools"):
                logger.debug("Lazy-loading PyDoll browser tools")
                _ensure_pydoll_imports()  # Lazy import PyDoll modules
                self._pydoll_browser_navigation_tool = PyDollBrowserNavigationTool()
                self._pydoll_browser_interaction_tool = PyDollBrowserInteractionTool()
                self._pydoll_browser_screenshot_tool = PyDollBrowserScreenshotTool()
                self._pydoll_browser_scroll_tool = PyDollBrowserScrollTool()
                self._lazy_initialized['pydoll_tools'] = True
        return self._pydoll_browser_scroll_tool

    def get_tools(self):
        """Get available tool schemas."""
        return self.tools
    
    def get_responses_tools(self, allowed_names: Optional[List[str]] = None, include_web_search: bool = True) -> List[Dict[str, Any]]:
        """Return tools in OpenAI/Responses API function-calling format.

        Only include file/code/command related tools by default. Browser and process
        management tools are excluded unless explicitly allowed.
        """
        # Default curated set for file/code/command edits/executions
        default_allowed = [
            "create_folder",
            "create_file",
            "write_to_file",
            "read_file",
            "list_files",
            "find_file",
            "enhanced_diff",
            "analyze_project",
            "apply_diff",
            "edit_with_pattern",
            "multiedit_apply",
            "code_execution",
            "execute_command",
            "grep_search",
        ]
        allowed = set(allowed_names or default_allowed)
        responses_tools: List[Dict[str, Any]] = []
        for t in self.tools:
            name = t.get("name")
            if not name or name not in allowed:
                continue
            desc = t.get("description", "")
            params_schema = t.get("input_schema") or {"type": "object", "properties": {}}
            responses_tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": desc,
                    "parameters": params_schema,
                },
            })
        # Optionally add built-in Responses web_search tool
        if include_web_search:
            try:
                responses_tools.append({"type": "web_search"})
            except Exception:
                pass
        return responses_tools
    
    def get_tool(self, tool_name: str):
        """Get a tool instance on-demand with caching."""
        if tool_name in self._tool_instances:
            return self._tool_instances[tool_name]
        
        if tool_name not in self._tool_registry:
            raise ValueError(f"Unknown tool: {tool_name}")
        
        # Load the tool on first access
        tool_path = self._tool_registry[tool_name]
        
        if tool_path.startswith('self.'):
            # It's a method on this class or a property
            attr_name = tool_path.split('.', 1)[1]
            tool_instance = getattr(self, attr_name)
        else:
            # It's an external module/function
            module_path, func_name = tool_path.rsplit('.', 1)
            import importlib
            module = importlib.import_module(module_path)
            tool_instance = getattr(module, func_name)
        
        self._tool_instances[tool_name] = tool_instance
        return tool_instance
    
    def _execute_file_operation(self, operation_name: str, tool_input: dict) -> Union[str, dict]:
        """Execute file operations with enhanced tools and workspace integration."""
        if operation_name == "create_folder":
            from penguin.tools.core.support import create_folder
            return create_folder(os.path.join(self._file_root, tool_input["path"]))
        elif operation_name == "create_file":
            from penguin.tools.core.support import create_file
            return create_file(os.path.join(self._file_root, tool_input["path"]), tool_input.get("content", ""))
        elif operation_name == "write_to_file":
            from penguin.tools.core.support import enhanced_write_to_file
            return enhanced_write_to_file(
                tool_input["path"], 
                tool_input["content"],
                backup=tool_input.get("backup", True),
                workspace_path=self._file_root
            )
        elif operation_name == "read_file":
            from penguin.tools.core.support import enhanced_read_file
            return enhanced_read_file(
                tool_input["path"],
                show_line_numbers=tool_input.get("show_line_numbers", False),
                max_lines=tool_input.get("max_lines"),
                workspace_path=self._file_root
            )
        elif operation_name == "list_files":
            from penguin.tools.core.support import list_files_filtered
            return list_files_filtered(
                tool_input.get("path", "."),
                ignore_patterns=tool_input.get("ignore_patterns"),
                group_by_type=tool_input.get("group_by_type", False),
                show_hidden=tool_input.get("show_hidden", False),
                workspace_path=self._file_root
            )
        elif operation_name == "find_file":
            from penguin.tools.core.support import find_files_enhanced
            return find_files_enhanced(
                tool_input["filename"],
                search_path=tool_input.get("search_path", "."),
                include_hidden=tool_input.get("include_hidden", False),
                file_type=tool_input.get("file_type"),
                workspace_path=self._file_root
            )
        else:
            raise ValueError(f"Unknown file operation: {operation_name}")

    def _execute_enhanced_diff(self, tool_input: dict) -> str:
        """Execute enhanced diff with workspace integration."""
        from penguin.tools.core.support import enhanced_diff
        import threading, json
        try:
            default_timeout = int(os.environ.get('PENGUIN_TOOL_TIMEOUT_DIFF', os.environ.get('PENGUIN_TOOL_TIMEOUT', '120')))
        except Exception:
            default_timeout = 120

        result_container = {"done": False, "result": None, "error": None}

        def _runner():
            try:
                result_container["result"] = enhanced_diff(
                    tool_input["file1"],
                    tool_input["file2"],
                    context_lines=tool_input.get("context_lines", 3),
                    semantic=tool_input.get("semantic", True)
                )
            except Exception as e:
                result_container["error"] = str(e)
            finally:
                result_container["done"] = True

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        t.join(timeout=default_timeout)
        if not result_container["done"]:
            return json.dumps({"error": "timeout", "tool": "enhanced_diff", "timeout_seconds": default_timeout})
        if result_container["error"] is not None:
            return json.dumps({"error": result_container["error"], "tool": "enhanced_diff"})
        return result_container["result"]

    def _execute_analyze_project(self, tool_input: dict) -> str:
        """Execute project analysis with workspace integration."""
        from penguin.tools.core.support import analyze_project_structure
        import threading, json
        try:
            default_timeout = int(os.environ.get('PENGUIN_TOOL_TIMEOUT_ANALYZE', os.environ.get('PENGUIN_TOOL_TIMEOUT', '180')))
        except Exception:
            default_timeout = 180

        result_container = {"done": False, "result": None, "error": None}

        def _runner():
            try:
                result_container["result"] = analyze_project_structure(
                    directory=tool_input.get("directory", "."),
                    include_external=tool_input.get("include_external", False),
                    workspace_path=self._file_root
                )
            except Exception as e:
                result_container["error"] = str(e)
            finally:
                result_container["done"] = True

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        t.join(timeout=default_timeout)
        if not result_container["done"]:
            return json.dumps({"error": "timeout", "tool": "analyze_project", "timeout_seconds": default_timeout})
        if result_container["error"] is not None:
            return json.dumps({"error": result_container["error"], "tool": "analyze_project"})
        return result_container["result"]

    def _execute_apply_diff(self, tool_input: dict) -> str:
        """Execute diff application with workspace integration."""
        from penguin.tools.core.support import apply_diff_to_file
        import threading, json
        try:
            default_timeout = int(os.environ.get('PENGUIN_TOOL_TIMEOUT_EDIT', os.environ.get('PENGUIN_TOOL_TIMEOUT', '180')))
        except Exception:
            default_timeout = 180

        result_container = {"done": False, "result": None, "error": None}

        def _runner():
            try:
                result_container["result"] = apply_diff_to_file(
                    file_path=tool_input["file_path"],
                    diff_content=tool_input["diff_content"],
                    backup=tool_input.get("backup", True),
                    workspace_path=self._file_root
                )
            except Exception as e:
                result_container["error"] = str(e)
            finally:
                result_container["done"] = True

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        t.join(timeout=default_timeout)
        if not result_container["done"]:
            return json.dumps({"error": "timeout", "tool": "apply_diff", "timeout_seconds": default_timeout})
        if result_container["error"] is not None:
            return json.dumps({"error": result_container["error"], "tool": "apply_diff"})
        return result_container["result"]

    def _execute_edit_with_pattern(self, tool_input: dict) -> str:
        """Execute pattern-based editing with workspace integration."""
        from penguin.tools.core.support import edit_file_with_pattern
        import threading, json
        try:
            default_timeout = int(os.environ.get('PENGUIN_TOOL_TIMEOUT_EDIT', os.environ.get('PENGUIN_TOOL_TIMEOUT', '180')))
        except Exception:
            default_timeout = 180

        result_container = {"done": False, "result": None, "error": None}

        def _runner():
            try:
                result_container["result"] = edit_file_with_pattern(
                    file_path=tool_input["file_path"],
                    search_pattern=tool_input["search_pattern"],
                    replacement=tool_input["replacement"],
                    backup=tool_input.get("backup", True),
                    workspace_path=self._file_root
                )
            except Exception as e:
                result_container["error"] = str(e)
            finally:
                result_container["done"] = True

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        t.join(timeout=default_timeout)
        if not result_container["done"]:
            return json.dumps({"error": "timeout", "tool": "edit_with_pattern", "timeout_seconds": default_timeout})
        if result_container["error"] is not None:
            return json.dumps({"error": result_container["error"], "tool": "edit_with_pattern"})
        return result_container["result"]

    def _execute_multiedit(self, tool_input: dict) -> str:
        """Execute multiedit facade with workspace integration."""
        from penguin.tools.multiedit import apply_multiedit
        content = tool_input.get("content", "")
        do_apply = bool(tool_input.get("apply", False))
        # Map config toggles → environment for lower layers
        try:
            patches_cfg = None
            if hasattr(self.config, 'patches'):
                patches_cfg = getattr(self.config, 'patches')
            elif isinstance(self.config, dict):
                patches_cfg = self.config.get('patches')
            if patches_cfg:
                def _get(k, default=None):
                    try:
                        return getattr(patches_cfg, k)
                    except Exception:
                        try:
                            return patches_cfg.get(k, default)
                        except Exception:
                            return default
                robust = _get('robust')
                three_way = _get('three_way')
                shadow = _get('shadow')
                branch = _get('branch') or _get('branch_prefix')
                commit_message = _get('commit_message')
                if robust is not None:
                    os.environ['PENGUIN_PATCH_ROBUST'] = '1' if robust else '0'
                if three_way is not None:
                    os.environ['PENGUIN_PATCH_THREEWAY'] = '1' if three_way else '0'
                if shadow is not None:
                    os.environ['PENGUIN_PATCH_SHADOW'] = '1' if shadow else '0'
                if branch:
                    os.environ['PENGUIN_PATCH_BRANCH'] = str(branch)
                if commit_message:
                    os.environ['PENGUIN_PATCH_COMMIT_MSG'] = str(commit_message)
        except Exception:
            pass
        result = apply_multiedit(content, dry_run=(not do_apply), workspace_root=self._file_root)
        try:
            import json
            return json.dumps({
                "success": result.success,
                "files_edited": result.files_edited,
                "files_failed": result.files_failed,
                "error_messages": result.error_messages,
                "backup_paths": result.backup_paths,
                "rollback_performed": result.rollback_performed,
                "applied": do_apply,
            })
        except Exception:
            return f"success={result.success}, edited={len(result.files_edited)}, failed={len(result.files_failed)}"

    def set_project_root(self, project_root: Union[str, Path]) -> str:
        """Point the "project" root at a new directory (e.g., workspace project)."""
        try:
            resolved = Path(project_root).expanduser().resolve()
        except Exception as exc:  # pragma: no cover - defensive
            raise ValueError(f"Invalid project root '{project_root}': {exc}") from exc

        if not resolved.exists():
            raise ValueError(f"Project root does not exist: {resolved}")
        if not resolved.is_dir():
            raise ValueError(f"Project root must be a directory: {resolved}")

        self.project_root = str(resolved)
        logger.info("ToolManager project root -> %s", self.project_root)
        # Inform path_utils about the new logical cwd so security checks allow it.
        try:
            os.environ['PENGUIN_CWD'] = self.project_root
        except Exception:  # pragma: no cover - best effort
            pass

        if self.file_root_mode == 'project':
            self._file_root = self.project_root
            logger.info("ToolManager file root now %s (mode=project)", self._file_root)

        # Refresh file map so listings reflect the new root immediately.
        try:
            self._file_map = FileMap(self._file_root)
            self._lazy_initialized['file_map'] = True
        except Exception:  # pragma: no cover - lazily rebuild on first access
            self._lazy_initialized['file_map'] = False

        return f"Project root set to {self.project_root}"

    def set_execution_root(self, mode: str) -> str:
        """Switch active execution root between 'project' and 'workspace'."""
        mode_l = (mode or '').lower()
        if mode_l not in ('project', 'workspace'):
            return f"Invalid root mode '{mode}'. Use 'project' or 'workspace'."
        self.file_root_mode = mode_l
        self._file_root = self.project_root if mode_l == 'project' else self.workspace_root
        logger.info(
            "ToolManager execution root set to %s (@ %s)",
            self.file_root_mode,
            self._file_root,
        )
        # Update process-wide default write root so support.create_file/create_folder honor policy
        try:
            os.environ['PENGUIN_WRITE_ROOT'] = mode_l
            os.environ['PENGUIN_CWD'] = self._file_root
        except Exception:
            pass
        # Update notebook executor directory if loaded
        if self._lazy_initialized.get('notebook_executor') and self._notebook_executor:
            try:
                self._notebook_executor.active_directory = self._file_root
            except Exception:
                pass
        # Refresh file map to reflect new root
        try:
            self._file_map = FileMap(self._file_root)
            self._lazy_initialized['file_map'] = True
        except Exception:
            # Defer until first access
            self._lazy_initialized['file_map'] = False
        return f"Execution root set to {mode_l}: {self._file_root}"
    
    def on_runtime_config_change(self, config_key: str, new_value: Any) -> None:
        """Callback for RuntimeConfig changes (observer pattern).
        
        This method is called by RuntimeConfig when configuration values change,
        allowing ToolManager to react and update its internal state.
        
        Args:
            config_key: The configuration key that changed
            new_value: The new value for that key
        """
        logger.info(f"ToolManager received config change: {config_key}={new_value}")
        
        if config_key == 'project_root':
            # Update project root and refresh file map if in project mode
            self.project_root = str(new_value)
            if self.file_root_mode == 'project':
                self._file_root = self.project_root
                self._refresh_file_map()
                logger.info(f"ToolManager: Updated file_root to {self._file_root} (project mode)")
        
        elif config_key == 'workspace_root':
            # Update workspace root and refresh file map if in workspace mode
            self.workspace_root = str(new_value)
            if self.file_root_mode == 'workspace':
                self._file_root = self.workspace_root
                self._refresh_file_map()
                logger.info(f"ToolManager: Updated file_root to {self._file_root} (workspace mode)")
        
        elif config_key == 'execution_mode':
            # Switch execution mode
            mode_lower = str(new_value).lower()
            if mode_lower in ('project', 'workspace'):
                self.file_root_mode = mode_lower
                self._file_root = self.project_root if mode_lower == 'project' else self.workspace_root
                self._refresh_file_map()
                logger.info(f"ToolManager: Switched to {mode_lower} mode, file_root={self._file_root}")
                
                # Update notebook executor directory if loaded
                if self._lazy_initialized.get('notebook_executor') and self._notebook_executor:
                    try:
                        self._notebook_executor.active_directory = self._file_root
                    except Exception as e:
                        logger.warning(f"Could not update notebook executor directory: {e}")
    
    def _refresh_file_map(self) -> None:
        """Refresh the file map to reflect new root directory."""
        try:
            self._file_map = FileMap(self._file_root)
            self._lazy_initialized['file_map'] = True
            logger.debug(f"ToolManager: Refreshed file map for {self._file_root}")
        except Exception as e:
            logger.warning(f"ToolManager: Could not refresh file map: {e}")
            # Defer until first access
            self._lazy_initialized['file_map'] = False

    def execute_tool(self, tool_name: str, tool_input: dict, context: dict = None) -> Union[str, dict]:
        with profile_operation(f"ToolManager.execute_tool.{tool_name}"):
            # Check permission before executing
            if self._permission_enabled:
                result, reason = self.check_tool_permission(tool_name, tool_input, context)
                if result is not None:
                    _ensure_permission_imports()
                    if result == _PermissionResult.DENY:
                        logger.warning(f"Permission denied for tool '{tool_name}': {reason}")
                        return json.dumps({
                            "error": "permission_denied",
                            "tool": tool_name,
                            "reason": reason,
                        })
                    elif result == _PermissionResult.ASK:
                        # Phase 3: Approval flow
                        logger.info(f"Tool '{tool_name}' requires approval: {reason}")
                        
                        # Extract operation and resource for approval tracking
                        operation = context.get("operation", f"tool.{tool_name}") if context else f"tool.{tool_name}"
                        resource = tool_input.get("path", tool_input.get("file_path", tool_input.get("target", "")))
                        session_id = context.get("session_id") if context else None
                        
                        # Check for pre-approvals first
                        try:
                            from penguin.security.approval import get_approval_manager
                            approval_manager = get_approval_manager()
                            
                            # Check if pre-approved - if so, continue execution
                            if approval_manager.check_pre_approved(operation, resource, session_id):
                                logger.info(f"Tool '{tool_name}' pre-approved for {resource}")
                                # Pre-approved: fall through to tool execution below
                            else:
                                # Not pre-approved: create approval request and return pending status
                                approval_request = approval_manager.create_request(
                                    tool_name=tool_name,
                                    operation=operation,
                                    resource=resource,
                                    reason=reason,
                                    session_id=session_id,
                                    context={
                                        "tool_input": tool_input,
                                        "agent_id": context.get("agent_id") if context else None,
                                    },
                                )
                                
                                logger.info(f"Approval request created: {approval_request.id}")
                                return json.dumps({
                                    "status": "pending_approval",
                                    "approval_id": approval_request.id,
                                    "tool": tool_name,
                                    "operation": operation,
                                    "resource": resource,
                                    "reason": reason,
                                    "message": f"Tool '{tool_name}' requires approval. Approval ID: {approval_request.id}",
                                })
                        except ImportError:
                            # Approval module not available - BLOCK execution for security
                            # Tools requiring approval must not bypass when module is missing
                            logger.error(f"Approval module not available, blocking '{tool_name}' (approval required)")
                            return json.dumps({
                                "error": "approval_unavailable",
                                "tool": tool_name,
                                "operation": operation,
                                "resource": resource,
                                "reason": reason,
                                "message": f"Tool '{tool_name}' requires approval but approval system is unavailable.",
                            })
                        except Exception as approval_err:
                            # Error in approval flow - BLOCK execution for security
                            # Don't silently allow tools that require approval
                            logger.error(f"Error in approval flow for '{tool_name}': {approval_err}")
                            return json.dumps({
                                "error": "approval_error",
                                "tool": tool_name,
                                "operation": operation,
                                "resource": resource,
                                "reason": reason,
                                "message": f"Tool '{tool_name}' requires approval but an error occurred: {approval_err}",
                            })
            
            tool_map = {
                "create_folder": lambda: self._execute_file_operation("create_folder", tool_input),
                "create_file": lambda: self._execute_file_operation("create_file", tool_input),
                "write_to_file": lambda: self._execute_file_operation("write_to_file", tool_input),
                "read_file": lambda: self._execute_file_operation("read_file", tool_input),
                "list_files": lambda: self._execute_file_operation("list_files", tool_input),
                "find_file": lambda: self._execute_file_operation("find_file", tool_input),
                "add_declarative_note": lambda: self.add_declarative_note(
                    tool_input["category"], tool_input["content"]
                ),
                "grep_search": lambda: self.perform_grep_search(
                    tool_input["pattern"],
                    tool_input.get("k", 5),
                    tool_input.get("case_sensitive", False),
                    tool_input.get("search_files", True),
                ),
                "memory_search": lambda: self._execute_async_tool(self.perform_memory_search(
                    tool_input["query"],
                    tool_input.get("k", 5),
                    tool_input.get("memory_type"),
                    tool_input.get("categories"),
                )),
                "code_execution": lambda: self.execute_code(tool_input["code"]),
                "get_file_map": lambda: self.get_file_map(tool_input.get("directory", "")),
                "lint_python": lambda: lint_python(
                    tool_input["target"], tool_input["is_file"]
                ),
                "execute_command": lambda: self.execute_command(tool_input["command"]),
                "add_summary_note": lambda: self.add_summary_note(
                    tool_input["category"], tool_input["content"]
                ),
                # "tavily_search": lambda: self.tavily_search(tool_input["query"]),
                "perplexity_search": lambda: self.perplexity_provider.format_results(
                    self.perplexity_provider.search(
                        tool_input["query"], tool_input.get("max_results", 5)
                    )
                ),
                # "workspace_search": lambda: self.search_workspace(
                #     tool_input["query"], tool_input.get("max_results", 5)
                # ),
                # "memory_search": lambda: self.search_memory(
                #     tool_input["query"],
                #     tool_input.get("max_results", 5),
                #     tool_input.get("memory_type", None),
                #     tool_input.get("categories", None),
                #     tool_input.get("date_after", None),
                #     tool_input.get("date_before", None),
                # ),
                # "tavily_search": lambda: self.tavily_search(
                #     tool_input["query"],
                #     tool_input.get("max_results", 5),
                #     tool_input.get("search_depth", "advanced")
                # ),
                "browser_navigate": lambda: self._execute_async_tool(self.execute_browser_navigate(tool_input["url"])),
                "browser_interact": lambda: self._execute_async_tool(self.execute_browser_interact(
                    tool_input["action"], tool_input["selector"], tool_input.get("text")
                )),
                "browser_screenshot": lambda: self._execute_async_tool(self.execute_browser_screenshot()),
                "pydoll_browser_navigate": lambda: self._execute_async_tool(self.execute_pydoll_browser_navigate(tool_input["url"])),
                "pydoll_browser_interact": lambda: self._execute_async_tool(self.execute_pydoll_browser_interact(
                    tool_input["action"], tool_input["selector"], tool_input.get("selector_type", "css"), tool_input.get("text")
                )),
                "pydoll_browser_screenshot": lambda: self._execute_async_tool(self.execute_pydoll_browser_screenshot()),
                "analyze_codebase": lambda: self.analyze_codebase(
                    tool_input.get("directory"),
                    tool_input.get("analysis_type", "all"),
                    tool_input.get("include_external", False),
                ),
                "reindex_workspace": lambda: self._execute_async_tool(
                    self.reindex_workspace(
                        tool_input.get("directory"),
                        tool_input.get("force_full", False),
                        tool_input.get("file_types"),
                    )
                ),
                "enhanced_diff": lambda: self._execute_enhanced_diff(tool_input),
                "analyze_project": lambda: self._execute_analyze_project(tool_input),
                "apply_diff": lambda: self._execute_apply_diff(tool_input),
                "multiedit_apply": lambda: self._execute_multiedit(tool_input),
                "edit_with_pattern": lambda: self._execute_edit_with_pattern(tool_input),
                # Repository management tools
                "create_improvement_pr": lambda: create_improvement_pr(
                    tool_input["repo_owner"],
                    tool_input["repo_name"],
                    tool_input["title"],
                    tool_input["description"], 
                    tool_input.get("files_changed")
                ),
                "create_feature_pr": lambda: create_feature_pr(
                    tool_input["repo_owner"],
                    tool_input["repo_name"],
                    tool_input["feature_name"],
                    tool_input["description"],
                    tool_input.get("implementation_notes", ""),
                    tool_input.get("files_modified")
                ),
                "create_bugfix_pr": lambda: create_bugfix_pr(
                    tool_input["repo_owner"],
                    tool_input["repo_name"],
                    tool_input["bug_description"],
                    tool_input["fix_description"], 
                    tool_input.get("files_fixed")
                ),
                "get_repository_status": lambda: get_repository_status(
                    tool_input["repo_owner"],
                    tool_input["repo_name"]
                ),
                "commit_and_push_changes": lambda: commit_and_push_changes(
                    tool_input["repo_owner"],
                    tool_input["repo_name"],
                    tool_input["commit_message"],
                    tool_input.get("files_to_add")
                ),
                "create_and_switch_branch": lambda: create_and_switch_branch(
                    tool_input["repo_owner"],
                    tool_input["repo_name"],
                    tool_input["branch_name"]
                ),
                # Response/Task completion signals
                "finish_response": lambda: self.task_tools.finish_response(
                    tool_input.get("summary")
                ),
                "finish_task": lambda: self.task_tools.finish_task(
                    json.dumps(tool_input) if tool_input else None
                ),
                "task_completed": lambda: self.task_tools.task_completed(
                    tool_input.get("summary", "")
                ),
                # Sub-agent / Multi-agent tools
                "send_message": lambda: self._execute_async_tool(
                    self._execute_send_message(tool_input)
                ),
                "spawn_sub_agent": lambda: self._execute_async_tool(
                    self._execute_spawn_sub_agent(tool_input)
                ),
                "stop_sub_agent": lambda: self._execute_async_tool(
                    self._execute_stop_sub_agent(tool_input)
                ),
                "resume_sub_agent": lambda: self._execute_async_tool(
                    self._execute_resume_sub_agent(tool_input)
                ),
                "get_agent_status": lambda: self._execute_async_tool(
                    self._execute_get_agent_status(tool_input)
                ),
                "wait_for_agents": lambda: self._execute_async_tool(
                    self._execute_wait_for_agents(tool_input)
                ),
                "get_context_info": lambda: self._execute_async_tool(
                    self._execute_get_context_info(tool_input)
                ),
                "sync_context": lambda: self._execute_async_tool(
                    self._execute_sync_context(tool_input)
                ),
                "delegate": lambda: self._execute_async_tool(
                    self._execute_delegate(tool_input)
                ),
                "delegate_explore_task": lambda: self._execute_async_tool(
                    self._execute_delegate_explore_task(tool_input)
                ),
            }

            logging.info(f"Executing tool: {tool_name} with input: {tool_input}")
            if tool_name not in tool_map:
                error_message = f"Unknown tool: {tool_name}"
                logging.error(error_message)
                self.log_error(
                    Exception(error_message), f"Attempted to use unknown tool: {tool_name}"
                )
                return {"error": error_message}

            try:
                result = tool_map[tool_name]()
                if result is None or (isinstance(result, list) and len(result) == 0):
                    result = {"result": "No results found or empty directory."}
                self.add_message_to_search(
                    {"role": "assistant", "content": f"Tool use: {tool_name}"}
                )
                self.add_message_to_search(
                    {"role": "user", "content": f"Tool result: {result}"}
                )
                logging.info(
                    f"Tool {tool_name} executed successfully with result: {result}"
                )

                return result
            except Exception as e:
                error_message = f"Error executing tool {tool_name}: {str(e)}"
                logging.error(error_message)
                self.log_error(e, f"Error occurred while executing tool: {tool_name}")
                return {"error": error_message}

    def add_declarative_note(self, category, content):
        return self.declarative_memory_tool.add_note(category, content)

    def get_file_map(self, directory: str = "") -> str:
        return self.file_map.get_formatted_file_map(directory)

    def perform_grep_search(self, query, k=5, case_sensitive=False, search_files=True):
        patterns = query.split("|")  # Allow multiple patterns separated by |
        logging.info(f"Performing grep search with patterns: {patterns}")
        results = self.grep_search.search(patterns, k, case_sensitive, search_files)
        logging.info(f"Grep search returned {len(results)} results")
        formatted_results = []
        for result in results:
            if result["type"] == "file":
                formatted_results.append(
                    {
                        "type": "text",
                        "text": f"File: {result['path']}\nContent: {result['content']}\nMatch: {result['match']}",
                    }
                )
            else:
                formatted_results.append(
                    {
                        "type": "text",
                        "text": f"Message content: {result['content']}\nMatch: {result['match']}",
                    }
                )
        logging.info(f"Formatted {len(formatted_results)} results for output")
        return formatted_results

    def add_message_to_search(self, message):
        self.grep_search.add_message(message)

    def execute_code(self, code: str) -> str:
        import threading, json
        # Allow a separate timeout for code execution; fall back to general tool timeout
        try:
            default_timeout = int(os.environ.get('PENGUIN_TOOL_TIMEOUT_CODE', os.environ.get('PENGUIN_TOOL_TIMEOUT', '300')))
        except Exception:
            default_timeout = 300

        result_container = {"done": False, "result": None, "error": None}

        def _runner():
            try:
                result_container["result"] = self.notebook_executor.execute_code(code)
            except Exception as e:
                result_container["error"] = str(e)
            finally:
                result_container["done"] = True

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        t.join(timeout=default_timeout)

        if not result_container["done"]:
            return json.dumps({
                "error": "timeout",
                "tool": "code_execution",
                "timeout_seconds": default_timeout,
            })
        if result_container["error"] is not None:
            return json.dumps({
                "error": f"Error executing code: {result_container['error']}",
                "tool": "code_execution",
            })
        return result_container["result"] or ""

    def execute_command(self, command: str) -> str:
        try:
            # Determine the OS
            import platform

            os_type = platform.system().lower()

            # Adjust command based on OS
            if os_type == "windows":
                shell = True
                command = f"cmd /c {command}"
            else:  # Unix-like systems (Linux, macOS)
                shell = False
                command = ["bash", "-c", command]

            # Prepare environment to suppress Rich formatting
            env = os.environ.copy()
            env['TERM'] = 'dumb'
            env['NO_COLOR'] = '1'
            env['RICH_NO_MARKUP'] = '1'

            # Default timeout (seconds) for command tools
            try:
                default_timeout = int(os.environ.get('PENGUIN_TOOL_TIMEOUT', '60'))
            except Exception:
                default_timeout = 300
                # TODO: make this configurable
                # NOTE: You need to consider a case where it may be installing packages, etc.

            result = None
            try:
                result = subprocess.run(
                    command,
                    shell=shell,
                    capture_output=True,
                    text=True,
                    cwd=self._file_root,
                    env=env,  # Use environment with Rich suppression
                    timeout=default_timeout,
                )
            except subprocess.TimeoutExpired:
                return json.dumps({
                    "error": "timeout",
                    "tool": "execute_command",
                    "timeout_seconds": default_timeout,
                })

            if result.returncode == 0:
                return result.stdout.strip()
            else:
                return json.dumps({
                    "error": result.stderr.strip() or "command_failed",
                    "tool": "execute_command",
                    "returncode": result.returncode,
                })
        except Exception as e:
            return json.dumps({
                "error": f"Error executing command: {str(e)}",
                "tool": "execute_command",
            })

    def add_summary_note(self, category: str, content: str) -> str:
        self.summary_notes_tool.add_summary(category, content)
        return f"Summary note added: {category} - {content}"

    def get_summary_notes(self) -> List[Dict[str, Any]]:
        return self.summary_notes_tool.get_summaries()

    def encode_image(self, image_path: str) -> str:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    async def execute_browser_navigate(self, url: str) -> str:
        """Execute browser navigation to a URL"""
        try:
            result = await self.browser_navigation_tool.execute(url)
            return result
        except Exception as e:
            error_message = f"Error navigating to URL: {str(e)}"
            logging.error(error_message)
            self.log_error(e, error_message)
            return error_message
    
    async def execute_browser_interact(self, action: str, selector: str, text: Optional[str] = None) -> str:
        """Execute browser interaction with page elements"""
        try:
            result = await self.browser_interaction_tool.execute(action, selector, text)
            return result
        except Exception as e:
            error_message = f"Error interacting with browser: {str(e)}"
            logging.error(error_message)
            self.log_error(e, error_message)
            return error_message
    
    async def execute_browser_screenshot(self) -> Dict[str, Any]:
        """Execute browser screenshot capture"""
        try:
            result = await self.browser_screenshot_tool.execute()
            return result
        except Exception as e:
            error_message = f"Error capturing screenshot: {str(e)}"
            logging.error(error_message)
            self.log_error(e, error_message)
            return {"error": error_message}

    async def close_browser(self):
        """Close the browser instance if it exists"""
        return await browser_manager.close()

    async def execute_with_screenshot_on_error(self, coroutine, description="browser action"):
        """Execute a coroutine with screenshot capture on error"""
        try:
            return await coroutine
        except Exception as e:
            error_message = f"{description} failed: {str(e)}"
            logging.error(error_message)
            
            # Try to capture screenshot of error state
            try:
                page = await browser_manager.get_page()
                if page:
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    error_path = os.path.join(os.getcwd(), "error_screenshots", f"error_{timestamp}.png")
                    os.makedirs(os.path.dirname(error_path), exist_ok=True)
                    await page.screenshot(path=error_path)
                    logging.info(f"Error screenshot saved to {error_path}")
            except Exception as screenshot_e:
                logging.error(f"Failed to capture error screenshot: {str(screenshot_e)}")
            
            raise e

    async def execute_pydoll_browser_navigate(self, url: str) -> str:
        """Execute PyDoll browser navigation to a URL"""
        try:
            result = await self.pydoll_browser_navigation_tool.execute(url)
            return result
        except Exception as e:
            error_message = f"Error navigating to URL with PyDoll: {str(e)}"
            logging.error(error_message)
            self.log_error(e, error_message)
            return error_message
    
    async def execute_pydoll_browser_interact(self, action: str, selector: str, selector_type: str = "css", text: Optional[str] = None) -> str:
        """Execute PyDoll browser interaction with page elements"""
        try:
            result = await self.pydoll_browser_interaction_tool.execute(action, selector, selector_type, text)
            return result
        except Exception as e:
            error_message = f"Error interacting with browser using PyDoll: {str(e)}"
            logging.error(error_message)
            self.log_error(e, error_message)
            return error_message
    
    async def execute_pydoll_browser_screenshot(self) -> Dict[str, Any]:
        """Execute PyDoll browser screenshot capture"""
        try:
            result = await self.pydoll_browser_screenshot_tool.execute()
            return result
        except Exception as e:
            error_message = f"Error capturing screenshot with PyDoll: {str(e)}"
            logging.error(error_message)
            self.log_error(e, error_message)
            return {"error": error_message}

    async def close_pydoll_browser(self):
        """Close the PyDoll browser instance if it exists"""
        try:
            _ensure_pydoll_imports()
            return await pydoll_browser_manager.close()
        except ImportError as e:
            logger.warning(f"Cannot close PyDoll browser: {e}")
            return False

    def perform_memory_search_sync(
        self, query: str, k: int = 5, memory_type: Optional[str] = None, categories: Optional[List[str]] = None
    ) -> str:
        """Synchronous wrapper for memory search that handles async context properly."""
        try:
            # Check if we're already in an event loop
            loop = None
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # No event loop running, we can use asyncio.run()
                return asyncio.run(self.perform_memory_search(query, k, memory_type, categories))
            
            # We're in an event loop, so we need to handle this differently
            # For now, return an error message indicating the limitation
            return json.dumps({"error": "Memory search from sync context within async environment not yet supported. Use ActionExecutor instead."})
            
        except Exception as e:
            error_message = f"Error in synchronous memory search wrapper: {str(e)}"
            logger.error(error_message, exc_info=True)
            return json.dumps({"error": error_message})

    async def perform_memory_search(
        self, query: str, k: int = 5, memory_type: Optional[str] = None, categories: Optional[List[str]] = None
    ) -> str:
        """Perform a search using the configured MemoryProvider."""
        try:
            # Check if memory tools are enabled with safe config access
            try:
                if hasattr(self.config, 'get'):
                    tools_config = self.config.get("tools", {})
                    allow_memory_tools = tools_config.get("allow_memory_tools", False)
                    memory_config = self.config.get("memory")
                elif hasattr(self.config, '__dict__'):
                    config_dict = self.config.__dict__
                    tools_config = config_dict.get("tools", {})
                    allow_memory_tools = tools_config.get("allow_memory_tools", False) if isinstance(tools_config, dict) else False
                    memory_config = config_dict.get("memory")
                else:
                    allow_memory_tools = True  # Default to allowing memory tools
                    memory_config = {}
            except Exception:
                allow_memory_tools = True
                memory_config = {}
            
            if not allow_memory_tools:
                return json.dumps({"error": "Memory tools are disabled in config.yml."})
            
            if not memory_config:
                return json.dumps({"error": "Memory system is not configured in config.yml."})

            # Initialize provider if needed using the lazy loading mechanism
            memory_provider = await self.ensure_memory_provider()
            if not memory_provider:
                return json.dumps({"error": "Failed to initialize memory provider"})

            # Prepare filters
            filters = {}
            if memory_type:
                filters["memory_type"] = memory_type
            if categories:
                filters["categories"] = categories
            
            results = await memory_provider.search_memory(query, max_results=k, filters=filters)

            if not results:
                return json.dumps({"result": "No matches found."})

            return json.dumps(results, indent=2)
            
        except Exception as e:
            error_message = f"Error performing memory search: {str(e)}"
            logger.error(error_message, exc_info=True)
            return json.dumps({"error": error_message})

    def analyze_codebase(
        self, directory: Optional[str] = None, analysis_type: str = "all", include_external: bool = False
    ) -> str:
        """Analyze codebase structure and dependencies using AST analysis."""
        # Check if memory tools are enabled with safe config access
        try:
            if hasattr(self.config, 'get'):
                allow_memory_tools = self.config.get("tools", {}).get("allow_memory_tools", False)
            elif hasattr(self.config, '__dict__'):
                config_dict = self.config.__dict__
                tools_config = config_dict.get("tools", {})
                allow_memory_tools = tools_config.get("allow_memory_tools", False) if isinstance(tools_config, dict) else False
            else:
                allow_memory_tools = True  # Default to allowing
        except Exception:
            allow_memory_tools = True
            
        if not allow_memory_tools:
            return json.dumps({"error": "Code analysis tools are disabled in config.yml."})
        
        try:
            import ast
            from pathlib import Path
            from collections import defaultdict
            
            # Default to active file root if no directory is specified
            target_dir = Path(directory or self._file_root)
            
            if not target_dir.exists():
                return json.dumps({"error": f"Directory '{target_dir}' does not exist."})
            
            analysis_results = {
                "directory": str(target_dir),
                "analysis_type": analysis_type,
                "summary": {},
                "files_analyzed": 0,
                "errors": []
            }
            
            # Containers for analysis data
            all_functions = []
            all_classes = []
            all_imports = defaultdict(list)
            dependency_graph = defaultdict(set)
            complexity_metrics = {"total_lines": 0, "total_functions": 0, "total_classes": 0}
            
            # Find all Python files
            python_files = list(target_dir.rglob("*.py"))
            
            for file_path in python_files:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Parse the AST
                    tree = ast.parse(content)
                    relative_path = str(file_path.relative_to(target_dir))
                    
                    # Count lines
                    lines = len(content.splitlines())
                    complexity_metrics["total_lines"] += lines
                    
                    # Extract functions
                    functions = []
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef):
                            func_info = {
                                "name": node.name,
                                "line": node.lineno,
                                "args": len(node.args.args),
                                "is_async": isinstance(node, ast.AsyncFunctionDef),
                                "docstring": ast.get_docstring(node) is not None
                            }
                            functions.append(func_info)
                            all_functions.append({**func_info, "file": relative_path})
                    
                    complexity_metrics["total_functions"] += len(functions)
                    
                    # Extract classes
                    classes = []
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef):
                            methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                            class_info = {
                                "name": node.name,
                                "line": node.lineno,
                                "methods": methods,
                                "method_count": len(methods),
                                "docstring": ast.get_docstring(node) is not None
                            }
                            classes.append(class_info)
                            all_classes.append({**class_info, "file": relative_path})
                    
                    complexity_metrics["total_classes"] += len(classes)
                    
                    # Extract imports
                    imports = []
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                import_name = alias.name
                                imports.append(import_name)
                                all_imports[relative_path].append(import_name)
                                
                                # Track dependencies (only local imports if not include_external)
                                if include_external or not self._is_external_import(import_name):
                                    dependency_graph[relative_path].add(import_name)
                                    
                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                for alias in node.names:
                                    import_name = f"{node.module}.{alias.name}"
                                    imports.append(import_name)
                                    all_imports[relative_path].append(import_name)
                                    
                                    if include_external or not self._is_external_import(node.module):
                                        dependency_graph[relative_path].add(node.module)
                    
                    analysis_results["files_analyzed"] += 1
                    
                except Exception as e:
                    analysis_results["errors"].append(f"Failed to analyze {file_path}: {str(e)}")
            
            # Build summary based on analysis_type
            if analysis_type in ["all", "dependencies"]:
                analysis_results["dependencies"] = {
                    "import_count": sum(len(imports) for imports in all_imports.values()),
                    "dependency_graph": {k: list(v) for k, v in dependency_graph.items()},
                    "most_imported": self._get_most_common_imports(all_imports),
                    "circular_dependencies": self._detect_circular_dependencies(dependency_graph)
                }
            
            if analysis_type in ["all", "complexity"]:
                analysis_results["complexity"] = {
                    **complexity_metrics,
                    "avg_functions_per_file": complexity_metrics["total_functions"] / max(analysis_results["files_analyzed"], 1),
                    "avg_classes_per_file": complexity_metrics["total_classes"] / max(analysis_results["files_analyzed"], 1),
                    "avg_lines_per_file": complexity_metrics["total_lines"] / max(analysis_results["files_analyzed"], 1)
                }
            
            if analysis_type in ["all", "patterns"]:
                analysis_results["patterns"] = {
                    "async_functions": len([f for f in all_functions if f["is_async"]]),
                    "documented_functions": len([f for f in all_functions if f["docstring"]]),
                    "documented_classes": len([c for c in all_classes if c["docstring"]]),
                    "largest_classes": sorted(all_classes, key=lambda x: x["method_count"], reverse=True)[:5],
                    "function_complexity": self._analyze_function_complexity(all_functions)
                }
            
            # Generate summary
            analysis_results["summary"] = {
                "files": analysis_results["files_analyzed"],
                "total_lines": complexity_metrics["total_lines"],
                "functions": complexity_metrics["total_functions"],
                "classes": complexity_metrics["total_classes"],
                "imports": sum(len(imports) for imports in all_imports.values()) if all_imports else 0
            }
            
            return json.dumps(analysis_results, indent=2)
            
        except Exception as e:
            return json.dumps({"error": f"Failed to analyze codebase: {str(e)}"})

    def _is_external_import(self, import_name: str) -> bool:
        """Check if an import is external (not local to the project)."""
        external_patterns = [
            'os', 'sys', 'json', 'asyncio', 'logging', 'pathlib', 'datetime', 'time',
            'typing', 'collections', 'itertools', 'functools', 'operator',
            'requests', 'httpx', 'flask', 'django', 'fastapi', 'numpy', 'pandas',
            'torch', 'tensorflow', 'sklearn', 'matplotlib', 'seaborn',
            'pytest', 'unittest', 'mock'
        ]
        return any(import_name.startswith(pattern) for pattern in external_patterns)
    
    def _get_most_common_imports(self, all_imports: dict) -> list:
        """Get the most commonly imported modules."""
        from collections import Counter
        all_import_list = []
        for imports in all_imports.values():
            all_import_list.extend(imports)
        
        counter = Counter(all_import_list)
        return [{"module": module, "count": count} for module, count in counter.most_common(10)]
    
    def _detect_circular_dependencies(self, dependency_graph: dict) -> list:
        """Detect circular dependencies in the codebase."""
        circular = []
        
        def has_path(start, end, visited=None):
            if visited is None:
                visited = set()
            if start == end:
                return True
            if start in visited:
                return False
            visited.add(start)
            for dep in dependency_graph.get(start, set()):
                if has_path(dep, end, visited.copy()):
                    return True
            return False
        
        for file1 in dependency_graph:
            for dep in dependency_graph[file1]:
                if dep in dependency_graph and has_path(dep, file1):
                    circular.append({"file1": file1, "file2": dep})
        
        return circular
    
    def _analyze_function_complexity(self, all_functions: list) -> dict:
        """Analyze function complexity patterns."""
        arg_counts = [f["args"] for f in all_functions]
        return {
            "avg_args": sum(arg_counts) / len(arg_counts) if arg_counts else 0,
            "max_args": max(arg_counts) if arg_counts else 0,
            "functions_with_many_args": len([f for f in all_functions if f["args"] > 5]),
            "async_percentage": (len([f for f in all_functions if f["is_async"]]) / len(all_functions) * 100) if all_functions else 0
        }

    async def reindex_workspace(
        self, directory: Optional[str] = None, force_full: bool = False, file_types: Optional[List[str]] = None
    ) -> str:
        """Re-index workspace files into the active MemoryProvider."""
        # Check if memory tools are enabled with safe config access
        try:
            if hasattr(self.config, 'get'):
                allow_memory_tools = self.config.get("tools", {}).get("allow_memory_tools", False)
            elif hasattr(self.config, '__dict__'):
                config_dict = self.config.__dict__
                tools_config = config_dict.get("tools", {})
                allow_memory_tools = tools_config.get("allow_memory_tools", False) if isinstance(tools_config, dict) else False
            else:
                allow_memory_tools = True  # Default to allowing
        except Exception:
            allow_memory_tools = True
            
        if not allow_memory_tools:
            return json.dumps({"error": "Indexing tools are disabled in config.yml."})

        try:
            # Ensure provider exists using the lazy loading mechanism
            memory_provider = await self.ensure_memory_provider()
            if not memory_provider:
                return json.dumps({"error": "Failed to initialize memory provider"})

            start_time = time.time()
            workspace_path = Path(self.config.get("workspace", {}).get("path", "."))
            target_dir = Path(directory) if directory else workspace_path
            
            if not target_dir.exists():
                return json.dumps({"error": f"Directory '{target_dir}' does not exist."})

            # Default file types if not specified
            if file_types is None:
                file_types = [".py", ".md", ".txt", ".json", ".yml", ".yaml", ".toml", ".cfg", ".ini"]

            # Statistics tracking
            stats = {
                "files_processed": 0,
                "files_skipped": 0,
                "files_failed": 0,
                "conversations_indexed": 0,
                "notes_indexed": 0,
                "code_files_indexed": 0,
                "total_size_bytes": 0,
                "directories_scanned": set(),
                "errors": []
            }

            # Build file list
            all_files = []
            for file_type in file_types:
                pattern = f"*{file_type}" if not file_type.startswith("*") else file_type
                found_files = list(target_dir.rglob(pattern))
                all_files.extend(found_files)

            # Remove duplicates and filter
            unique_files = list(set(all_files))
            indexable_files = [
                f for f in unique_files 
                if f.is_file() and not any(ignore in str(f) for ignore in [".git", "__pycache__", ".DS_Store", "node_modules"])
            ]

            logger.info(f"Reindexing {len(indexable_files)} files (force_full={force_full})")

            # Process files in batches for better performance
            batch_size = 50
            for i in range(0, len(indexable_files), batch_size):
                batch = indexable_files[i:i + batch_size]
                
                # Process batch concurrently
                batch_tasks = []
                for file_path in batch:
                    stats["directories_scanned"].add(str(file_path.parent))
                    
                    # Skip if already indexed (unless force_full)
                    if not force_full and hasattr(self, '_indexed_files'):
                        file_hash = self._calculate_file_hash(file_path)
                        if file_hash in self._indexed_files:
                            stats["files_skipped"] += 1
                            continue
                    
                    batch_tasks.append(self._index_single_file(file_path, stats, memory_provider))
                
                # Execute batch
                if batch_tasks:
                    await asyncio.gather(*batch_tasks, return_exceptions=True)

            # Final statistics
            elapsed = time.time() - start_time
            stats["directories_scanned"] = len(stats["directories_scanned"])
            
            result = {
                "status": "completed",
                "duration_seconds": round(elapsed, 2),
                "target_directory": str(target_dir),
                "force_full": force_full,
                "file_types": file_types,
                "statistics": stats,
                "provider": type(memory_provider).__name__,
                "provider_stats": await memory_provider.get_memory_stats() if hasattr(memory_provider, 'get_memory_stats') else {}
            }

            logger.info(f"Workspace reindexing completed in {elapsed:.2f}s. Files: {stats['files_processed']} processed, {stats['files_skipped']} skipped, {stats['files_failed']} failed")
            
            return json.dumps(result, indent=2)

        except Exception as e:
            error_msg = f"Failed to reindex workspace: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return json.dumps({"error": error_msg, "details": str(e)})

    async def _index_single_file(self, file_path: Path, stats: dict, memory_provider: MemoryProvider) -> None:
        """Index a single file and update statistics."""
        try:
            file_size = file_path.stat().st_size
            stats["total_size_bytes"] += file_size
            
            # Handle different file types
            if file_path.suffix == ".json" and "conversations" in str(file_path):
                await self._index_conversation_file(file_path, memory_provider)
                stats["conversations_indexed"] += 1
            elif file_path.suffix in [".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".cpp", ".c", ".h"]:
                await self._index_code_file(file_path, memory_provider)
                stats["code_files_indexed"] += 1
            elif file_path.suffix in [".md", ".txt", ".rst"]:
                await self._index_text_file(file_path, memory_provider)
                stats["notes_indexed"] += 1
            else:
                # Generic text file indexing
                await self._index_generic_file(file_path, memory_provider)
            
            stats["files_processed"] += 1
            
        except Exception as e:
            stats["files_failed"] += 1
            stats["errors"].append(f"Failed to index {file_path}: {str(e)}")
            logger.warning(f"Failed to index {file_path}: {str(e)}")

    async def _index_code_file(self, file_path: Path, memory_provider: MemoryProvider) -> None:
        """Index a code file with AST analysis if Python."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            metadata = {
                "file_type": "code",
                "path": str(file_path),
                "language": file_path.suffix[1:],  # Remove the dot
                "size_bytes": len(content.encode('utf-8')),
                "indexed_at": datetime.now().isoformat()
            }
            
            # Add AST analysis for Python files
            if file_path.suffix == ".py":
                try:
                    import ast
                    tree = ast.parse(content)
                    
                    functions = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
                    classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
                    
                    metadata.update({
                        "functions": functions,
                        "classes": classes,
                        "function_count": len(functions),
                        "class_count": len(classes)
                    })
                except SyntaxError:
                    metadata["parse_error"] = "Syntax error in Python file"
            
            await memory_provider.add_memory(
                content=content,
                metadata=metadata,
                categories=["code", metadata["language"]]
            )
            
        except Exception as e:
            raise Exception(f"Code file indexing failed: {str(e)}")

    async def _index_text_file(self, file_path: Path, memory_provider: MemoryProvider) -> None:
        """Index a text/markdown file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            metadata = {
                "file_type": "text",
                "path": str(file_path),
                "format": file_path.suffix[1:],
                "size_bytes": len(content.encode('utf-8')),
                "indexed_at": datetime.now().isoformat()
            }
            
            # Extract markdown headers if it's a markdown file
            if file_path.suffix == ".md":
                import re
                headers = re.findall(r'^#+\s+(.+)$', content, re.MULTILINE)
                metadata["headers"] = headers[:10]  # Limit to first 10 headers
            
            await memory_provider.add_memory(
                content=content,
                metadata=metadata,
                categories=["text", metadata["format"], "notes"]
            )
            
        except Exception as e:
            raise Exception(f"Text file indexing failed: {str(e)}")

    async def _index_generic_file(self, file_path: Path, memory_provider: MemoryProvider) -> None:
        """Index a generic file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            metadata = {
                "file_type": "generic",
                "path": str(file_path),
                "extension": file_path.suffix[1:] if file_path.suffix else "no_extension",
                "size_bytes": len(content.encode('utf-8')),
                "indexed_at": datetime.now().isoformat()
            }
            
            await memory_provider.add_memory(
                content=content,
                metadata=metadata,
                categories=["files", metadata["extension"]]
            )
            
        except Exception as e:
            raise Exception(f"Generic file indexing failed: {str(e)}")

    def _calculate_file_hash(self, file_path: Path) -> str:
        """Calculate a simple hash for file change detection."""
        import hashlib
        stat = file_path.stat()
        # Use modification time and size as a simple hash
        return hashlib.md5(f"{stat.st_mtime}:{stat.st_size}".encode()).hexdigest()

    def _is_in_async_context(self) -> bool:
        """Check if we're currently running in an async event loop."""
        try:
            asyncio.get_running_loop()
            return True
        except RuntimeError:
            return False

    def _execute_async_tool(self, coro):
        """Execute an async tool properly depending on the current context."""
        try:
            # Check if we're already in an event loop
            loop = asyncio.get_running_loop()
            # We're in an event loop, so we need to run the coroutine directly
            # This is a hack that works for most cases by creating a new thread
            import concurrent.futures
            import threading
            
            result = None
            exception = None
            
            def run_in_thread():
                nonlocal result, exception
                try:
                    # Create a new event loop in this thread
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    result = new_loop.run_until_complete(coro)
                    new_loop.close()
                except Exception as e:
                    exception = e
            
            thread = threading.Thread(target=run_in_thread)
            thread.start()
            thread.join()
            
            if exception:
                raise exception
            return result
            
        except RuntimeError:
            # No event loop running, we can use asyncio.run()
            return asyncio.run(coro)

    async def _initial_indexing(self):
        """Perform initial indexing of workspace files."""
        # This is a temporary solution for Stage 1 to ensure memories are indexed.
        # In Stage 2, this will be replaced by the IncrementalIndexer and FileSystemWatcher.
        logger.info("Starting initial workspace indexing...")
        
        # Use lazy loading to get the memory provider
        memory_provider = await self.ensure_memory_provider()
        if not memory_provider:
            logger.error("Failed to initialize memory provider for initial indexing")
            return
        
        workspace_path = Path(self.config.get("workspace", {}).get("path", "."))
        notes_dir = workspace_path / "notes"
        conversations_dir = workspace_path / "conversations"
        
        files_indexed = 0
        
        async def index_directory(directory: Path, category: str):
            nonlocal files_indexed
            if not directory.exists():
                return
            
            for file_path in directory.rglob('*'):
                if not file_path.is_file():
                    continue
                
                try:
                    if category == "conversations" and file_path.suffix.lower() == '.json':
                        # Special handling for conversation JSON files
                        await self._index_conversation_file(file_path, memory_provider)
                        files_indexed += 1
                    elif file_path.suffix.lower() in {'.md', '.markdown', '.txt'}:
                        # Regular file indexing for notes and other text files
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        
                        metadata = {"source": str(file_path), "file_type": "text", "path": str(file_path)}
                        await memory_provider.add_memory(
                            content=content,
                            metadata=metadata,
                            categories=[category]
                        )
                        files_indexed += 1
                except Exception as e:
                    logger.error(f"Failed to index file {file_path}: {e}")

        await index_directory(notes_dir, "notes")
        await index_directory(conversations_dir, "conversations")
        
        if files_indexed > 0:
            logger.info(f"Initial indexing complete. Indexed {files_indexed} files.")
        else:
            logger.info("Initial indexing complete. No new files to index.")

    async def _index_conversation_file(self, file_path: Path, memory_provider: MemoryProvider):
        """Index individual messages from a conversation JSON file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                conversation_data = json.load(f)
            
            # Extract conversation metadata
            session_id = conversation_data.get('id', 'unknown')
            created_at = conversation_data.get('created_at', '')
            
            # Index each message individually
            messages = conversation_data.get('messages', [])
            for i, message in enumerate(messages):
                # Skip system messages (they're usually very long prompts)
                if message.get('role') == 'system':
                    continue
                
                content = message.get('content', '')
                
                # Handle content that might be a list or dict (some conversation formats)
                if isinstance(content, list):
                    content = ' '.join(str(item) for item in content)
                elif isinstance(content, dict):
                    content = str(content)
                elif not isinstance(content, str):
                    content = str(content)
                
                if not content.strip():
                    continue
                
                # Create rich metadata for each message
                metadata = {
                    "source": str(file_path),
                    "file_type": "conversation_message", 
                    "path": str(file_path),
                    "session_id": session_id,
                    "message_role": message.get('role', 'unknown'),
                    "message_id": message.get('id', f'msg_{i}'),
                    "timestamp": message.get('timestamp', created_at),
                    "message_index": i
                }
                
                # Add individual message to memory
                await memory_provider.add_memory(
                    content=content,
                    metadata=metadata,
                    categories=["conversations", "text", message.get('role', 'unknown')]
                )
                
        except Exception as e:
            logger.error(f"Failed to index conversation file {file_path}: {e}")
            # Fallback to indexing the raw JSON if parsing fails
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            metadata = {"source": str(file_path), "file_type": "text", "path": str(file_path)}
            await memory_provider.add_memory(
                content=content,
                metadata=metadata,
                categories=["conversations"]
            )

    # ------------------------------------------------------------------
    # Startup diagnostics helper
    # ------------------------------------------------------------------
    def get_startup_stats(self) -> Dict[str, Any]:
        """Return key statistics about ToolManager's startup state.

        This is used by PenguinCore and performance tests to inspect whether
        heavy components like the MemoryProvider were loaded eagerly, whether
        background indexing has finished, and which lazy-load flags have been
        triggered.
        """
        return {
            "fast_startup": getattr(self, "fast_startup", False),
            "memory_provider_exists": self._memory_provider is not None,
            "indexing_completed": getattr(self, "_indexing_completed", False),
            "lazy_initialized": self._lazy_initialized.copy(),
        }

    # ------------------------------------------------------------------
    # Sub-Agent / Multi-Agent Tools
    # ------------------------------------------------------------------

    def set_core(self, core: Any) -> None:
        """Inject PenguinCore reference for sub-agent tools.

        Args:
            core: The PenguinCore instance
        """
        self._core = core

    async def _execute_send_message(self, tool_input: Dict[str, Any]) -> str:
        """Execute send_message tool via MessageBus.

        Args:
            tool_input: Dict with content, target/targets, channel, message_type, metadata

        Returns:
            JSON string with result
        """
        content = tool_input.get("content", "")
        target = tool_input.get("target")
        targets = tool_input.get("targets", [])
        channel = tool_input.get("channel")
        message_type = tool_input.get("message_type", "message")
        metadata = tool_input.get("metadata", {})

        # Normalize targets
        if target and not targets:
            targets = [target]
        if not targets:
            targets = ["human"]  # Default to human operator

        # Get MessageBus instance
        try:
            from penguin.system.message_bus import MessageBus, ProtocolMessage
            bus = MessageBus.get_instance()
        except Exception as e:
            return json.dumps({"error": f"MessageBus unavailable: {e}"})

        results = []
        for tgt in targets:
            msg = ProtocolMessage(
                sender=None,  # Will be set by context
                recipient=tgt,
                content=content,
                message_type=message_type,
                metadata=metadata,
                channel=channel,
            )
            try:
                await bus.send(msg)
                results.append(tgt)
            except Exception as e:
                results.append(f"{tgt} (failed: {e})")

        return json.dumps({"sent_to": results, "status": "ok"})

    async def _execute_spawn_sub_agent(self, tool_input: Dict[str, Any]) -> str:
        """Execute spawn_sub_agent tool.

        Args:
            tool_input: Dict with agent configuration

        Returns:
            JSON string with result
        """
        agent_id = tool_input.get("id", "").strip()
        if not agent_id:
            return json.dumps({"error": "spawn_sub_agent requires 'id'"})

        if self._core is None:
            return json.dumps({"error": "Core unavailable for spawn_sub_agent. Call set_core() first."})

        parent_id = tool_input.get("parent", "default")
        share_session = bool(tool_input.get("share_session", False))
        share_cw = bool(tool_input.get("share_context_window", False))
        shared_cw_max = tool_input.get("shared_context_window_max_tokens")
        background = bool(tool_input.get("background", False))

        kwargs = {}
        for key in ("persona", "system_prompt", "model_config_id", "model_output_max_tokens", "default_tools"):
            if key in tool_input:
                kwargs[key] = tool_input[key]
        if isinstance(tool_input.get("model_overrides"), dict):
            kwargs["model_overrides"] = tool_input["model_overrides"]

        try:
            # Use core's create_sub_agent if available
            if hasattr(self._core, "create_sub_agent"):
                self._core.create_sub_agent(
                    agent_id,
                    parent_agent_id=parent_id,
                    share_session=share_session,
                    share_context_window=share_cw,
                    shared_context_window_max_tokens=shared_cw_max,
                    **kwargs,
                )
            else:
                # Fallback: use conversation_manager directly
                if hasattr(self._core, "conversation_manager"):
                    self._core.conversation_manager.create_sub_agent(
                        agent_id,
                        parent_id=parent_id,
                        share_session=share_session,
                        share_context_window=share_cw,
                        shared_context_window_max_tokens=shared_cw_max,
                    )
                else:
                    return json.dumps({"error": "Core has no create_sub_agent method"})
        except Exception as e:
            return json.dumps({"error": f"Failed to spawn sub-agent: {e}"})

        # Handle initial_prompt if provided
        initial_prompt = tool_input.get("initial_prompt")
        if initial_prompt:
            if background:
                # Run agent in background using AgentExecutor
                try:
                    from penguin.multi.executor import get_executor, set_executor, AgentExecutor
                    executor = get_executor()
                    if executor is None:
                        # Initialize executor with core
                        executor = AgentExecutor(self._core)
                        set_executor(executor)

                    await executor.spawn_agent(
                        agent_id,
                        initial_prompt,
                        metadata={
                            "parent": parent_id,
                            "share_session": share_session,
                            "share_context_window": share_cw,
                        }
                    )
                    return json.dumps({
                        "status": "ok",
                        "agent_id": agent_id,
                        "parent": parent_id,
                        "share_session": share_session,
                        "share_context_window": share_cw,
                        "background": True,
                        "message": f"Agent '{agent_id}' spawned and running in background",
                    })
                except Exception as e:
                    logger.error(f"Failed to spawn background agent {agent_id}: {e}")
                    return json.dumps({"error": f"Failed to spawn background agent: {e}"})
            else:
                # Synchronous: send message and wait
                try:
                    if hasattr(self._core, "send_to_agent"):
                        await self._core.send_to_agent(agent_id, initial_prompt)
                except Exception as e:
                    logger.warning(f"Failed to send initial_prompt to {agent_id}: {e}")

        return json.dumps({
            "status": "ok",
            "agent_id": agent_id,
            "parent": parent_id,
            "share_session": share_session,
            "share_context_window": share_cw,
            "background": background,
        })

    async def _execute_stop_sub_agent(self, tool_input: Dict[str, Any]) -> str:
        """Execute stop_sub_agent tool.

        Args:
            tool_input: Dict with agent id

        Returns:
            JSON string with result
        """
        agent_id = tool_input.get("id", "").strip()
        if not agent_id:
            return json.dumps({"error": "stop_sub_agent requires 'id'"})

        if self._core is None:
            return json.dumps({"error": "Core unavailable"})

        cancelled_background = False
        try:
            # Try to cancel background task if running in executor
            from penguin.multi.executor import get_executor
            executor = get_executor()
            if executor:
                status = executor.get_status(agent_id)
                if status and status.get("state") in ("pending", "running"):
                    cancelled_background = await executor.cancel(agent_id)

            # Also pause in conversation manager
            if hasattr(self._core, "set_agent_paused"):
                self._core.set_agent_paused(agent_id, True)
            elif hasattr(self._core, "conversation_manager"):
                cm = self._core.conversation_manager
                if hasattr(cm, "set_agent_paused"):
                    cm.set_agent_paused(agent_id, True)

            return json.dumps({
                "status": "ok",
                "agent_id": agent_id,
                "paused": True,
                "background_cancelled": cancelled_background,
            })
        except Exception as e:
            return json.dumps({"error": f"Failed to pause agent: {e}"})

    async def _execute_resume_sub_agent(self, tool_input: Dict[str, Any]) -> str:
        """Execute resume_sub_agent tool.

        Args:
            tool_input: Dict with agent id

        Returns:
            JSON string with result
        """
        agent_id = tool_input.get("id", "").strip()
        if not agent_id:
            return json.dumps({"error": "resume_sub_agent requires 'id'"})

        if self._core is None:
            return json.dumps({"error": "Core unavailable"})

        try:
            if hasattr(self._core, "set_agent_paused"):
                self._core.set_agent_paused(agent_id, False)
            elif hasattr(self._core, "conversation_manager"):
                cm = self._core.conversation_manager
                if hasattr(cm, "set_agent_paused"):
                    cm.set_agent_paused(agent_id, False)
            return json.dumps({"status": "ok", "agent_id": agent_id, "resumed": True})
        except Exception as e:
            return json.dumps({"error": f"Failed to resume agent: {e}"})

    async def _execute_get_agent_status(self, tool_input: Dict[str, Any]) -> str:
        """Get status of background agents.

        Args:
            tool_input: Dict with optional 'id' and 'include_result'

        Returns:
            JSON string with agent status(es)
        """
        from penguin.multi.executor import get_executor

        agent_id = tool_input.get("id", "").strip()
        include_result = bool(tool_input.get("include_result", False))

        executor = get_executor()
        if executor is None:
            return json.dumps({
                "status": "ok",
                "agents": {},
                "message": "No executor initialized - no background agents running"
            })

        if agent_id:
            # Query specific agent
            status = executor.get_status(agent_id)
            if status is None:
                return json.dumps({"error": f"Agent '{agent_id}' not found in executor"})

            if not include_result:
                status = {k: v for k, v in status.items() if k != "result"}

            return json.dumps({"status": "ok", "agent": status})
        else:
            # Query all agents
            all_status = executor.get_all_status()
            if not include_result:
                all_status = {
                    aid: {k: v for k, v in st.items() if k != "result"}
                    for aid, st in all_status.items()
                }

            stats = executor.get_stats()
            return json.dumps({
                "status": "ok",
                "agents": all_status,
                "stats": stats,
            })

    async def _execute_wait_for_agents(self, tool_input: Dict[str, Any]) -> str:
        """Wait for background agents to complete.

        Args:
            tool_input: Dict with optional 'ids' (list) and 'timeout'

        Returns:
            JSON string with results
        """
        from penguin.multi.executor import get_executor

        agent_ids = tool_input.get("ids")
        timeout = tool_input.get("timeout")

        executor = get_executor()
        if executor is None:
            return json.dumps({
                "status": "ok",
                "results": {},
                "message": "No executor initialized - no background agents to wait for"
            })

        try:
            results = await executor.wait_for_all(agent_ids, timeout=timeout)
            return json.dumps({
                "status": "ok",
                "results": results,
                "completed": len(results),
            })
        except asyncio.TimeoutError:
            # Return partial results on timeout
            partial = {}
            ids_to_check = agent_ids or list(executor._tasks.keys())
            for aid in ids_to_check:
                status = executor.get_status(aid)
                if status:
                    partial[aid] = {
                        "state": status.get("state"),
                        "result": status.get("result") if status.get("state") == "completed" else None,
                    }
            return json.dumps({
                "status": "timeout",
                "results": partial,
                "message": f"Timeout after {timeout}s waiting for agents",
            })

    async def _execute_get_context_info(self, tool_input: Dict[str, Any]) -> str:
        """Get context window sharing information for an agent.

        Args:
            tool_input: Dict with optional 'id' and 'include_stats'

        Returns:
            JSON string with context sharing info
        """
        if self._core is None:
            return json.dumps({"error": "Core unavailable"})

        agent_id = tool_input.get("id", "").strip() or "default"
        include_stats = bool(tool_input.get("include_stats", False))

        try:
            cm = self._core.conversation_manager
            if not hasattr(cm, "get_context_sharing_info"):
                return json.dumps({"error": "Context sharing info not available"})

            info = cm.get_context_sharing_info(agent_id)

            if include_stats and hasattr(cm, "get_context_window_stats"):
                stats = cm.get_context_window_stats(agent_id)
                if stats:
                    info["token_stats"] = stats

            # Add list of agents sharing same context window
            if hasattr(cm, "get_shared_context_agents"):
                shared_with = cm.get_shared_context_agents(agent_id)
                info["shares_context_with"] = shared_with

            return json.dumps({"status": "ok", **info})
        except Exception as e:
            return json.dumps({"error": f"Failed to get context info: {e}"})

    async def _execute_sync_context(self, tool_input: Dict[str, Any]) -> str:
        """Synchronize context from parent to child agent.

        Args:
            tool_input: Dict with 'parent', 'child', optional 'replace'

        Returns:
            JSON string with result
        """
        if self._core is None:
            return json.dumps({"error": "Core unavailable"})

        parent = tool_input.get("parent", "").strip()
        child = tool_input.get("child", "").strip()
        replace = bool(tool_input.get("replace", False))

        if not parent or not child:
            return json.dumps({"error": "sync_context requires 'parent' and 'child'"})

        try:
            cm = self._core.conversation_manager
            if not hasattr(cm, "sync_context_to_child"):
                return json.dumps({"error": "Context sync not available"})

            success = cm.sync_context_to_child(parent, child, replace_existing=replace)
            if success:
                return json.dumps({
                    "status": "ok",
                    "synced_from": parent,
                    "synced_to": child,
                    "replaced": replace,
                })
            else:
                return json.dumps({"error": "Context sync failed"})
        except Exception as e:
            return json.dumps({"error": f"Failed to sync context: {e}"})

    async def _execute_delegate(self, tool_input: Dict[str, Any]) -> str:
        """Execute delegate tool.

        Args:
            tool_input: Dict with child, content, parent, channel, metadata, background, wait, timeout

        Returns:
            JSON string with result
        """
        child = tool_input.get("child", "").strip()
        content = tool_input.get("content")
        if not child or content is None:
            return json.dumps({"error": "delegate requires 'child' and 'content'"})

        if self._core is None:
            return json.dumps({"error": "Core unavailable"})

        parent = tool_input.get("parent", "default")
        channel = tool_input.get("channel")
        metadata = tool_input.get("metadata", {})
        background = bool(tool_input.get("background", False))
        wait = bool(tool_input.get("wait", False))
        timeout = tool_input.get("timeout")

        try:
            if background:
                # Run delegated task in background using AgentExecutor
                from penguin.multi.executor import get_executor, set_executor, AgentExecutor
                executor = get_executor()
                if executor is None:
                    executor = AgentExecutor(self._core)
                    set_executor(executor)

                # Check if agent is already registered in executor
                status = executor.get_status(child)
                if status and status.get("state") in ("pending", "running"):
                    return json.dumps({
                        "error": f"Agent '{child}' is already running a background task"
                    })

                # Spawn background task
                await executor.spawn_agent(
                    child,
                    str(content),
                    metadata={
                        "parent": parent,
                        "channel": channel,
                        **(metadata or {}),
                    }
                )

                if wait:
                    # Wait for result
                    try:
                        result = await executor.wait_for(child, timeout=timeout)
                        return json.dumps({
                            "status": "ok",
                            "delegated_to": child,
                            "from": parent,
                            "background": True,
                            "waited": True,
                            "result": result,
                        })
                    except asyncio.TimeoutError:
                        return json.dumps({
                            "status": "timeout",
                            "delegated_to": child,
                            "from": parent,
                            "background": True,
                            "message": f"Agent '{child}' timed out after {timeout}s",
                        })
                else:
                    return json.dumps({
                        "status": "ok",
                        "delegated_to": child,
                        "from": parent,
                        "background": True,
                        "message": f"Task delegated to '{child}' running in background",
                    })
            else:
                # Synchronous delegation via message passing
                if hasattr(self._core, "send_to_agent"):
                    await self._core.send_to_agent(
                        child,
                        content,
                        message_type="message",
                        metadata=metadata,
                        channel=channel,
                    )
                else:
                    # Fallback via MessageBus
                    from penguin.system.message_bus import MessageBus, ProtocolMessage
                    bus = MessageBus.get_instance()
                    msg = ProtocolMessage(
                        sender=parent,
                        recipient=child,
                        content=content,
                        message_type="message",
                        metadata=metadata,
                        channel=channel,
                    )
                    await bus.send(msg)

                return json.dumps({
                    "status": "ok",
                    "delegated_to": child,
                    "from": parent,
                })
        except Exception as e:
            return json.dumps({"error": f"Failed to delegate: {e}"})

    async def _execute_delegate_explore_task(self, tool_input: Dict[str, Any]) -> str:
        """Execute delegate_explore_task using haiku for autonomous exploration.

        Args:
            tool_input: Dict with task, directory, max_iterations

        Returns:
            JSON string with exploration results
        """
        from penguin.constants import DELEGATE_EXPLORE_TASK_MAX_ITERATIONS_CAP
        from penguin.constants import get_engine_max_iterations_default
        from pathlib import Path
        import re

        task = tool_input.get("task", "").strip()
        if not task:
            return json.dumps({"error": "delegate_explore_task requires 'task'"})

        start_dir = tool_input.get("directory", ".")
        requested_max = tool_input.get("max_iterations", get_engine_max_iterations_default())
        max_iterations = min(int(requested_max), int(DELEGATE_EXPLORE_TASK_MAX_ITERATIONS_CAP))

        cwd = os.getcwd()

        # Simple tool implementations for the exploration sub-agent
        def execute_list_files(path: str) -> str:
            try:
                p = Path(path)
                if not p.exists():
                    return f"Directory not found: {path}"
                if not p.is_dir():
                    return f"Not a directory: {path}"
                items = []
                for item in sorted(p.iterdir())[:50]:
                    if item.name.startswith('.'):
                        continue
                    prefix = "D " if item.is_dir() else "F "
                    size = f" ({item.stat().st_size}b)" if item.is_file() else ""
                    items.append(f"{prefix}{item.name}{size}")
                return f"Contents of {path}:\n" + "\n".join(items) if items else f"{path} is empty"
            except Exception as e:
                return f"Error listing {path}: {e}"

        def execute_read_file(path: str, max_lines: int = 200) -> str:
            try:
                p = Path(path)
                if not p.exists():
                    return f"File not found: {path}"
                if not p.is_file():
                    return f"Not a file: {path}"
                if p.stat().st_size > 100000:  # 100KB limit
                    return f"File too large: {path}"
                content = p.read_text(errors='replace')
                lines = content.splitlines()[:max_lines]
                if len(content.splitlines()) > max_lines:
                    lines.append("... (truncated)")
                return f"=== {path} ===\n" + "\n".join(lines)
            except Exception as e:
                return f"Error reading {path}: {e}"

        def execute_search(pattern: str, path: str = ".") -> str:
            try:
                import subprocess
                result = subprocess.run(
                    ["grep", "-rn", "--include=*.py", "--include=*.js", "--include=*.ts",
                     "--include=*.md", "--include=*.json", pattern, path],
                    capture_output=True, text=True, timeout=10
                )
                matches = result.stdout.strip().splitlines()[:20]
                return f"Search results for '{pattern}':\n" + "\n".join(matches) if matches else f"No matches for '{pattern}'"
            except Exception as e:
                return f"Search error: {e}"

        def execute_tool(name: str, args: dict) -> str:
            if name == "list_files":
                return execute_list_files(args.get("path", "."))
            elif name == "read_file":
                return execute_read_file(args.get("path", ""), args.get("max_lines", 200))
            elif name == "search":
                return execute_search(args.get("pattern", ""), args.get("path", "."))
            return f"Unknown tool: {name}"

        system_prompt = f"""You are a codebase exploration assistant.

You have these tools:
- list_files: List directory contents
- read_file: Read a file (max 200 lines)
- search: Search for patterns in files

Current directory: {cwd}
Starting directory: {start_dir}

To use a tool, respond with JSON:
```json
{{"tool": "tool_name", "args": {{"param": "value"}}}}
```

When done exploring, provide your final summary WITHOUT any tool calls."""

        try:
            from penguin.llm.openrouter_gateway import OpenRouterGateway
            from penguin.llm.model_config import ModelConfig

            model_config = ModelConfig(
                model="anthropic/claude-haiku-4.5",
                provider="openrouter",
                max_output_tokens=2000,
            )
            gateway = OpenRouterGateway(model_config)

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]

            final_content = ""
            for iteration in range(max_iterations):
                response = await gateway.get_response(messages=messages)

                content = ""
                if isinstance(response, dict):
                    content = response.get("content", "")
                    if not content and "choices" in response:
                        choices = response.get("choices", [])
                        if choices:
                            content = choices[0].get("message", {}).get("content", "")
                elif hasattr(response, "content"):
                    content = response.content
                else:
                    content = str(response)

                final_content = content

                # Check for tool calls
                tool_match = re.search(r'```json\s*({[^`]+})\s*```', content, re.DOTALL)
                if tool_match:
                    try:
                        tool_json = json.loads(tool_match.group(1))
                        tool_name = tool_json.get("tool")
                        tool_args = tool_json.get("args", {})
                        result = execute_tool(tool_name, tool_args)
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user", "content": f"Tool result:\n{result}"})
                    except json.JSONDecodeError:
                        return f"[Haiku Explorer]:\n{content}"
                else:
                    return f"[Haiku Explorer]:\n{content}"

            return f"[Haiku Explorer] (max iterations reached):\n{final_content}"
        except Exception as e:
            return json.dumps({"error": f"delegate_explore_task failed: {e}"})
