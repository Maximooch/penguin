import os
import subprocess
from typing import Any, Dict, List


class Session:
    def __init__(self):
        self.current_dir = os.getcwd()
        self.dir_stack = []
        self.env_variables: Dict[str, Any] = {}

    def cd(self, path: str) -> bool:
        new_path = os.path.join(self.current_dir, path)
        if os.path.isdir(new_path):
            self.current_dir = os.path.abspath(new_path)
            return True
        return False

    def pushd(self, path: str) -> bool:
        if self.cd(path):
            self.dir_stack.append(self.current_dir)
            return True
        return False

    def popd(self) -> bool:
        if self.dir_stack:
            self.current_dir = self.dir_stack.pop()
            return True
        return False

    def set_env(self, key: str, value: Any) -> None:
        self.env_variables[key] = value

    def get_env(self, key: str) -> Any:
        return self.env_variables.get(key)

    def execute_in_dir(self, command: str) -> str:
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

    def temp_cd(self, path: str):
        class TempCD:
            def __init__(self, session, path):
                self.session = session
                self.path = path
                self.original_dir = session.current_dir

            def __enter__(self):
                self.session.cd(self.path)

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.session.current_dir = self.original_dir

        return TempCD(self, path)


class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, Session] = {}

    def create_session(self, session_id: str) -> Session:
        if session_id not in self.sessions:
            self.sessions[session_id] = Session()
        return self.sessions[session_id]

    def get_session(self, session_id: str) -> Session:
        return self.sessions.get(session_id)

    def delete_session(self, session_id: str) -> None:
        if session_id in self.sessions:
            del self.sessions[session_id]

    def execute_in_session(self, session_id: str, command: str) -> str:
        session = self.get_session(session_id)
        if session:
            return session.execute_in_dir(command)
        return f"Session not found: {session_id}"
