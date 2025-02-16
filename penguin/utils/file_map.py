import fnmatch
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple


class FileNode:
    def __init__(self, name: str, is_dir: bool):
        self.name = name
        self.is_dir = is_dir
        self.children: Dict[str, FileNode] = {}
        self.last_modified: float = 0
        self.size: int = 0


class FileMap:
    def __init__(self, root_path: str):
        self.root_path = Path(root_path)
        self.root: FileNode = FileNode(self.root_path.name, True)
        self.ignore_patterns: List[str] = [
            "*/__pycache__/*",
            "*/penguin_venv/*",
            "*/logs/*",
            "*.pyc",
            "*.pyo",
            "*/node_modules/*",
            "*.git/*",
            "*.vscode/*",
            "*.idea/*",
            "*.log",
            "*.lock",
        ]
        self.update_file_map()

    def update_file_map(self):
        self._update_directory(self.root_path, self.root)

    def _update_directory(self, directory: Path, node: FileNode):
        for item in directory.iterdir():
            relative_path = str(item.relative_to(self.root_path))

            if self._should_ignore(relative_path):
                continue

            item_stat = item.stat()
            current_time = item_stat.st_mtime

            if (
                item.name not in node.children
                or current_time > node.children[item.name].last_modified
            ):
                if item.is_file():
                    file_node = FileNode(item.name, False)
                    file_node.size = item_stat.st_size
                    file_node.last_modified = current_time
                    node.children[item.name] = file_node
                elif item.is_dir():
                    dir_node = FileNode(item.name, True)
                    dir_node.last_modified = current_time
                    node.children[item.name] = dir_node
                    self._update_directory(item, dir_node)

    def _should_ignore(self, path: str) -> bool:
        return any(fnmatch.fnmatch(path, pattern) for pattern in self.ignore_patterns)

    def get_file_map(self) -> Dict[str, Any]:
        return self._node_to_dict(self.root)

    def _node_to_dict(self, node: FileNode) -> Dict[str, Any]:
        result = {
            "type": "directory" if node.is_dir else "file",
            "last_modified": node.last_modified,
        }
        if not node.is_dir:
            result["size"] = node.size
        if node.is_dir:
            result["children"] = {
                name: self._node_to_dict(child) for name, child in node.children.items()
            }
        return result

    def get_formatted_file_map(self, directory: str = "", max_files: int = 100) -> str:
        node = self._find_node(directory)
        formatted_output, file_count = self._format_node(
            node, directory, max_files=max_files
        )
        if file_count >= max_files:
            formatted_output.append(
                f"... (output truncated, showing {max_files} of {file_count} files)"
            )
        return "\n".join(formatted_output)

    def _find_node(self, path: str) -> FileNode:
        if not path:
            return self.root
        parts = path.split(os.sep)
        node = self.root
        for part in parts:
            if part in node.children and node.children[part].is_dir:
                node = node.children[part]
            else:
                return node
        return node

    def _format_node(
        self, node: FileNode, path: str, indent: str = "", max_files: int = 100
    ) -> Tuple[List[str], int]:
        formatted_output = []
        file_count = 0
        if node.is_dir:
            formatted_output.append(f"{indent}{path}/")
            for name, child in sorted(node.children.items()):
                child_path = os.path.join(path, name) if path else name
                child_output, child_count = self._format_node(
                    child, child_path, indent + "  ", max_files - file_count
                )
                formatted_output.extend(child_output)
                file_count += child_count
                if file_count >= max_files:
                    break
        else:
            size = node.size
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / (1024 * 1024):.1f} MB"
            formatted_output.append(f"{indent}{node.name} ({size_str})")
            file_count = 1
        return formatted_output, file_count

    def get_changes_since(self, timestamp: float) -> Dict[str, Any]:
        changes = {}
        self._get_changes_since_recursive(self.root, "", timestamp, changes)
        return changes

    def _get_changes_since_recursive(
        self, node: FileNode, path: str, timestamp: float, changes: Dict[str, Any]
    ):
        if node.last_modified > timestamp:
            changes[path] = self._node_to_dict(node)
        if node.is_dir:
            for name, child in node.children.items():
                child_path = os.path.join(path, name) if path else name
                self._get_changes_since_recursive(child, child_path, timestamp, changes)


# # Example usage
# if __name__ == "__main__":
#     file_map = FileMap(".")
#     print("Initial file map:")
#     print(file_map.get_formatted_file_map())

#     # Simulate some time passing and file changes
#     time.sleep(2)
#     Path("test_file.txt").touch()

#     print("\nUpdating incrementally:")
#     file_map.update_incrementally()
#     print(file_map.get_formatted_file_map())

#     print("\nChanges in the last 5 seconds:")
#     print(file_map.get_changes_since(time.time() - 5))
