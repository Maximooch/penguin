import os
import subprocess
from typing import List


class FileManager:
    def __init__(self):
        self.current_dir = os.getcwd()

    def cd(self, path: str) -> bool:
        new_path = os.path.join(self.current_dir, path)
        if os.path.isdir(new_path):
            self.current_dir = os.path.abspath(new_path)
            return True
        return False

    def execute_command(self, command: str) -> str:
        original_dir = os.getcwd()
        os.chdir(self.current_dir)
        try:
            if command.startswith("cd "):
                new_dir = command[3:].strip()
                if self.cd(new_dir):
                    return f"Changed directory to {self.current_dir}"
                else:
                    return f"Failed to change directory to {new_dir}"
            elif command.strip().lower() == "pwd":
                return self.current_dir
            else:
                result = subprocess.run(
                    command, shell=True, capture_output=True, text=True
                )
                return (
                    result.stdout
                    if result.returncode == 0
                    else f"Error: {result.stderr}"
                )
        finally:
            os.chdir(original_dir)

    def get_current_dir(self) -> str:
        return self.current_dir

    def list_files(self) -> List[str]:
        return os.listdir(self.current_dir)
