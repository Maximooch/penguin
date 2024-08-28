import os
from pathlib import Path
from typing import Dict, Any
import time

class FileMap:
    def __init__(self, root_path: str):
        self.root_path = Path(root_path)
        self.file_map: Dict[str, Any] = {}
        self.last_update_time: Dict[str, float] = {}
        self.update_file_map()

    def update_file_map(self):
        self._update_directory(self.root_path)

    def _update_directory(self, directory: Path):
        for item in directory.iterdir():
            relative_path = str(item.relative_to(self.root_path))
            
            # Skip __pycache__, penguin_venv, and logs directories
            if any(part in ['__pycache__', 'penguin_venv', 'logs'] for part in item.parts):
                continue
            
            item_stat = item.stat()
            current_time = item_stat.st_mtime

            if relative_path not in self.last_update_time or current_time > self.last_update_time[relative_path]:
                if item.is_file():
                    self.file_map[relative_path] = {
                        "type": "file",
                        "size": item_stat.st_size,
                        "last_modified": current_time
                    }
                elif item.is_dir():
                    self.file_map[relative_path] = {
                        "type": "directory",
                        "last_modified": current_time
                    }
                    self._update_directory(item)

                self.last_update_time[relative_path] = current_time
            elif item.is_dir():
                self._update_directory(item)

    def get_file_map(self) -> Dict[str, Any]:
        return self.file_map

    def update_incrementally(self):
        self._update_directory(self.root_path)

    def get_changes_since(self, timestamp: float) -> Dict[str, Any]:
        changes = {}
        for path, info in self.file_map.items():
            if info["last_modified"] > timestamp:
                changes[path] = info
        return changes

    def get_formatted_file_map(self, directory: str = "") -> str:
        file_map = self.get_file_map()
        formatted_output = []
        
        def format_entry(path, info, indent=""):
            if info['type'] == 'directory':
                formatted_output.append(f"{indent}{path}/")
                for sub_path, sub_info in file_map.items():
                    if sub_path.startswith(path + '/') and sub_path != path:
                        format_entry(sub_path, sub_info, indent + "  ")
            else:
                size = info['size']
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size / (1024 * 1024):.1f} MB"
                formatted_output.append(f"{indent}{path.split('/')[-1]} ({size_str})")

        for path, info in sorted(file_map.items()):
            if directory:
                if path.startswith(directory):
                    format_entry(path, info)
            elif '/' not in path:
                format_entry(path, info)
        
        return "\n".join(formatted_output)

# Example usage
if __name__ == "__main__":
    file_map = FileMap(".")
    print("Initial file map:")
    print(file_map.get_formatted_file_map())

    # Simulate some time passing and file changes
    time.sleep(2)
    Path("test_file.txt").touch()

    print("\nUpdating incrementally:")
    file_map.update_incrementally()
    print(file_map.get_formatted_file_map())

    print("\nChanges in the last 5 seconds:")
    print(file_map.get_changes_since(time.time() - 5))