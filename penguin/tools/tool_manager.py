import base64
import logging
import os
import subprocess
import asyncio
from typing import Any, Callable, Dict, List, Optional, Union
import datetime
import json
from pathlib import Path

# from utils.log_error import log_error
# from .core.support import create_folder, create_file, write_to_file, read_file, list_files, encode_image_to_base64, find_file
from penguin.config import config, WORKSPACE_PATH
from penguin.memory.summary_notes import SummaryNotes
from penguin.utils import FileMap

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
from penguin.tools.pydoll_tools import (
    pydoll_browser_manager, PyDollBrowserNavigationTool, PyDollBrowserInteractionTool, PyDollBrowserScreenshotTool
)
# from penguin.llm.model_manager import ModelManager
from penguin.memory.provider import MemoryProvider

logger = logging.getLogger(__name__) # Add logger

class ToolManager:
    def __init__(self, config: Dict[str, Any], log_error_func: Callable):
        # Fix HuggingFace tokenizers parallelism warning early, before any model loading
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        
        print("DEBUG: Initializing ToolManager...")
        self.config = config
        self.log_error = log_error_func
        
        # Initialize lightweight components immediately
        self.declarative_memory_tool = DeclarativeMemoryTool()
        self.grep_search = GrepSearch(root_dir=os.path.join(WORKSPACE_PATH, "logs"))
        self.file_map = FileMap(WORKSPACE_PATH)  # Initialize with the workspace path
        self.project_root = WORKSPACE_PATH  # Set project root to workspace path
        self.summary_notes_tool = SummaryNotes()
        
        # Lazily loaded components
        self._lazy_initialized = {
            'notebook_executor': False,
            'perplexity_provider': False,
            # 'code_indexer': False,
            # 'memory_searcher': False,
            'browser_tools': False,
            'pydoll_tools': False,
        }
        
        # Placeholder attributes for lazy loading
        self._notebook_executor = None
        self._perplexity_provider = None
        # self._code_indexer = None
        # self._memory_searcher = None
        
        # Browser tools placeholders
        self._browser_navigation_tool = None
        self._browser_interaction_tool = None
        self._browser_screenshot_tool = None
        
        # PyDoll tools placeholders
        self._pydoll_browser_navigation_tool = None
        self._pydoll_browser_interaction_tool = None
        self._pydoll_browser_screenshot_tool = None
        
        logger.info("ToolManager initialized with lazy loading for expensive components")

        self.tools = [
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
                "description": "Write content to a file at the specified path. If the file exists, only the necessary changes will be applied. If the file doesn't exist, it will be created. Always provide the full intended content of the file.",
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
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "read_file",
                "description": "Read the contents of a file at the specified path. Use this when you need to examine the contents of an existing file.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "The path of the file to read",
                        }
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "list_files",
                "description": "List all files and directories in the root folder where the script is running. Use this when you need to see the contents of the current directory.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "The path of the folder to list (default: current directory)",
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
                "description": "Find a file by name in the project structure. You can specify a search path or search from the root directory.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "The name of the file to find",
                        },
                        "search_path": {
                            "type": "string",
                            "description": "The path to start the search from (optional, defaults to root project directory)",
                        },
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
            # {
            #     "name": "workspace_search",
            #     "description": "Search through workspace code files using semantic search and AST parsing for accurate code lookups.",
            #     "input_schema": {
            #         "type": "object",
            #         "properties": {
            #             "query": {
            #                 "type": "string",
            #                 "description": "The search query - can be function name, class name, or general code concept",
            #             },
            #             "max_results": {
            #                 "type": "integer",
            #                 "description": "Maximum number of results to return (default: 5)",
            #             },
            #         },
            #         "required": ["query"],
            #     },
            # },
            # {
            #     "name": "memory_search",
            #     "description": "Search through memory logs and notes",
            #     "parameters": {
            #         "query": {"type": "string", "description": "The search query"},
            #         "max_results": {
            #             "type": "integer",
            #             "description": "Maximum number of results to return",
            #             "default": 5,
            #         },
            #         "memory_type": {
            #             "type": "string",
            #             "description": "Type of memory to search (logs/notes)",
            #             "optional": True,
            #         },
            #         "categories": {
            #             "type": "array",
            #             "description": "Categories to filter by",
            #             "optional": True,
            #         },
            #     },
            # },
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
        ]

        self.diagnostics_enabled = config.get("diagnostics", {}).get("enabled", False)
        
        # Initialize Memory Provider
        self._memory_provider = self._initialize_memory_provider(config.get("memory", {}))
        
        # Run one-time indexing
        if self._memory_provider:
            loop = asyncio.get_event_loop()
            loop.create_task(self.initialize_async_components())

    async def initialize_async_components(self):
        """Initializes async components like the memory provider and then indexes files."""
        if not self._memory_provider:
            return
        logger.info("Initializing asynchronous components...")
        await self._memory_provider.initialize()

        # Use generic IncrementalIndexer for initial scan
        try:
            from penguin.memory.indexing.incremental import IncrementalIndexer

            workspace_path = Path(self.config.get("workspace", {}).get("path", "."))
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
            await self._initial_indexing()

        logger.info("Asynchronous components initialized.")

    async def _initial_indexing(self):
        """Perform initial indexing of workspace files."""
        # This is a temporary solution for Stage 1 to ensure memories are indexed.
        # In Stage 2, this will be replaced by the IncrementalIndexer and FileSystemWatcher.
        logger.info("Starting initial workspace indexing...")
        
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
                        await self._index_conversation_file(file_path)
                        files_indexed += 1
                    elif file_path.suffix.lower() in {'.md', '.markdown', '.txt'}:
                        # Regular file indexing for notes and other text files
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        
                        metadata = {"source": str(file_path), "file_type": "text", "path": str(file_path)}
                        await self._memory_provider.add_memory(
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

    async def _index_conversation_file(self, file_path: Path):
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
                await self._memory_provider.add_memory(
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
            await self._memory_provider.add_memory(
                content=content,
                metadata=metadata,
                categories=["conversations"]
            )

    def _initialize_memory_provider(self, memory_config: Dict[str, Any]) -> Optional[MemoryProvider]:
        """Initialize the memory provider based on configuration."""
        if not memory_config.get("enabled", True):
            return None
        
        from penguin.memory.providers.factory import MemoryProviderFactory
        return MemoryProviderFactory.create_provider(memory_config)

    # Lazy loading properties
    @property
    def notebook_executor(self):
        if not self._lazy_initialized['notebook_executor']:
            logger.debug("Lazy-loading notebook executor")
            self._notebook_executor = NotebookExecutor()
            self._lazy_initialized['notebook_executor'] = True
        return self._notebook_executor
    
    @property
    def perplexity_provider(self):
        if not self._lazy_initialized['perplexity_provider']:
            logger.debug("Lazy-loading perplexity provider")
            self._perplexity_provider = PerplexityProvider()
            self._lazy_initialized['perplexity_provider'] = True
        return self._perplexity_provider
    
    @property
    def code_indexer(self):
        # if not self._lazy_initialized['code_indexer']:
        #     logger.debug("Lazy-loading code indexer (may take some time)")
        #     start_time = datetime.datetime.now()
        #     self._code_indexer = CodeIndexer(
        #         persist_directory=os.path.join(WORKSPACE_PATH, "chroma_db")
        #     )
        #     # Wait for initialization is still required, but now only when actually needed
        #     self._code_indexer.wait_for_initialization()
        #     self._lazy_initialized['code_indexer'] = True
        #     elapsed = (datetime.datetime.now() - start_time).total_seconds()
        #     logger.info(f"Code indexer initialized in {elapsed:.2f} seconds")
        # return self._code_indexer
        raise NotImplementedError("Code indexer is currently disabled.")
    
    @property
    def memory_searcher(self):
        # if not self._lazy_initialized['memory_searcher']:
        #     logger.debug("Lazy-loading memory searcher")
        #     start_time = datetime.datetime.now()
        #     self._memory_searcher = MemorySearcher()
        #     self._lazy_initialized['memory_searcher'] = True
        #     elapsed = (datetime.datetime.now() - start_time).total_seconds()
        #     logger.info(f"Memory searcher initialized in {elapsed:.2f} seconds")
        # return self._memory_searcher
        raise NotImplementedError("Memory searcher is currently disabled.")
    
    # Browser tools lazy loading
    @property
    def browser_navigation_tool(self):
        if not self._lazy_initialized['browser_tools']:
            logger.debug("Lazy-loading browser tools")
            self._browser_navigation_tool = BrowserNavigationTool()
            self._browser_interaction_tool = BrowserInteractionTool()  
            self._browser_screenshot_tool = BrowserScreenshotTool()
            self._lazy_initialized['browser_tools'] = True
        return self._browser_navigation_tool
    
    @property
    def browser_interaction_tool(self):
        if not self._lazy_initialized['browser_tools']:
            logger.debug("Lazy-loading browser tools")
            self._browser_navigation_tool = BrowserNavigationTool()
            self._browser_interaction_tool = BrowserInteractionTool()  
            self._browser_screenshot_tool = BrowserScreenshotTool()
            self._lazy_initialized['browser_tools'] = True
        return self._browser_interaction_tool
    
    @property
    def browser_screenshot_tool(self):
        if not self._lazy_initialized['browser_tools']:
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
            logger.debug("Lazy-loading PyDoll browser tools")
            self._pydoll_browser_navigation_tool = PyDollBrowserNavigationTool()
            self._pydoll_browser_interaction_tool = PyDollBrowserInteractionTool()
            self._pydoll_browser_screenshot_tool = PyDollBrowserScreenshotTool()
            self._lazy_initialized['pydoll_tools'] = True
        return self._pydoll_browser_navigation_tool
    
    @property
    def pydoll_browser_interaction_tool(self):
        if not self._lazy_initialized['pydoll_tools']:
            logger.debug("Lazy-loading PyDoll browser tools")
            self._pydoll_browser_navigation_tool = PyDollBrowserNavigationTool()
            self._pydoll_browser_interaction_tool = PyDollBrowserInteractionTool()
            self._pydoll_browser_screenshot_tool = PyDollBrowserScreenshotTool()
            self._lazy_initialized['pydoll_tools'] = True
        return self._pydoll_browser_interaction_tool
    
    @property
    def pydoll_browser_screenshot_tool(self):
        if not self._lazy_initialized['pydoll_tools']:
            logger.debug("Lazy-loading PyDoll browser tools")
            self._pydoll_browser_navigation_tool = PyDollBrowserNavigationTool()
            self._pydoll_browser_interaction_tool = PyDollBrowserInteractionTool()
            self._pydoll_browser_screenshot_tool = PyDollBrowserScreenshotTool()
            self._lazy_initialized['pydoll_tools'] = True
        return self._pydoll_browser_screenshot_tool

    def get_tools(self):
        return self.tools

    def execute_tool(self, tool_name: str, tool_input: dict) -> Union[str, dict]:
        tool_map = {
            # "create_folder": lambda: create_folder(os.path.join(WORKSPACE_PATH, tool_input["path"])),
            # "create_file": lambda: create_file(os.path.join(WORKSPACE_PATH, tool_input["path"]), tool_input.get("content", "")),
            # "write_to_file": lambda: write_to_file(os.path.join(WORKSPACE_PATH, tool_input["path"]), tool_input["content"]),
            # "read_file": lambda: read_file(os.path.join(WORKSPACE_PATH, tool_input["path"])),
            # "list_files": lambda: list_files(os.path.join(WORKSPACE_PATH, tool_input.get("path", "."))),
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
            # "find_file": lambda: find_file(tool_input["filename"], tool_input.get("search_path", ".")),
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
            "browser_navigate": lambda: asyncio.run(self.execute_browser_navigate(tool_input["url"])),
            "browser_interact": lambda: asyncio.run(self.execute_browser_interact(
                tool_input["action"], tool_input["selector"], tool_input.get("text")
            )),
            "browser_screenshot": lambda: asyncio.run(self.execute_browser_screenshot()),
            "pydoll_browser_navigate": lambda: asyncio.run(self.execute_pydoll_browser_navigate(tool_input["url"])),
            "pydoll_browser_interact": lambda: asyncio.run(self.execute_pydoll_browser_interact(
                tool_input["action"], tool_input["selector"], tool_input.get("selector_type", "css"), tool_input.get("text")
            )),
            "pydoll_browser_screenshot": lambda: asyncio.run(self.execute_pydoll_browser_screenshot()),
            "analyze_codebase": lambda: self.analyze_codebase(
                tool_input.get("directory"),
                tool_input.get("analysis_type", "all"),
                tool_input.get("include_external", False),
            ),
            "reindex_workspace": lambda: asyncio.run(
                self.reindex_workspace(
                    tool_input.get("directory"),
                    tool_input.get("force_full", False),
                    tool_input.get("file_types"),
                )
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
        return self.notebook_executor.execute_code(code)

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

            result = subprocess.run(
                command,
                shell=shell,
                capture_output=True,
                text=True,
                cwd=self.project_root,
            )

            if result.returncode == 0:
                return result.stdout.strip()
            else:
                return f"Error: {result.stderr.strip()}"
        except Exception as e:
            return f"Error executing command: {str(e)}"

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
        return await pydoll_browser_manager.close()

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
            # Check if memory tools are enabled
            tools_config = self.config.get("tools", {})
            
            if not tools_config.get("allow_memory_tools", False):
                return json.dumps({"error": "Memory tools are disabled in config.yml."})

            memory_config = self.config.get("memory")
            
            if not memory_config:
                return json.dumps({"error": "Memory system is not configured in config.yml."})

            # Initialize provider if needed
            if not hasattr(self, "_memory_provider") or self._memory_provider is None:
                from penguin.memory.providers.factory import MemoryProviderFactory
                
                self._memory_provider = MemoryProviderFactory.create_provider(memory_config)
                
                await self._memory_provider.initialize()

            # Prepare filters
            filters = {}
            if memory_type:
                filters["memory_type"] = memory_type
            if categories:
                filters["categories"] = categories
            
            results = await self._memory_provider.search_memory(query, max_results=k, filters=filters)

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
        """Placeholder for code analysis. Integrates with the DependencyMapper tool."""
        if not self.config.get("tools", {}).get("allow_memory_tools", False):
            return json.dumps({"error": "Code analysis tools are disabled in config.yml."})
        
        try:
            from penguin.tools.core.dependency_mapper import DependencyMapper
            
            # Default to project root if no directory is specified
            target_dir = directory or self.project_root
            mapper = DependencyMapper(str(target_dir))
            
            # This is a synchronous placeholder. In a real scenario, this would
            # be an async call and properly formatted.
            # analysis_result = asyncio.run(mapper.analyze_workspace())
            
            return json.dumps({"result": f"Code analysis for '{analysis_type}' on '{target_dir}' is not fully implemented yet."})
        except Exception as e:
            return json.dumps({"error": f"Failed to analyze codebase: {e}"})

    async def reindex_workspace(
        self, directory: Optional[str] = None, force_full: bool = False, file_types: Optional[List[str]] = None
    ) -> str:
        """Re-index workspace files into the active MemoryProvider."""
        if not self.config.get("tools", {}).get("allow_memory_tools", False):
            return json.dumps({"error": "Indexing tools are disabled in config.yml."})

        try:
            # Ensure provider exists
            if not hasattr(self, "_memory_provider") or self._memory_provider is None:
                from penguin.memory.providers.factory import MemoryProviderFactory
                self._memory_provider = MemoryProviderFactory.create_provider(self.config.get("memory"))
                await self._memory_provider.initialize()

            # Call provider's own indexing routine if available
            if hasattr(self._memory_provider, "index_memory_files"):
                result_msg = await self._memory_provider.index_memory_files()
                return json.dumps({"result": result_msg})
            else:
                return json.dumps({"error": "Active MemoryProvider does not support file indexing."})
        except Exception as e:
            return json.dumps({"error": f"Re-index failed: {e}"})

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
