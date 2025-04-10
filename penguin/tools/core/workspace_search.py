import ast
import fnmatch
import json
import logging
import os
import time
from typing import Any, Dict, List

import chromadb
import ollama
from chromadb.config import Settings


class CodeIndexer:
    def __init__(self, persist_directory: str = "./chroma_db"):
        # Initialize ChromaDB client
        self.client = chromadb.Client(
            Settings(persist_directory=persist_directory, anonymized_telemetry=False)
        )
        self.collection = self.client.get_or_create_collection(
            "penguin_code_collection"
        )

        # Initialize Ollama client for embeddings
        self.ollama_client = ollama.Client()
        self.ignore_patterns = self.get_ignore_patterns()

    def get_ignore_patterns(self) -> List[str]:
        ignore_patterns = [
            "penguin_venv/*",
            ".venv/*",
            "__pycache__/*",
            "node_modules/*",
            "build/*",
            "dist/*",
            "*.pyc",
            "*.pyo",
            "*.pyd",
            ".git/*",
            ".vscode/*",
            ".idea/*",
            "logs/*",
            "embeddings/*",
            "example/*",
            "testing/*",
            "*.log",
            "*.sqlite",
            "*.bak",
            "*.swp",
            "*~",
        ]
        return ignore_patterns

    def should_ignore(self, path: str) -> bool:
        for pattern in self.ignore_patterns:
            if fnmatch.fnmatch(path, pattern):
                return True
        return False

    def index_directory(self, directory: str):
        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    relative_path = os.path.relpath(file_path, directory)
                    if self.should_ignore(relative_path):
                        continue
                    self.index_file(file_path, relative_path)

    def parse_ast(self, content: str) -> Dict[str, Any]:
        ast_info = {"classes": [], "functions": [], "imports": []}
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    ast_info["classes"].append(
                        {
                            "name": node.name,
                            "line": node.lineno,
                            "end_line": node.end_lineno,
                            "methods": [
                                m.name for m in node.body if isinstance(m, ast.FunctionDef)
                            ],
                        }
                    )
                elif isinstance(node, ast.FunctionDef):
                    ast_info["functions"].append(
                        {
                            "name": node.name,
                            "line": node.lineno,
                            "end_line": node.end_lineno,
                            "args": [a.arg for a in node.args.args],
                        }
                    )
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        ast_info["imports"].append(
                            {"name": alias.name, "line": node.lineno}
                        )
        except SyntaxError as e:
            # Log specific syntax errors during parsing but return empty ast_info
            # This allows indexing to proceed (potentially with embeddings) even if AST parsing fails.
            logging.warning(f"SyntaxError parsing AST: {e}. File content might not be valid Python.")
            # Return the initialized empty dict, indicating no AST info could be extracted
            return ast_info 
            
        # Return the populated ast_info if parsing was successful
        return ast_info

    def index_file(self, file_path: str, relative_path: str):
        print(f"Indexing: {relative_path}")
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            # Get embeddings from Ollama
            response = self.ollama_client.embeddings(
                model="nomic-embed-text", prompt=content
            )

            if not response or "embedding" not in response:
                print(f"Warning: No embedding returned for {relative_path}")
                return

            embedding = response["embedding"]
            if not embedding or not isinstance(embedding, list):
                print(f"Warning: Invalid embedding format for {relative_path}")
                return

            # Parse AST info
            ast_info = self.parse_ast(content)

            # Store in ChromaDB
            self.collection.add(
                embeddings=[embedding],  # Single embedding wrapped in list
                documents=[content],
                metadatas=[
                    {"file_path": relative_path, "ast_info": json.dumps(ast_info)}
                ],
                ids=[relative_path],
            )
        except Exception as e:
            print(f"Error indexing {relative_path}: {str(e)}")
            if hasattr(e, "__traceback__"):
                import traceback

                print(traceback.format_exc())

    def search_code(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        # Get query embedding from Ollama
        response = self.ollama_client.embeddings(model="nomic-embed-text", prompt=query)
        query_embedding = [response["embedding"]]

        # First try exact function name match in AST info
        exact_matches = []
        all_results = self.collection.get(
            include=["documents", "metadatas", "embeddings"]
        )

        for doc, meta in zip(all_results["documents"], all_results["metadatas"]):
            ast_info = json.loads(meta["ast_info"])

            # Check classes and their methods
            for class_info in ast_info["classes"]:
                if query in class_info["methods"]:
                    exact_matches.append(
                        {
                            "content": doc,
                            "metadata": meta,
                            "distance": 0,  # Exact match
                            "match_type": "method",
                            "class": class_info["name"],
                            "line_range": (class_info["line"], class_info["end_line"]),
                        }
                    )

            # Check standalone functions
            for func_info in ast_info["functions"]:
                if query == func_info["name"]:
                    exact_matches.append(
                        {
                            "content": doc,
                            "metadata": meta,
                            "distance": 0,  # Exact match
                            "match_type": "function",
                            "line_range": (func_info["line"], func_info["end_line"]),
                        }
                    )

        # If we found exact matches, return those
        if exact_matches:
            return exact_matches[:max_results]

        # Otherwise, fall back to semantic search
        results = self.collection.query(
            query_embeddings=query_embedding,
            n_results=max_results,
            include=["documents", "metadatas", "distances"],
        )

        combined_results = []
        for doc, meta, distance in zip(
            results["documents"][0], results["metadatas"][0], results["distances"][0]
        ):
            ast_info = json.loads(meta["ast_info"])
            relevant_ast = self.find_relevant_ast(query, ast_info)

            # Extract the relevant code section if we found matching AST nodes
            content = doc
            line_range = None
            if relevant_ast["functions"] or relevant_ast["classes"]:
                if relevant_ast["functions"]:
                    func = relevant_ast["functions"][0]
                    line_range = (func["line"], func["end_line"])
                elif relevant_ast["classes"]:
                    class_info = relevant_ast["classes"][0]
                    line_range = (class_info["line"], class_info["end_line"])

                if line_range:
                    content_lines = doc.splitlines()
                    content = "\n".join(
                        content_lines[line_range[0] - 1 : line_range[1]]
                    )

            combined_results.append(
                {
                    "content": content,
                    "metadata": meta,
                    "distance": distance,
                    "relevant_ast": relevant_ast,
                    "line_range": line_range,
                }
            )

        return combined_results

    def find_relevant_ast(self, query: str, ast_info: Dict[str, Any]) -> Dict[str, Any]:
        relevant_ast = {"classes": [], "functions": [], "imports": []}
        query_parts = query.lower().split()

        for item in ast_info["classes"]:
            if all(part in item["name"].lower() for part in query_parts):
                relevant_ast["classes"].append(item)
            else:
                for method in item["methods"]:
                    if all(part in method.lower() for part in query_parts):
                        relevant_ast["classes"].append(item)
                        break

        for item in ast_info["functions"]:
            if all(part in item["name"].lower() for part in query_parts):
                relevant_ast["functions"].append(item)
            elif any(
                all(part in arg.lower() for part in query_parts) for arg in item["args"]
            ):
                relevant_ast["functions"].append(item)

        for item in ast_info["imports"]:
            if all(part in item["name"].lower() for part in query_parts):
                relevant_ast["imports"].append(item)

        return relevant_ast

    def explore_code(self, file_path: str, line_number: int, context_lines: int = 20):
        with open(file_path, encoding="utf-8") as f:
            lines = f.readlines()

        start = max(0, line_number - context_lines - 1)
        end = min(len(lines), line_number + context_lines)
        return "".join(lines[start:end])

    def display_search_results(self, results: List[Dict[str, Any]]):
        for i, result in enumerate(results, 1):
            print(f"\n{i}. File: {result['metadata']['file_path']}")
            if "match_type" in result:
                print(f"   Exact match! Found as {result['match_type']}")
                if result["match_type"] == "method":
                    print(f"   In class: {result['class']}")
            print(f"   Lines: {result.get('line_range', 'Unknown')}")
            print(f"   Distance: {result['distance']:.4f}")
            print("   Code snippet:")
            print("   " + "\n   ".join(result["content"].split("\n")[:5]) + "...")

    def wait_for_initialization(self):
        """Wait for the indexer to complete initialization"""
        try:
            # Give the indexer some time to initialize
            initialization_timeout = 60  # seconds
            start_time = time.time()
            while not hasattr(self, "collection") or not self.collection:
                if time.time() - start_time > initialization_timeout:
                    raise TimeoutError("Workspace indexer initialization timed out")
                time.sleep(0.1)
        except Exception as e:
            logging.error(
                f"Error waiting for workspace indexer initialization: {str(e)}"
            )
            raise


if __name__ == "__main__":
    indexer = CodeIndexer()

    print("Indexing the penguin directory...")
    indexer.index_directory("../penguin")
    print("Indexing complete.")

    search_queries = [
        # "process_and_display_response"
        "automode"
    ]

    for query in search_queries:
        print(f"\nSearch results for query: '{query}'")
        search_results = indexer.search_code(query)

        if not search_results:
            print("No results found.")
        else:
            indexer.display_search_results(search_results)

    print("\nScript execution complete.")
