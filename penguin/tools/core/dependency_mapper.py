"""
Code Dependency Mapper

Analyzes a Python workspace to map the dependencies between modules,
detecting local vs. external imports.
"""

import ast
import logging
from pathlib import Path
from typing import Any, Dict, List, Set

logger = logging.getLogger(__name__)


class DependencyMapper:
    """
    Scans a workspace to build a dependency graph of Python modules.
    """

    def __init__(self, workspace_path: str):
        self.workspace_path = Path(workspace_path).resolve()
        self.dependency_graph: Dict[str, Dict[str, List[str]]] = {}
        self.local_modules: Set[str] = set()

    async def analyze_workspace(self) -> Dict[str, Any]:
        """
        Analyzes the entire workspace to build and return the dependency graph.

        Returns:
            A dictionary containing the dependency graph and other metrics.
        """
        python_files = list(self.workspace_path.rglob('*.py'))
        self._discover_local_modules(python_files)

        for file_path in python_files:
            await self._analyze_file(file_path)

        return {
            'dependency_graph': self.dependency_graph,
            # Further analysis like circular dependency detection could be added here.
        }

    def _discover_local_modules(self, python_files: List[Path]):
        """Create a set of all local module paths for quick lookup."""
        for file_path in python_files:
            relative_path = file_path.relative_to(self.workspace_path)
            module_path = str(relative_path.with_suffix('')).replace('/', '.')
            if module_path.endswith('.__init__'):
                module_path = module_path.removesuffix('.__init__')
            self.local_modules.add(module_path)

    async def _analyze_file(self, file_path: Path):
        """Analyzes a single file for its dependencies."""
        relative_path_str = str(file_path.relative_to(self.workspace_path))
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            tree = ast.parse(content, filename=str(file_path))
            
            imports = self._extract_imports(tree)
            
            local_imports = [imp for imp in imports if self._is_local_import(imp)]
            external_imports = [imp for imp in imports if not self._is_local_import(imp)]

            self.dependency_graph[relative_path_str] = {
                'imports': sorted(list(imports)),
                'local': sorted(local_imports),
                'external': sorted(external_imports),
            }

        except (SyntaxError, FileNotFoundError) as e:
            logger.warning(f"Could not analyze dependencies for {relative_path_str}: {e}")
            self.dependency_graph[relative_path_str] = {
                'imports': [],
                'local': [],
                'external': [],
                'error': str(e),
            }
    
    def _extract_imports(self, tree: ast.AST) -> Set[str]:
        """Extracts all unique module names from import statements."""
        imports: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    # Take the top-level module (e.g., 'os' from 'os.path')
                    imports.add(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    # Handle relative imports (e.g., from . import foo)
                    if node.level > 0:
                        # For simplicity, we can resolve this based on file path later
                        # or just note the relative nature. Here we'll take the module name.
                        pass
                    imports.add(node.module.split('.')[0])
        return imports
    
    def _is_local_import(self, module_name: str) -> bool:
        """Check if an imported module is part of the local workspace."""
        return module_name in self.local_modules 