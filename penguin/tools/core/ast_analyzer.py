"""
AST Analyzer for Python Code

Provides a class to perform a deep analysis of Python source code using
the `ast` module. It extracts detailed information about classes, functions,
imports, and complexity.
"""

import ast
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ASTAnalyzer:
    """
    Analyzes Python source code to extract structured information.
    """

    def analyze_file(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Performs a comprehensive AST analysis of a Python file.

        Args:
            file_path: The path to the Python file.

        Returns:
            A dictionary containing the analysis results, or None on failure.
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content, filename=file_path)
            
            return {
                'functions': self._extract_functions(tree),
                'classes': self._extract_classes(tree),
                'imports': self._extract_imports(tree),
                'complexity': self._calculate_complexity(tree),
            }
        except (SyntaxError, FileNotFoundError) as e:
            logger.error(f"Failed to analyze AST for {file_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"An unexpected error occurred during AST analysis of {file_path}: {e}")
            return None

    def _extract_functions(self, tree: ast.AST) -> List[Dict[str, Any]]:
        """Extracts function definitions, including their arguments and docstrings."""
        functions = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append({
                    'name': node.name,
                    'line_start': node.lineno,
                    'line_end': node.end_lineno,
                    'args': [arg.arg for arg in node.args.args],
                    'docstring': ast.get_docstring(node) or "",
                    'is_async': isinstance(node, ast.AsyncFunctionDef),
                    'decorators': [d.id for d in node.decorator_list if isinstance(d, ast.Name)],
                })
        return functions

    def _extract_classes(self, tree: ast.AST) -> List[Dict[str, Any]]:
        """Extracts class definitions, including their methods and base classes."""
        classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = [
                    n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                classes.append({
                    'name': node.name,
                    'line_start': node.lineno,
                    'line_end': node.end_lineno,
                    'methods': methods,
                    'base_classes': [base.id for base in node.bases if isinstance(base, ast.Name)],
                    'docstring': ast.get_docstring(node) or "",
                })
        return classes

    def _extract_imports(self, tree: ast.AST) -> List[str]:
        """Extracts all imported modules."""
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module)
        return sorted(list(imports))

    def _calculate_complexity(self, tree: ast.AST) -> int:
        """
        Calculates a simple cyclomatic complexity score.
        Counts branching points: if, for, while, except, with, and, or.
        """
        complexity = 0
        for node in ast.walk(tree):
            if isinstance(
                node,
                (
                    ast.If,
                    ast.For,
                    ast.While,
                    ast.AsyncFor,
                    ast.AsyncWith,
                    ast.With,
                    ast.ExceptHandler,
                    ast.And,
                    ast.Or,
                ),
            ):
                complexity += 1
        return complexity 