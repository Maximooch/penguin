from IPython.core.interactiveshell import InteractiveShell
import io
import sys
import os
from config import WORKSPACE_PATH

class NotebookExecutor:
    def __init__(self):
        self.shell = InteractiveShell.instance()
        os.chdir(WORKSPACE_PATH)  # Set the working directory to the workspace

    def execute_code(self, code: str) -> str:
        try:
            # Capture output
            out = io.StringIO()
            sys.stdout = out

            # Execute the code
            result = self.shell.run_cell(code)

            # Restore stdout
            sys.stdout = sys.__stdout__

            # Get the captured output
            output = out.getvalue()

            if result.success:
                return output if output.strip() else str(result.result)
            else:
                return f"Error: {result.error_in_exec}"
        except Exception as e:
            return f"Error executing code: {str(e)}"
