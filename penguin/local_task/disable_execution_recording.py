# This is claude generated code
# Honestly I don't know why this is needed, but I'll take care of it later.

"""
Disable execution recording in the ProjectManager.

Run this script to disable execution recording if you're experiencing freezing issues.
"""

from penguin.local_task.manager import ProjectManager

if __name__ == "__main__":
    # Disable execution recording globally
    ProjectManager.disable_execution_recording()
    print("Execution recording has been disabled globally.")
    print("This should prevent freezing issues related to task recording.")
    print("To re-enable, use: ProjectManager.enable_execution_recording()") 