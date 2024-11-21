import subprocess
import asyncio
from typing import Dict

class ProcessManager:
    def __init__(self):
        self.processes: Dict[str, subprocess.Popen] = {}

    async def start_process(self, name: str, command: str) -> str:
        try:
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            self.processes[name] = process
            return f"Process '{name}' started with PID {process.pid}"
        except Exception as e:
            return f"Error starting process '{name}': {str(e)}"

    async def stop_process(self, name: str) -> str:
        if name in self.processes:
            process = self.processes[name]
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            del self.processes[name]
            return f"Process '{name}' stopped"
        return f"Process '{name}' not found"

    async def get_process_status(self, name: str) -> str:
        if name in self.processes:
            process = self.processes[name]
            if process.poll() is None:
                return f"Process '{name}' is running"
            else:
                return f"Process '{name}' has exited with return code {process.returncode}"
        return f"Process '{name}' not found"

    async def list_processes(self) -> Dict[str, str]:
        return {name: "Running" if process.poll() is None else "Exited" 
                for name, process in self.processes.items()}
