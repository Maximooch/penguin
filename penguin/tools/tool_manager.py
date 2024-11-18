import os
import json
import io
import sys
import logging
import time 
import random 
import requests # type: ignore
from requests.exceptions import RequestException # type: ignore
from typing import List, Dict, Any, Callable, Union
from utils import FileMap
import subprocess
# from utils.log_error import log_error

# from .support import create_folder, create_file, write_to_file, read_file, list_files, encode_image_to_base64, find_file

from bs4 import BeautifulSoup # type: ignore
from .declarative_memory_tool import DeclarativeMemoryTool
from .grep_search import GrepSearch
from .lint_python import lint_python
from .memory_search import MemorySearch
from utils.notebook import NotebookExecutor
from memory.summary_notes import SummaryNotes
from .duck import duckduckgo_search as ddg_search
# from .tavily import TavilySearch
from tavily import TavilyClient
from .perplexity_tool import PerplexityProvider

from config import WORKSPACE_PATH, TAVILY_API_KEY

class ToolManager:
    def __init__(self, log_error_func: Callable):
        # from utils.file_map import FileMap  # Import here to avoid circular import
        self.log_error = log_error_func
        self.declarative_memory_tool = DeclarativeMemoryTool()
        self.grep_search = GrepSearch(root_dir=os.path.join(WORKSPACE_PATH, "logs"))
        self.memory_search = MemorySearch(os.path.join(WORKSPACE_PATH, "logs"))
        self.file_map = FileMap(WORKSPACE_PATH)  # Initialize with the workspace path
        self.project_root = WORKSPACE_PATH  # Set project root to workspace path
        self.notebook_executor = NotebookExecutor()
        self.summary_notes_tool = SummaryNotes()
        tavily_api_key = TAVILY_API_KEY
        self.tavily_client = TavilyClient(api_key=tavily_api_key)
        self.perplexity_provider = PerplexityProvider()
        self.tools = [
            {
                "name": "create_folder",
                "description": "Create a new folder at the specified path. Use this when you need to create a new directory in the project structure.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "The path where the folder should be created"
                        }
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "create_file",
                "description": "Create a new file at the specified path with optional content. Use this when you need to create a new file in the project structure.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "The path where the file should be created"
                        },
                        "content": {
                            "type": "string",
                            "description": "The initial content of the file (optional)"
                        }
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "write_to_file",
                "description": "Write content to a file at the specified path. If the file exists, only the necessary changes will be applied. If the file doesn't exist, it will be created. Always provide the full intended content of the file.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "The path of the file to write to"
                        },
                        "content": {
                            "type": "string",
                            "description": "The full content to write to the file"
                        }
                    },
                    "required": ["path", "content"]
                }
            },
            {
                "name": "read_file",
                "description": "Read the contents of a file at the specified path. Use this when you need to examine the contents of an existing file.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "The path of the file to read"
                        }
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "list_files",
                "description": "List all files and directories in the root folder where the script is running. Use this when you need to see the contents of the current directory.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "The path of the folder to list (default: current directory)"
                        }
                    }
                }
            },
            {
            "name": "add_declarative_note",
            "description": "Add a declarative memory note about the user, project, or workflow.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "The category of the note (e.g., 'user', 'project', 'workflow')"
                    },
                    "content": {
                        "type": "string",
                        "description": "The content of the note"
                    }
                },
                "required": ["category", "content"]
            }
        },
        {
            "name": "grep_search",
            "description": "Perform a grep-like search on the conversation history and files.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "The search pattern (regex). Multiple patterns can be separated by '|'"
                    },
                    "k": {
                        "type": "integer",
                        "description": "The number of results to return (default: 5)"
                    },
                    "case_sensitive": {
                        "type": "boolean",
                        "description": "Whether the search should be case-sensitive (default: false)"
                    },
                    "search_files": {
                        "type": "boolean",
                        "description": "Whether to search in files as well as conversation history (default: true)"
                    }
                },
                "required": ["pattern"]
            }
        },
        {
            "name": "memory_search",
            "description": "Search through conversation history and declarative memory using keyword and semantic matching.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    },
                    "k": {
                        "type": "integer",
                        "description": "The number of results to return (default: 5)"
                    }
                },
                "required": ["query"]
            }
        },
        {
            "name": "code_execution",
            "description": "Execute a snippet of Python code.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The Python code to execute"
                    }
                },
                "required": ["code"]
            }
        },
        {
            "name": "get_file_map",
            "description": "Get the current file map of the project structure. You can specify a subdirectory to get a partial map.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "The directory to map (optional, defaults to root project directory)"
                    }
                }
            }
        },
        {
            "name": "find_file",
            "description": "Find a file by name in the project structure. You can specify a search path or search from the root directory.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "The name of the file to find"
                    },
                    "search_path": {
                        "type": "string",
                        "description": "The path to start the search from (optional, defaults to root project directory)"
                    }
                },
                "required": ["filename"]
            }
        },
        {
            "name": "lint_python",
            "description": "Lint Python code or files using multiple linters (Flake8, Pylint, mypy, and Bandit).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "The Python code snippet, file path, or directory to lint"
                    },
                    "is_file": {
                        "type": "boolean",
                        "description": "Whether the target is a file/directory path (true) or a code snippet (false)"
                    }
                },
                "required": ["target", "is_file"]
            }
        },
        {
            "name": "execute_command",
            "description": "Execute a shell command in the project root directory.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute"
                    }
                },
                "required": ["command"]
            }
        },
        {
            "name": "add_summary_note",
            "description": "Add a summary note for the current session.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "The category of the summary (e.g., 'session', 'conversation')"
                    },
                    "content": {
                        "type": "string",
                        "description": "The content of the summary"
                    }
                },
                "required": ["category", "content"]
            }
        },
        {
                "name": "tavily_search",
                "description": "Perform a web search using Tavily API to get up-to-date information or additional context. Use this when you need current information or feel a search could provide a better answer.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query"
                        }
                    },
                    "required": ["query"]
                }
        },
        {
                "name": "perplexity_search",
                "description": "Perform a web search using Perplexity API to get up-to-date information or additional context.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query"
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "The maximum number of results to return (default: 5)"
                        }
                    },
                    "required": ["query"]
                }
            },
        # {
        #     "name": "tavily_search",
        #     "description": "Perform a web search using Tavily API with advanced context and metadata.",
        #     "input_schema": {
        #         "type": "object",
        #         "properties": {
        #             "query": {
        #                 "type": "string",
        #                 "description": "The search query"
        #             },
        #             "max_results": {
        #                 "type": "integer",
        #                 "description": "The maximum number of results to return (default: 5)"
        #             },
        #             "search_depth": {
        #                 "type": "string",
        #                 "description": "The search depth: 'basic' or 'advanced' (default: 'basic')"
        #             }
        #         },
        #         "required": ["query"]
        #     }
        # },
        ]

    def get_tools(self):
        return self.tools

    def execute_tool(self, tool_name: str, tool_input: dict) -> Union[str, dict]:
        tool_map = {
            # "create_folder": lambda: create_folder(os.path.join(WORKSPACE_PATH, tool_input["path"])),
            # "create_file": lambda: create_file(os.path.join(WORKSPACE_PATH, tool_input["path"]), tool_input.get("content", "")),
            # "write_to_file": lambda: write_to_file(os.path.join(WORKSPACE_PATH, tool_input["path"]), tool_input["content"]),
            # "read_file": lambda: read_file(os.path.join(WORKSPACE_PATH, tool_input["path"])),
            # "list_files": lambda: list_files(os.path.join(WORKSPACE_PATH, tool_input.get("path", "."))),
            "add_declarative_note": lambda: self.add_declarative_note(tool_input["category"], tool_input["content"]),
            "grep_search": lambda: self.perform_grep_search(
                tool_input["pattern"],
                tool_input.get("k", 5),
                tool_input.get("case_sensitive", False),
                tool_input.get("search_files", True)
            ),
            "memory_search": lambda: self.perform_memory_search(tool_input["query"], tool_input.get("k", 5)),
            "duckduckgo_search": lambda: self.duckduckgo_search(
                tool_input["query"],
                tool_input.get("max_results", 5)
            ),
            "code_execution": lambda: self.execute_code(tool_input["code"]),
            "get_file_map": lambda: self.get_file_map(tool_input.get("directory", "")),
            # "find_file": lambda: find_file(tool_input["filename"], tool_input.get("search_path", ".")),
            "lint_python": lambda: lint_python(tool_input["target"], tool_input["is_file"]),
            "execute_command": lambda: self.execute_command(tool_input["command"]),
            "add_summary_note": lambda: self.add_summary_note(tool_input["category"], tool_input["content"]),
            "tavily_search": lambda: self.tavily_search(tool_input["query"]),
            "perplexity_search": lambda: self.perplexity_provider.format_results(
                self.perplexity_provider.search(tool_input["query"], tool_input.get("max_results", 5))
            )
            # "tavily_search": lambda: self.tavily_search(
            #     tool_input["query"],
            #     tool_input.get("max_results", 5),
            #     tool_input.get("search_depth", "advanced")
            # ),
        }
        
        logging.info(f"Executing tool: {tool_name} with input: {tool_input}")
        if tool_name not in tool_map:
            error_message = f"Unknown tool: {tool_name}"
            logging.error(error_message)
            self.log_error(Exception(error_message), f"Attempted to use unknown tool: {tool_name}")
            return {"error": error_message}

        try:
            result = tool_map[tool_name]()
            if result is None or (isinstance(result, list) and len(result) == 0):
                result = {"result": "No results found or empty directory."}
            self.add_message_to_search({"role": "assistant", "content": f"Tool use: {tool_name}"})
            self.add_message_to_search({"role": "user", "content": f"Tool result: {result}"})
            logging.info(f"Tool {tool_name} executed successfully with result: {result}")
            # if tool_name == "tavily_search":
            #     formatted_results = "Tavily Search Results:\n\n"
            #     for i, result in enumerate(result, 1):
            #         if "error" in result:
            #             formatted_results += f"{i}. Error: {result['error']}\n\n"
            #         else:
            #             formatted_results += (
            #                 f"{i}. {result['title']}\n"
            #                 f"   URL: {result['url']}\n"
            #                 f"   Content: {result['content'][:200]}...\n"
            #                 f"   Score: {result['score']}\n"
            #                 f"   Published Date: {result['published_date']}\n"
            #                 f"   Source: {result['source']}\n\n"
            #             )
            #     result = formatted_results.strip()
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
        patterns = query.split('|')  # Allow multiple patterns separated by |
        logging.info(f"Performing grep search with patterns: {patterns}")
        results = self.grep_search.search(patterns, k, case_sensitive, search_files)
        logging.info(f"Grep search returned {len(results)} results")
        formatted_results = []
        for result in results:
            if result['type'] == 'file':
                formatted_results.append({
                    "type": "text",
                    "text": f"File: {result['path']}\nContent: {result['content']}\nMatch: {result['match']}"
                })
            else:
                formatted_results.append({
                    "type": "text",
                    "text": f"Message content: {result['content']}\nMatch: {result['match']}"
                })
        logging.info(f"Formatted {len(formatted_results)} results for output")
        return formatted_results

    def perform_memory_search(self, query: str, k: int = 5) -> str:
        try:
            logging.info(f"Performing memory search with query: {query}")
            results = self.memory_search.combined_search(query, k)
            logging.info(f"Memory search returned {len(results)} results")
            formatted_results = []
            for result in results:
                formatted_results.append({
                    "type": "text",
                    "text": f"Timestamp: {result.get('timestamp', 'N/A')}\nType: {result.get('type', 'N/A')}\nContent: {result.get('content', 'N/A')}"
                })
            logging.info(f"Formatted {len(formatted_results)} results for output")
            return json.dumps(formatted_results, indent=2)
        except Exception as e:
            error_message = f"Error performing memory search: {str(e)}"
            self.log_error(e, error_message)
            logging.error(error_message)
            return error_message

    def add_message_to_search(self, message):
        self.grep_search.add_message(message)

    # def encode_image(self, image_path):
    #     return encode_image_to_base64(image_path)

    def duckduckgo_search(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        try:
            results = ddg_search(query, max_results)
            return results
        except Exception as e:
            error_message = f"Error performing DuckDuckGo search: {str(e)}"
            logging.error(error_message)
            return [{"error": error_message}]

    def execute_code(self, code: str) -> str:
        return self.notebook_executor.execute_code(code)

    # def execute_code(self, code: str) -> str:
    #     try:
    #         # Create a StringIO object to capture print output
    #         output_buffer = io.StringIO()
    #         sys.stdout = output_buffer

    #         # Execute the code
    #         exec_globals = {}
    #         exec(code, exec_globals)

    #         # Restore the original stdout
    #         sys.stdout = sys.__stdout__

    #         # Get the captured output
    #         output = output_buffer.getvalue()

    #         # If there's no output, check for the last expression result
    #         if not output.strip():
    #             last_expression = code.strip().split('\n')[-1]
    #             if not last_expression.startswith(('def ', 'class ', 'import ', 'from ')):
    #                 output = str(eval(last_expression, exec_globals))

    #         return output if output.strip() else "Code executed successfully, but produced no output."
    #     except Exception as e:
    #         return f"Error executing code: {str(e)}"

    # For now you can only cd with just the folder names, not the full path. 
    # I want to do some security measures before allowing full path execution. 

    def execute_command(self, command: str) -> str:
        try:
            # Determine the OS
            import platform
            os_type = platform.system().lower()

            # Adjust command based on OS
            if os_type == 'windows':
                shell = True
                command = f'cmd /c {command}'
            else:  # Unix-like systems (Linux, macOS)
                shell = False
                command = ['bash', '-c', command]

            result = subprocess.run(command, shell=shell, capture_output=True, text=True, cwd=self.project_root)
            
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

    # def archive_summary_notes(self):
    #     self.summary_notes_tool.save_summaries()

    def tavily_search(self, query: str, max_results: int = 5) -> str:
        try:
            response = self.tavily_client.search(query=query, max_results=max_results)
            formatted_results = "Tavily Search Results:\n\n"
            for i, result in enumerate(response.get("results", []), 1):
                formatted_results += (
                    f"{i}. {result.get('title', 'No title')}\n"
                    f"   URL: {result.get('url', 'No URL')}\n"
                    f"   Snippet: {result.get('snippet', 'No snippet')[:200]}...\n\n"
                )
            return formatted_results.strip()
        except Exception as e:
            return f"Error performing Tavily search: {str(e)}"      

    # def tavily_search(self, query: str, max_results: int = 5, search_depth: str = "advanced") -> str:
    #     try:
    #         response = self.tavily_search.search(query, max_results, search_depth)
    #         if "error" in response:
    #             return response["error"]
            
    #         formatted_results = "Tavily Search Results:\n\n"
    #         for i, result in enumerate(response.get("results", []), 1):
    #             formatted_results += (
    #                 f"{i}. {result.get('title', 'No title')}\n"
    #                 f"   URL: {result.get('url', 'No URL')}\n"
    #                 f"   Content: {result.get('content', 'No content')[:200]}...\n"
    #                 f"   Score: {result.get('score', 'N/A')}\n"
    #                 f"   Published Date: {result.get('published_date', 'N/A')}\n"
    #                 f"   Source: {result.get('source', 'N/A')}\n\n"
    #             )
    #         return formatted_results.strip()
    #     except Exception as e:
    #         return f"Error performing Tavily search: {str(e)}"
    
