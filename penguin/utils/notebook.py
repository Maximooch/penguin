import io
import os
import sys

from IPython.core.interactiveshell import InteractiveShell # type: ignore

from penguin.utils.process_manager import ProcessManager
from penguin.utils import FileMap


class NotebookExecutor:
    def __init__(self):
        from penguin.config import WORKSPACE_PATH
        
        self.shell = InteractiveShell.instance()
        self.original_dir = os.getcwd()  # Track original directory
        os.chdir(WORKSPACE_PATH)  # Set the working directory to the workspace
        self.process_manager = ProcessManager()
        self.current_process = None
        self.file_map = FileMap(WORKSPACE_PATH)
        self.active_directory = WORKSPACE_PATH  # Explicit workspace tracking

    def execute_code(self, code: str) -> str:
        try:
            # Store pre-execution state
            pre_dir = os.getcwd()
            os.chdir(self.active_directory)  # Ensure workspace context
            
            pre_state = self.file_map.get_file_map()
            
            # Capture both stdout and stderr
            out = io.StringIO()
            err = io.StringIO()
            sys.stdout = out
            sys.stderr = err

            # Execute the code
            result = self.shell.run_cell(code)

            # Restore stdout and stderr
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__
            
            # Return to original directory after execution
            os.chdir(pre_dir)

            # Get the captured outputs
            output = out.getvalue()
            error_output = err.getvalue()

            # Combine outputs based on what's available
            if result.success:
                combined_output = []
                if output.strip():
                    combined_output.append(output.strip())
                if result.result is not None:
                    combined_output.append(str(result.result))
                if error_output.strip():  # Include stderr even on success
                    combined_output.append(f"Warnings:\n{error_output.strip()}")
                return (
                    "\n".join(combined_output)
                    if combined_output
                    else "Code executed successfully"
                )
            else:
                # Attempt to capture richer error information
                error_parts = []
                if result.error_in_exec:
                    error_parts.append(str(result.error_in_exec))
                if hasattr(result, "error_before_exec") and result.error_before_exec:
                    error_parts.append(str(result.error_before_exec))
                if error_output.strip():
                    error_parts.append(error_output.strip())

                error_msg = "\n".join(error_parts) if error_parts else "Unknown error occurred"
                return f"Error: {error_msg}"
        except Exception as e:
            return f"Error executing code: {str(e)}"

    def execute_shell(self, command: str) -> str:
        import platform
        import subprocess

        try:
            # Determine OS and adjust command
            if platform.system().lower() == "windows":
                shell = True
                command = f"cmd /c {command}"
            else:  # Unix-like systems
                shell = False
                command = ["bash", "-c", command]

            # Execute command in explicit workspace directory
            result = subprocess.run(
                command, 
                shell=shell, 
                capture_output=True, 
                text=True, 
                cwd=self.active_directory  # Force workspace context
            )

            # Combine stdout and stderr if present
            output = []
            if result.stdout:
                output.append(result.stdout.strip())
            if result.stderr:
                output.append(f"Stderr:\n{result.stderr.strip()}")

            return "\n".join(output) if output else "Command executed successfully"
        except Exception as e:
            return f"Error executing shell command: {str(e)}"

    async def enter_process(self, name: str) -> str:
        result = await self.process_manager.enter_process(name)
        if result:
            self.current_process = name
            return f"Entered process '{name}'"
        return f"Failed to enter process '{name}'"

    async def send_command(self, command: str) -> str:
        if not self.current_process:
            return "Not currently in any process"
        return await self.process_manager.send_command(self.current_process, command)

    async def exit_process(self) -> str:
        if not self.current_process:
            return "Not currently in any process"
        result = await self.process_manager.exit_process(self.current_process)
        self.current_process = None
        return result
