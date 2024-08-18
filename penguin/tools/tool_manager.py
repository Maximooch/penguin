import os
import logging
import time 
import random 
import requests # type: ignore
from requests.exceptions import RequestException # type: ignore

from .support import create_folder, create_file, write_to_file, read_file, list_files, encode_image_to_base64
# from tavily import TavilyClient

from bs4 import BeautifulSoup # type: ignore
from duckduckgo_search import DDGS # type: ignore
from .declarative_memory_tool import DeclarativeMemoryTool
# from .bm25_search import BM25Search
from .grep_search import GrepSearch
# from .elastic_search_tool import ElasticSearch
# from .sklearn_search_tool import SklearnSearch

class ToolManager:
    def __init__(self, tavily_api_key):
        # self.tavily_client = TavilyClient(api_key=tavily_api_key)
        self.declarative_memory_tool = DeclarativeMemoryTool()
        # self.bm25_searcher = BM25Search(root_dir=os.path.join(os.getcwd(), "logs"))
        self.grep_search = GrepSearch(root_dir=os.path.join(os.getcwd(), "logs"))
        # self.elastic_search = ElasticSearch(root_dir=os.path.join(os.getcwd(), "logs"))
        # self.sklearn_search = SklearnSearch(root_dir=os.path.join(os.getcwd(), "logs"))
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
                "name": "duckduckgo_search",
                "description": "Perform a web search using DuckDuckGo to get up-to-date information or additional context. Use this when you need current information or feel a search could provide a better answer.",
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

        try:
            result = tool_map.get(tool_name, lambda: f"Unknown tool: {tool_name}")()
            self.add_message_to_search({"role": "assistant", "content": f"Tool use: {tool_name}"})
            self.add_message_to_search({"role": "user", "content": f"Tool result: {result}"})
            return result
        except Exception as e:
            error_message = f"Error executing tool '{tool_name}': {str(e)}"
            self.add_message_to_search({"role": "system", "content": error_message})
            logging.error(f"Tool execution error: {error_message}", exc_info=True)
            return error_message

    def duckduckgo_search(self, query, max_results=5):
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
            
            formatted_results = []
            for result in results:
                formatted_results.append({
                    "title": result['title'],
                    "content": result['body'],
                    "url": result['href']
                })
            
            return formatted_results
        except Exception as e:
            logging.error(f"Error performing DuckDuckGo search: {str(e)}")
            return [{
                "title": "Search Error",
                "content": f"An error occurred: {str(e)}",
                "url": ""
            }]

    # def tavily_search(self, query):
    #     try:
    #         response = self.tavily_client.qna_search(query=query, search_depth="advanced")
    #         return response
    #     except Exception as e:
    #         return f"Error performing search: {str(e)}"

    # def add_declarative_note(self, category, content):
    #     return self.declarative_memory_tool.add_note(category, content)

    def perform_sklearn_search(self, query, k=5, case_sensitive=False, search_files=True):
        logging.info(f"Performing sklearn search with query: {query}")
        results = self.sklearn_search.search(query, k, case_sensitive, search_files)
        logging.info(f"Sklearn search returned {len(results)} results")
        formatted_results = []
        for result in results:
            if result['type'] == 'file':
                formatted_results.append({
                    "type": "text",
                    "text": f"File: {result.get('path', 'Unknown')}\nContent: {result['content'][:500]}...\nRelevance Score: {result['relevance_score']:.2f}, Cosine Similarity: {result['cosine_similarity']:.2f}, Matching terms: {result['matching_terms']}, Fuzzy Ratio: {result['fuzzy_ratio']:.2f}"
                })
            else:
                formatted_results.append({
                    "type": "text",
                    "text": f"Message content: {result['content']}\nRelevance Score: {result['relevance_score']:.2f}, Cosine Similarity: {result['cosine_similarity']:.2f}, Matching terms: {result['matching_terms']}, Fuzzy Ratio: {result['fuzzy_ratio']:.2f}"
                })
        logging.info(f"Formatted {len(formatted_results)} results for output")
        return formatted_results

    # def perform_bm25_search(self, query, k=5):
    #     results = self.bm25_searcher.search(query, k)
    #     formatted_results = []
    #     for result in results:
    #         if result.get('role') == 'file':
    #             formatted_results.append({
    #                 "type": "text",
    #                 "text": f"File: {result['content']}"
    #             })
    #         else:
    #             formatted_results.append({
    #                 "type": "text",
    #                 "text": f"Role: {result['role']}, Content: {result['content']}"
    #             })
    #     return formatted_results

    # import logging

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

    # def update_bm25_index(self):
    #     self.bm25_searcher.index_files()


    def add_message_to_search(self, message):
        # self.bm25_searcher.add_message(message)
        self.grep_search.add_message(message)
    
        # self.sklearn_search.add_message(message)

    def encode_image(self, image_path):
        return encode_image_to_base64(image_path)

    def execute_code(self, code):
        try:
            # Set the environment variable for encoding
            os.environ['PYTHONIOENCODING'] = 'utf-8'
            
            local_vars = {}
            exec(code, {}, local_vars)
            return local_vars
        except Exception as e:
            logging.error(f"Error executing code: {str(e)}")
            return {"error": str(e)}

# Example usage:
# tool_manager = ToolManager("your-tavily-api-key-here")
# result = tool_manager.execute_tool("create_folder", {"path": "test_folder"})
# print(result)
# result = tool_manager.execute_tool("duckduckgo_search", {"keywords": "Latest news about AI"})
# print(result)