import os
import io
import sys
import logging
import time 
import random 
import requests # type: ignore
from requests.exceptions import RequestException # type: ignore

from .support import create_folder, create_file, write_to_file, read_file, list_files, encode_image_to_base64

from bs4 import BeautifulSoup # type: ignore
from .declarative_memory_tool import DeclarativeMemoryTool
from .grep_search import GrepSearch

class ToolManager:
    def __init__(self):
        self.declarative_memory_tool = DeclarativeMemoryTool()
        self.grep_search = GrepSearch(root_dir=os.path.join(os.getcwd(), "logs"))
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
        }
        ]

    def get_tools(self):
        return self.tools

    def execute_tool(self, tool_name, tool_input):
        tool_map = {
            "create_folder": lambda: create_folder(tool_input["path"]),
            "create_file": lambda: create_file(tool_input["path"], tool_input.get("content", "")),
            "write_to_file": lambda: write_to_file(tool_input["path"], tool_input["content"]),
            "read_file": lambda: read_file(tool_input["path"]),
            "list_files": lambda: list_files(tool_input.get("path", ".")),
            "add_declarative_note": lambda: self.add_declarative_note(tool_input["category"], tool_input["content"]),
            "grep_search": lambda: self.perform_grep_search(
                tool_input["pattern"],
                tool_input.get("k", 5),
                tool_input.get("case_sensitive", False),
                tool_input.get("search_files", True)
            ),
            "duckduckgo_search": lambda: self.duckduckgo_search(
                tool_input["query"],
                tool_input.get("max_results", 5)
            ),
            "code_execution": lambda: self.execute_code(tool_input["code"]),
        }

        logging.info(f"Executing tool: {tool_name} with input: {tool_input}")
        if tool_name not in tool_map:
            error_message = f"Unknown tool: {tool_name}"
            logging.error(error_message)
            return error_message

        try:
            result = tool_map[tool_name]()
            if result is None or (isinstance(result, list) and len(result) == 0):
                result = "No results found or empty directory."
            self.add_message_to_search({"role": "assistant", "content": f"Tool use: {tool_name}"})
            self.add_message_to_search({"role": "user", "content": f"Tool result: {result}"})
            logging.info(f"Tool {tool_name} executed successfully with result: {result}")
            return result
        except Exception as e:
            error_message = f"Error executing tool {tool_name}: {str(e)}"
            logging.error(error_message)
            return error_message

    def add_declarative_note(self, category, content):
        return self.declarative_memory_tool.add_note(category, content)

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

    def add_message_to_search(self, message):
        self.grep_search.add_message(message)

    def encode_image(self, image_path):
        return encode_image_to_base64(image_path)

    def execute_code(self, code: str) -> str:
        try:
            # Create a StringIO object to capture print output
            output_buffer = io.StringIO()
            sys.stdout = output_buffer

            # Execute the code
            exec_globals = {}
            exec(code, exec_globals)

            # Restore the original stdout
            sys.stdout = sys.__stdout__

            # Get the captured output
            output = output_buffer.getvalue()

            # If there's no output, check for the last expression result
            if not output.strip():
                last_expression = code.strip().split('\n')[-1]
                if not last_expression.startswith(('def ', 'class ', 'import ', 'from ')):
                    output = str(eval(last_expression, exec_globals))

            return output if output.strip() else "Code executed successfully, but produced no output."
        except Exception as e:
            return f"Error executing code: {str(e)}"