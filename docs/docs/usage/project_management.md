# Project Management

Penguin v0.2.0 introduces a powerful SQLite-backed project management system that provides robust task tracking, hierarchical organization, and integration with the AI assistant workflow. This guide covers all aspects of managing projects and tasks in Penguin.

## Overview

The project management system offers:

- **SQLite-backed storage** with ACID transactions for reliability
- **Hierarchical task organization** with dependencies and subtasks
- **Real-time status tracking** with automatic checkpointing
- **Resource constraints** for budget and time management
- **EventBus integration** for real-time updates across CLI and web interfaces
- **Dual sync/async APIs** for flexible integration

## Core Concepts

### Projects
A project is a high-level container for related work with:
- **Name and description** for identification
- **Workspace path** for file organization  
- **Creation and modification timestamps**
- **Associated tasks** and their relationships
- **Overall status** derived from task completion

### Tasks
Tasks are individual work items with:
- **Hierarchical structure** (parent/child relationships)
- **Status tracking** (pending, running, completed, failed, cancelled)
- **Dependencies** between tasks
- **Resource constraints** (token budgets, time limits)
- **Execution records** with detailed logs
- **Agent assignment** for automated execution

### Dependencies
Tasks can depend on other tasks with:
- **Blocking dependencies** - task cannot start until dependencies complete
- **Soft dependencies** - preferences for execution order
- **Cross-project dependencies** - tasks can depend on tasks in other projects

## CLI Usage (Status as of v0.1.x)

### Implemented Commands

#### Project
```bash
# Create a project
penguin project create "My Project" [--description/-d TEXT]

# List projects
penguin project list

# Delete a project
penguin project delete <PROJECT_ID> [--force/-f]
```

#### Task (within a project)
```bash
# Create a task
penguin project task create <PROJECT_ID> "Task title" [--description/-d TEXT]

# List tasks
penguin project task list [<PROJECT_ID>] [--status/-s STATUS]

# Start / complete / delete
penguin project task start <TASK_ID>
penguin project task complete <TASK_ID>
penguin project task delete <TASK_ID> [--force/-f]
```

> ⚠️ The above are the **only** task-related CLI commands that exist today.  Everything else in earlier docs (update, show, pause, graphs, bulk ops, etc.) is **planned** and tracked in [future considerations](../advanced/future_considerations.md).

---

### Planned Extensions (not yet implemented)
These commands are design-level only.  Attempting to run them will produce a "No such command" error:

* `penguin project show`, `project stats`, `project archive/restore`, export/import
* `penguin project task update`, `task show`, dependency management, bulk ops
* Memory/database/workspace sub-apps
* Advanced filters (`--tree`, `--graph`, etc.)

Refer to the roadmap for progress.

## Python API

### Basic Project Management
```python
from penguin.project import ProjectManager, TaskStatus

# Initialize manager
pm = ProjectManager()

# Create project
project = pm.create_project(
    name="Web Application",
    description="Full-stack web app",
    workspace="./webapp"
)

# Create tasks
task1 = pm.create_task(
    project_id=project.id,
    title="Setup FastAPI backend",
    description="Initialize FastAPI project with basic structure"
)

task2 = pm.create_task(
    project_id=project.id,
    title="Create React frontend",
    description="Initialize React app with TypeScript",
    depends_on=[task1.id]  # Depends on backend setup
)

# List projects and tasks
projects = pm.list_projects()
tasks = pm.list_tasks(project_id=project.id)
```

### Advanced Task Management
```python
from penguin.project import TaskPriority, ResourceConstraints

# Create task with constraints
task = pm.create_task(
    project_id=project.id,
    title="Generate API documentation",
    description="Create comprehensive API docs",
    priority=TaskPriority.HIGH,
    resource_constraints=ResourceConstraints(
        max_tokens=15000,
        max_duration_minutes=120,
        allowed_tools=["file_operations", "web_search"]
    )
)

# Update task status
pm.update_task_status(task.id, TaskStatus.IN_PROGRESS)

# Add execution record
from penguin.project import ExecutionRecord
record = ExecutionRecord(
    task_id=task.id,
    agent_id="gpt-4",
    tokens_used=1200,
    duration_seconds=45,
    status=TaskStatus.COMPLETED,
    output="API documentation generated successfully"
)
pm.add_execution_record(record)
```

### Async API
```python
import asyncio
from penguin.project import AsyncProjectManager

async def main():
    apm = AsyncProjectManager()
    
    # All operations available as async
    project = await apm.create_project("Async Project")
    tasks = await apm.list_tasks(project_id=project.id)
    
    # Batch operations
    await apm.bulk_update_tasks(
        task_ids=[1, 2, 3],
        status=TaskStatus.COMPLETED
    )

asyncio.run(main())
```

## Web Interface (Coming Soon!)

### Project Dashboard
Access the web interface at `http://localhost:8000` (requires `penguin-ai[web]`):

- **Project Overview**: Visual cards showing all projects with status indicators
- **Task Board**: Kanban-style board with drag-and-drop task management
- **Gantt Chart**: Timeline view of project milestones and dependencies
- **Resource Usage**: Charts showing token consumption and time tracking

### Real-time Updates
The web interface provides real-time updates via WebSocket:

- **Live task status** changes as AI agents work
- **Progress indicators** for running tasks
- **Notification system** for task completion/failures
- **Collaborative editing** for task descriptions and notes

### Workflow Management
- **Visual dependency editor** for complex task relationships
- **Automated task creation** from natural language descriptions
- **Template system** for common project types
- **Integration hooks** for external tools (GitHub, Jira, etc.)

## Advanced Features

### Automated Task Execution
```python
from penguin import PenguinAgent
from penguin.project import TaskManager

# Create agent and task manager
agent = PenguinAgent()
tm = TaskManager()

# Execute task with agent
async def execute_task(task_id):
    task = tm.get_task(task_id)
    
    # Start task
    tm.update_task_status(task_id, TaskStatus.IN_PROGRESS)
    
    try:
        # Run agent on task
        result = await agent.run_task(
            prompt=task.description,
            max_iterations=task.resource_constraints.max_iterations
        )
        
        # Record completion
        tm.complete_task(task_id, result=result)
        
    except Exception as e:
        tm.fail_task(task_id, error=str(e))

# Execute pending tasks
pending_tasks = tm.list_tasks(status=TaskStatus.PENDING)
for task in pending_tasks:
    await execute_task(task.id)
```

### Event-Driven Architecture
```python
from penguin.project import EventBus, TaskEvent

# Subscribe to task events
def on_task_completed(event: TaskEvent):
    print(f"Task {event.task_id} completed: {event.data}")

EventBus.subscribe("task.completed", on_task_completed)

# Custom event handlers
@EventBus.handler("task.started")
async def send_notification(event):
    # Send Slack notification, update external systems, etc.
    pass
```

### Project Templates
```yaml
# project-template.yml
name: "Web Application Template"
description: "Standard full-stack web application"

tasks:
  - title: "Project Setup"
    description: "Initialize project structure and dependencies"
    subtasks:
      - "Create repository"
      - "Setup CI/CD pipeline"
      - "Configure development environment"
  
  - title: "Backend Development"
    description: "Implement server-side functionality"
    depends_on: ["Project Setup"]
    subtasks:
      - "Design database schema"
      - "Implement API endpoints"
      - "Add authentication"
      - "Write unit tests"
  
  - title: "Frontend Development"
    description: "Build user interface"
    depends_on: ["Backend Development"]
    subtasks:
      - "Create React components"
      - "Implement routing"
      - "Add state management"
      - "Style with CSS/Tailwind"

constraints:
  max_duration_days: 30
  budget_tokens: 100000
  allowed_tools: ["file_operations", "web_search", "code_execution"]
```

Load template:
```bash
penguin project create-from-template --template web-app-template.yml "My New Project"
```

## Database Schema

The project management system uses SQLite with the following key tables:

```sql
-- Projects table
CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    workspace_path TEXT,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tasks table
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id),
    parent_task_id INTEGER REFERENCES tasks(id),
    title TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'pending',
    priority TEXT DEFAULT 'medium',
    assigned_to TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Task dependencies
CREATE TABLE task_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER REFERENCES tasks(id),
    depends_on_task_id INTEGER REFERENCES tasks(id),
    dependency_type TEXT DEFAULT 'blocking',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Execution records
CREATE TABLE execution_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER REFERENCES tasks(id),
    agent_id TEXT,
    status TEXT,
    tokens_used INTEGER,
    duration_seconds INTEGER,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    output TEXT,
    error_message TEXT
);
```

## Performance and Scaling

### Database Optimization
```yaml
# config.yml
project:
  storage:
    # Enable WAL mode for better concurrency
    journal_mode: WAL
    
    # Optimize for read-heavy workloads
    synchronous: NORMAL
    cache_size: 10000
    
    # Connection pooling
    max_connections: 20
    timeout: 30
```

### Batch Operations
```python
# Efficient bulk task creation
tasks_data = [
    {"title": f"Task {i}", "project_id": project_id}
    for i in range(100)
]
pm.bulk_create_tasks(tasks_data)

# Batch status updates
pm.bulk_update_task_status(
    task_ids=list(range(1, 101)),
    status=TaskStatus.COMPLETED
)
```

### Memory Management
```python
# Use pagination for large datasets
tasks = pm.list_tasks(
    project_id=project_id,
    limit=50,
    offset=0
)

# Stream large queries
for task in pm.stream_tasks(project_id=project_id):
    process_task(task)
```

## Best Practices

### Project Organization
1. **Use clear, descriptive names** for projects and tasks
2. **Break large tasks into subtasks** for better tracking
3. **Set realistic resource constraints** to prevent runaway execution
4. **Use dependencies** to model real workflow constraints
5. **Regular checkpointing** for long-running tasks

### Task Design
1. **Atomic tasks** that can be completed independently
2. **Clear acceptance criteria** in task descriptions
3. **Appropriate time/token budgets** based on complexity
4. **Tool restrictions** to prevent unauthorized operations
5. **Regular status updates** for monitoring progress

### Error Handling
```python
from penguin.project import ProjectError, TaskError

try:
    project = pm.create_project("Test Project")
except ProjectError as e:
    logger.error(f"Failed to create project: {e}")
    
try:
    task = pm.start_task(task_id)
except TaskError as e:
    logger.error(f"Cannot start task: {e}")
```

## Troubleshooting

### Common Issues

**Database locked errors:**
```bash
# Check for long-running transactions
penguin project diagnose --check-locks

# Force unlock (use carefully)
penguin project unlock-database
```

**Performance issues:**
```bash
# Analyze database performance
penguin project analyze --performance

# Optimize database
penguin project optimize-database

# Check index usage
penguin project explain-query "SELECT * FROM tasks WHERE status = 'pending'"
```

**Circular dependencies:**
```bash
# Detect circular dependencies
penguin task validate-dependencies --all-projects

# Visualize dependency graph
penguin task graph --project "Web Application" --output deps.svg
```

For additional support, see the [API Reference](../api_reference/project_api.md) or [GitHub Issues](https://github.com/Maximooch/penguin/issues).

