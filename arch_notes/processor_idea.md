*Hmm, managing multiple processes through a CLI... That's an interesting challenge. We'll need to think about process management, inter-process communication, and maintaining state across different CLI sessions. Let's break this down.*

To handle multiple processes through a CLI, especially for scenarios like starting a Python server and shutting it down later, we can enhance our system in several ways:

1. Process Management:
   We can create a ProcessManager class that keeps track of running processes, their PIDs, and statuses.

2. Background Process Execution:
   Modify the execute_command function to allow for background process execution.

3. Process Control Commands:
   Implement new CLI commands for starting, stopping, and checking the status of processes.

4. Persistent Process State:
   Store process information in a file so it can be retrieved across different CLI sessions.

5. Enhanced NotebookExecutor:
   Extend the NotebookExecutor to handle long-running processes and provide an interface for interacting with them.

Here's a high-level implementation of these improvements:

1. Process Management:

```python
import psutil
import json
from typing import Dict, Any

class ProcessManager:
    def __init__(self, state_file: str = 'process_state.json'):
        self.state_file = state_file
        self.processes: Dict[str, Dict[str, Any]] = self.load_state()

    def load_state(self) -> Dict[str, Dict[str, Any]]:
        try:
            with open(self.state_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def save_state(self):
        with open(self.state_file, 'w') as f:
            json.dump(self.processes, f)

    def start_process(self, name: str, command: str):
        process = psutil.Popen(command.split(), start_new_session=True)
        self.processes[name] = {
            'pid': process.pid,
            'command': command,
            'status': 'running'
        }
        self.save_state()

    def stop_process(self, name: str):
        if name in self.processes:
            pid = self.processes[name]['pid']
            try:
                process = psutil.Process(pid)
                process.terminate()
                process.wait(timeout=10)
                self.processes[name]['status'] = 'stopped'
            except psutil.NoSuchProcess:
                pass
            self.save_state()

    def get_process_status(self, name: str) -> str:
        if name in self.processes:
            pid = self.processes[name]['pid']
            try:
                process = psutil.Process(pid)
                return 'running' if process.is_running() else 'stopped'
            except psutil.NoSuchProcess:
                return 'stopped'
        return 'not found'

    def list_processes(self) -> Dict[str, Dict[str, Any]]:
        return self.processes
```

2. Modify ToolManager to include ProcessManager:


```32:33:penguin/tools/tool_manager.py
class ToolManager:
    def __init__(self, log_error_func: Callable):
```


Add the following to the ToolManager class:

```python
from .process_manager import ProcessManager

class ToolManager:
    def __init__(self, log_error_func: Callable):
        # ... existing initialization ...
        self.process_manager = ProcessManager()

    def start_background_process(self, name: str, command: str) -> str:
        self.process_manager.start_process(name, command)
        return f"Process '{name}' started with command: {command}"

    def stop_background_process(self, name: str) -> str:
        self.process_manager.stop_process(name)
        return f"Process '{name}' stopped"

    def get_process_status(self, name: str) -> str:
        return self.process_manager.get_process_status(name)

    def list_processes(self) -> str:
        processes = self.process_manager.list_processes()
        return json.dumps(processes, indent=2)
```

3. Update ActionExecutor to include new process management actions:


```81:128:penguin/utils/parser.py
class ActionExecutor:
    def __init__(self, tool_manager: ToolManager, task_manager: TaskManager):
        self.tool_manager = tool_manager
        self.task_manager = task_manager
    def execute_action(self, action: CodeActAction) -> str:
        action_map = {
            # ActionType.READ: lambda params: self.tool_manager.execute_tool("read_file", {"path": params}),
            # ActionType.WRITE: self._write_file,
            ActionType.EXECUTE: self._execute_code,
            ActionType.SEARCH: lambda params: self.tool_manager.execute_tool("grep_search", {"pattern": params}),
            # ActionType.CREATE_FILE: self._create_file,
            # ActionType.CREATE_FOLDER: lambda params: self.tool_manager.execute_tool("create_folder", {"path": params}),
            # ActionType.LIST_FILES: lambda params: self.tool_manager.execute_tool("list_files", {"directory": params}),
            # ActionType.LIST_FOLDERS: lambda params: self.tool_manager.execute_tool("list_files", {"directory": params}),
            # ActionType.GET_FILE_MAP: lambda params: self.tool_manager.execute_tool("get_file_map", {"directory": params}),
            # ActionType.LINT: self._lint_python,
            ActionType.MEMORY_SEARCH: self._memory_search,
            ActionType.ADD_DECLARATIVE_NOTE: self._add_declarative_note,
            ActionType.TASK_CREATE: self._execute_task_create,
            ActionType.TASK_UPDATE: self._execute_task_update,
            ActionType.TASK_COMPLETE: self._execute_task_complete,
            ActionType.TASK_LIST: lambda params: list_tasks(self.task_manager)
            ActionType.PROJECT_CREATE: self._execute_project_create,
            ActionType.PROJECT_UPDATE: lambda params: update_task(self.task_manager, *params.split(':', 1)),
            ActionType.PROJECT_COMPLETE: self._execute_project_complete,
            ActionType.PROJECT_LIST: lambda params: list_tasks(self.task_manager),
            ActionType.SUBTASK_ADD: self._execute_subtask_add,
            ActionType.TASK_DETAILS: lambda params: get_task_details(self.task_manager, params),
            ActionType.PROJECT_DETAILS: lambda params: self.task_manager.get_project_details(params),
            # ActionType.WORKFLOW_ANALYZE: lambda params: self.task_manager.analyze_workflow(),
            ActionType.ADD_SUMMARY_NOTE: self._add_summary_note,
            ActionType.DUCKDUCKGO_SEARCH: self._duckduckgo_search,
            ActionType.TAVILY_SEARCH: self._tavily_search,
            ActionType.PERPLEXITY_SEARCH: self._perplexity_search,
        }
        
        try:
            if action.action_type not in action_map:
                return f"Unknown action type: {action.action_type.value}"
            
            result = action_map[action.action_type](action.params)
            logger.info(f"Action {action.action_type.value} executed successfully")
            return result
        except Exception as e:
            error_message = f"Error executing action {action.action_type.value}: {str(e)}"
            logger.error(error_message)
            return error_message
```


Add the following to the ActionExecutor class:

```python
class ActionType(Enum):
    # ... existing action types ...
    START_PROCESS = "start_process"
    STOP_PROCESS = "stop_process"
    GET_PROCESS_STATUS = "get_process_status"
    LIST_PROCESSES = "list_processes"

class ActionExecutor:
    def execute_action(self, action: CodeActAction) -> str:
        action_map = {
            # ... existing actions ...
            ActionType.START_PROCESS: self._start_process,
            ActionType.STOP_PROCESS: self._stop_process,
            ActionType.GET_PROCESS_STATUS: self._get_process_status,
            ActionType.LIST_PROCESSES: lambda params: self.tool_manager.list_processes(),
        }
        # ... rest of the method ...

    def _start_process(self, params: str) -> str:
        name, command = params.split(':', 1)
        return self.tool_manager.start_background_process(name.strip(), command.strip())

    def _stop_process(self, params: str) -> str:
        return self.tool_manager.stop_background_process(params.strip())

    def _get_process_status(self, params: str) -> str:
        return self.tool_manager.get_process_status(params.strip())
```

4. Enhance NotebookExecutor to handle long-running processes:


```7:45:penguin/utils/notebook.py
class NotebookExecutor:
    def __init__(self):
        self.shell = InteractiveShell.instance()
        os.chdir(WORKSPACE_PATH)  # Set the working directory to the workspace

    def execute_code(self, code: str) -> str:
        try:
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
                return "\n".join(combined_output) if combined_output else "Code executed successfully"
            else:
                error_msg = result.error_in_exec or error_output or "Unknown error occurred"
                return f"Error: {error_msg}"
        except Exception as e:
            return f"Error executing code: {str(e)}"
```


Modify the NotebookExecutor class:

```python
class NotebookExecutor:
    def __init__(self, tool_manager):
        self.shell = InteractiveShell.instance()
        self.tool_manager = tool_manager
        os.chdir(WORKSPACE_PATH)

    def execute_code(self, code: str) -> str:
        # ... existing code ...

    def start_background_process(self, name: str, command: str) -> str:
        return self.tool_manager.start_background_process(name, command)

    def stop_background_process(self, name: str) -> str:
        return self.tool_manager.stop_background_process(name)

    def get_process_status(self, name: str) -> str:
        return self.tool_manager.get_process_status(name)

    def list_processes(self) -> str:
        return self.tool_manager.list_processes()
```

These improvements allow for managing multiple processes through the CLI. Users can now start background processes (like a Python server), stop them later, check their status, and list all running processes. The process state is persisted, so it can be retrieved across different CLI sessions.

To use these new features, you would add new actions in the system prompt or user interface:

```
<start_process>process_name: command to run</start_process>
<stop_process>process_name</stop_process>
<get_process_status>process_name</get_process_status>
<list_processes></list_processes>
```

This system provides a robust way to manage multiple processes, including long-running ones like servers, through the CLI interface of your AI assistant.