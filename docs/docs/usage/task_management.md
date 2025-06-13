# Task Management

This guide focuses specifically on task management within Penguin's project system. Tasks are the fundamental units of work that can be executed by AI agents, tracked for progress, and organized into complex workflows.

## Task Lifecycle

### Task States
Tasks progress through several states during their lifecycle:

- **Pending** - Created but not yet started
- **In Progress** - Currently being worked on
- **Completed** - Successfully finished
- **Failed** - Encountered an error and could not complete
- **Cancelled** - Manually cancelled before completion
- **Paused** - Temporarily suspended (can be resumed)

### State Transitions
```
Pending → In Progress → Completed
    ↓         ↓           ↗
    ↓    → Failed      ↗
    ↓         ↓       ↗
    → Cancelled ←→ Paused
```

## Creating Effective Tasks

### Task Design Principles

1. **Atomic and Focused**: Each task should accomplish one clear objective
2. **Self-Contained**: Tasks should have all necessary context and information
3. **Measurable**: Include clear success criteria and acceptance conditions
4. **Appropriately Scoped**: Not too large (overwhelming) or too small (overhead)
5. **Resource Aware**: Set realistic budgets for time, tokens, and tool usage

### Task Components

#### Title and Description
```bash
# Good: Clear, actionable title
penguin task create "Implement user authentication API endpoints"

# Better: With detailed description
penguin task create "Implement user authentication API endpoints" \
  --description "Create login, logout, and token refresh endpoints using FastAPI and JWT tokens. Include input validation, error handling, and rate limiting."
```

#### Resource Constraints
```bash
# Set token budget to prevent runaway costs
penguin task create "Generate comprehensive documentation" \
  --budget-tokens 15000 \
  --budget-minutes 120

# Limit available tools for security
penguin task create "Analyze log files" \
  --allowed-tools "file_operations,web_search"
```

#### Dependencies and Relationships
```bash
# Task that depends on database setup
penguin task create "Create user models" \
  --depends-on "Setup database schema" \
  --project "Web Application"

# Subtask relationship
penguin task create "Write unit tests for auth" \
  --parent-task 42
```

## Task Organization Patterns

### Hierarchical Structure
```
Project: E-commerce Platform
├── Phase 1: Foundation
│   ├── Setup development environment
│   ├── Initialize project structure  
│   └── Configure CI/CD pipeline
├── Phase 2: Backend Development
│   ├── Database design
│   │   ├── User schema
│   │   ├── Product schema
│   │   └── Order schema
│   ├── API implementation
│   │   ├── Authentication endpoints
│   │   ├── User management
│   │   └── Product catalog
│   └── Testing
│       ├── Unit tests
│       └── Integration tests
└── Phase 3: Frontend Development
    ├── React setup
    ├── Component development
    └── State management
```

### Dependency Patterns

#### Sequential Dependencies
```bash
# Classic waterfall: A → B → C
penguin task create "Design database schema"
penguin task create "Implement data models" --depends-on "Design database schema"
penguin task create "Create API endpoints" --depends-on "Implement data models"
```

#### Parallel Development
```bash
# Frontend and backend can develop in parallel
penguin task create "Backend API development"
penguin task create "Frontend component development"  # No dependency

# Both needed for integration
penguin task create "Frontend-backend integration" \
  --depends-on "Backend API development" "Frontend component development"
```

#### Feature Branching
```bash
# Base feature
penguin task create "Basic user authentication"

# Parallel feature enhancements
penguin task create "Social login integration" --depends-on "Basic user authentication"
penguin task create "Two-factor authentication" --depends-on "Basic user authentication"
penguin task create "Password reset functionality" --depends-on "Basic user authentication"
```

## Advanced Task Features

### Resource Constraints and Budgets

#### Token Budget Management
```python
from penguin.project import ResourceConstraints

# Set realistic token budgets based on task complexity
constraints = ResourceConstraints(
    max_tokens=5000,      # Simple code changes
    max_tokens=15000,     # Documentation generation
    max_tokens=25000,     # Complex refactoring
    max_tokens=50000      # Large feature implementation
)
```

#### Time Constraints
```bash
# Set time limits to prevent infinite loops
penguin task create "Quick bug fix" \
  --budget-minutes 30 \
  --priority high

# Longer tasks for complex work
penguin task create "Refactor authentication system" \
  --budget-minutes 240 \
  --max-iterations 15
```

#### Tool Restrictions
```bash
# Read-only tasks
penguin task create "Code review and analysis" \
  --allowed-tools "file_operations:read,web_search"

# Development tasks
penguin task create "Implement new feature" \
  --allowed-tools "file_operations,code_execution,web_search"

# Documentation tasks
penguin task create "Update API documentation" \
  --allowed-tools "file_operations,web_search,markdown_processing"
```

### Priority Management

#### Priority Levels
```bash
# Critical issues that block other work
penguin task create "Fix production outage" --priority critical

# Important features for upcoming release
penguin task create "Implement payment processing" --priority high

# Regular development work
penguin task create "Add user preferences page" --priority medium

# Nice-to-have improvements
penguin task create "Optimize database queries" --priority low
```

#### Priority-Based Scheduling
```python
from penguin.project import TaskManager, TaskPriority

tm = TaskManager()

# Get tasks sorted by priority for execution
tasks = tm.list_tasks(
    status=TaskStatus.PENDING,
    sort_by="priority,created_at",
    order="desc"
)

# Execute high-priority tasks first
for task in tasks:
    if task.priority == TaskPriority.CRITICAL:
        tm.start_task(task.id)
```

### Agent Assignment

#### Manual Assignment
```bash
# Assign to specific model for specialized tasks
penguin task create "Generate creative marketing copy" \
  --assigned-to "claude-3-opus-20240229"

penguin task create "Optimize SQL queries" \
  --assigned-to "gpt-4"

penguin task create "Debug JavaScript issues" \
  --assigned-to "claude-3-sonnet-20240229"
```

#### Automatic Assignment
```python
from penguin.project import AgentMatcher

# Automatically assign based on task type and agent capabilities
matcher = AgentMatcher()

def assign_task_to_best_agent(task):
    best_agent = matcher.find_best_agent(
        task_type=task.get_task_type(),
        required_tools=task.resource_constraints.allowed_tools,
        complexity=task.get_complexity_score()
    )
    return best_agent
```

## Task Execution Monitoring

### Real-time Progress Tracking

#### CLI Monitoring
```bash
# Watch task progress in real-time
penguin task watch 123

# Show execution log
penguin task logs 123 --follow

# Display resource usage
penguin task usage 123 --live
```

#### Programmatic Monitoring
```python
import asyncio
from penguin.project import TaskManager, EventBus

tm = TaskManager()

async def monitor_task(task_id):
    """Monitor task execution with real-time updates"""
    
    # Subscribe to task events
    @EventBus.handler(f"task.{task_id}.progress")
    async def on_progress(event):
        print(f"Task {task_id}: {event.data['progress']}% complete")
    
    @EventBus.handler(f"task.{task_id}.status_changed")
    async def on_status_change(event):
        print(f"Task {task_id} status: {event.data['old_status']} → {event.data['new_status']}")
    
    # Wait for completion
    while True:
        task = tm.get_task(task_id)
        if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
            break
        await asyncio.sleep(1)

# Monitor multiple tasks
async def monitor_project(project_id):
    tasks = tm.list_tasks(project_id=project_id, status=TaskStatus.IN_PROGRESS)
    await asyncio.gather(*[monitor_task(task.id) for task in tasks])
```

### Execution Records and Analytics

#### Viewing Execution History
```bash
# Show detailed execution records
penguin task show 123 --history

# Analyze task performance
penguin task analyze 123 --metrics

# Compare execution across similar tasks
penguin task compare --filter "label:backend" --metric duration
```

#### Performance Analytics
```python
from penguin.project import ExecutionAnalyzer

analyzer = ExecutionAnalyzer()

# Analyze task performance patterns
stats = analyzer.analyze_task_performance(
    project_id=project.id,
    date_range="last_30_days"
)

print(f"Average completion time: {stats.avg_duration_minutes}m")
print(f"Token efficiency: {stats.tokens_per_minute}")
print(f"Success rate: {stats.success_rate}%")

# Identify bottlenecks
bottlenecks = analyzer.find_bottlenecks(project_id=project.id)
for bottleneck in bottlenecks:
    print(f"Bottleneck: {bottleneck.task_title} - {bottleneck.issue}")
```

## Task Templates and Automation

### Common Task Templates

#### Code Development Template
```yaml
# code-development-template.yml
name: "Code Development Task"
description: "Standard template for implementing new features"

fields:
  - name: feature_name
    type: string
    required: true
  - name: complexity
    type: choice
    options: [simple, medium, complex]
    default: medium

resource_constraints:
  max_tokens: "{{ 5000 if complexity == 'simple' else 15000 if complexity == 'medium' else 25000 }}"
  max_duration_minutes: "{{ 60 if complexity == 'simple' else 180 if complexity == 'medium' else 360 }}"
  allowed_tools: ["file_operations", "code_execution", "web_search"]

subtasks:
  - title: "Design {{ feature_name }} architecture"
    description: "Plan the implementation approach and identify components"
  - title: "Implement {{ feature_name }} core functionality"
    description: "Write the main implementation code"
  - title: "Add tests for {{ feature_name }}"
    description: "Create unit and integration tests"
  - title: "Update documentation for {{ feature_name }}"
    description: "Update relevant documentation and examples"
```

#### Bug Fix Template
```yaml
# bug-fix-template.yml
name: "Bug Fix Task"
description: "Template for investigating and fixing bugs"

fields:
  - name: bug_description
    type: text
    required: true
  - name: severity
    type: choice
    options: [low, medium, high, critical]
    default: medium

resource_constraints:
  max_tokens: "{{ 3000 if severity in ['low', 'medium'] else 8000 }}"
  max_duration_minutes: "{{ 30 if severity == 'low' else 60 if severity == 'medium' else 180 }}"
  allowed_tools: ["file_operations", "code_execution", "web_search", "debugging_tools"]

workflow:
  - title: "Reproduce {{ bug_description }}"
    description: "Verify the bug and understand its scope"
  - title: "Investigate root cause"
    description: "Analyze code and logs to identify the underlying issue"
  - title: "Implement fix"
    description: "Make necessary code changes to resolve the issue"
  - title: "Test fix"
    description: "Verify the fix works and doesn't introduce new issues"
```

### Automated Task Creation

#### From Project Specifications
```python
from penguin.project import SpecificationParser

# Parse natural language project specification
spec = """
Create a REST API for a blog platform with the following features:
- User authentication and authorization
- CRUD operations for blog posts
- Comment system with moderation
- Tag-based categorization
- Search functionality
- Rate limiting and security features
"""

parser = SpecificationParser()
project_plan = parser.parse_specification(spec)

# Automatically create tasks from plan
tm = TaskManager()
project = tm.create_project("Blog API", description=spec)

for phase in project_plan.phases:
    phase_task = tm.create_task(
        project_id=project.id,
        title=phase.title,
        description=phase.description
    )
    
    for task_spec in phase.tasks:
        tm.create_task(
            project_id=project.id,
            parent_task_id=phase_task.id,
            title=task_spec.title,
            description=task_spec.description,
            resource_constraints=task_spec.constraints
        )
```

#### From Code Analysis
```python
from penguin.project import CodeAnalyzer

# Analyze existing codebase to suggest tasks
analyzer = CodeAnalyzer()
suggestions = analyzer.analyze_codebase("./src")

for suggestion in suggestions.tasks:
    if suggestion.priority >= 0.7:  # High confidence suggestions
        tm.create_task(
            project_id=project.id,
            title=suggestion.title,
            description=suggestion.description,
            priority=suggestion.get_priority_level(),
            resource_constraints=suggestion.estimated_constraints
        )
```

## Task Collaboration and Handoffs

### Multi-Agent Collaboration

#### Sequential Agent Handoffs
```python
from penguin.project import AgentWorkflow

# Define workflow with different agents for different phases
workflow = AgentWorkflow([
    {
        "agent": "claude-3-opus-20240229",  # Planning phase
        "phase": "design",
        "description": "Design system architecture and create implementation plan"
    },
    {
        "agent": "gpt-4",  # Implementation phase
        "phase": "implementation", 
        "description": "Implement the designed solution"
    },
    {
        "agent": "claude-3-sonnet-20240229",  # Review phase
        "phase": "review",
        "description": "Review implementation and suggest improvements"
    }
])

# Execute workflow
result = await workflow.execute(task_id=123)
```

#### Parallel Collaboration
```python
# Split task into parallel subtasks
main_task = tm.get_task(123)
subtasks = tm.split_task(
    task_id=123,
    split_strategy="parallel",
    num_subtasks=3
)

# Assign different agents to each subtask
agents = ["gpt-4", "claude-3-opus-20240229", "claude-3-sonnet-20240229"]
for subtask, agent in zip(subtasks, agents):
    tm.assign_agent(subtask.id, agent)
    tm.start_task(subtask.id)

# Wait for all subtasks to complete, then merge results
await tm.wait_for_subtasks(main_task.id)
merged_result = tm.merge_subtask_results(main_task.id)
```

### Human-AI Collaboration

#### Review and Approval Workflows
```bash
# Create task requiring human approval
penguin task create "Deploy to production" \
  --requires-approval \
  --approver "team-lead"

# Task will pause before execution for approval
penguin task approve 123 --notes "Deployment approved after review"

# Or reject with feedback
penguin task reject 123 --reason "Need additional testing"
```

#### Collaborative Editing
```python
from penguin.project import CollaborativeTask

# Create task that allows human intervention
collab_task = CollaborativeTask(
    title="Refactor legacy authentication system",
    description="Modernize auth system while maintaining compatibility",
    collaboration_mode="assisted"  # AI suggests, human reviews/edits
)

# Human can pause and provide feedback at any point
@collab_task.on_pause
def human_review(task_state):
    """Called when AI requests human input"""
    print(f"AI suggests: {task_state.current_suggestion}")
    feedback = input("Your feedback (or 'continue'): ")
    
    if feedback != 'continue':
        task_state.add_human_feedback(feedback)
    
    return "continue"
```

## Troubleshooting Task Issues

### Common Task Problems

#### Resource Exhaustion
```bash
# Check resource usage
penguin task usage 123

# Increase budget if needed
penguin task update 123 --budget-tokens 20000 --budget-minutes 180

# Resume with new constraints
penguin task resume 123
```

#### Dependency Deadlocks
```bash
# Check for circular dependencies
penguin task validate-dependencies --project "My Project"

# Visualize dependency graph
penguin task graph --project "My Project" --output deps.png

# Break circular dependency
penguin task remove-dependency 123 456
```

#### Tool Permission Issues
```bash
# Check what tools task is trying to use
penguin task logs 123 --filter tool_usage

# Update allowed tools
penguin task update 123 --allowed-tools "file_operations,web_search,code_execution"

# Restart task with new permissions
penguin task restart 123
```

### Task Recovery Strategies

#### Checkpoint and Resume
```python
# Automatic checkpointing during long tasks
tm.enable_auto_checkpoint(task_id=123, interval_minutes=15)

# Manual checkpoint at safe points
tm.create_checkpoint(task_id=123, description="Completed database setup")

# Resume from checkpoint if task fails
if tm.get_task(123).status == TaskStatus.FAILED:
    latest_checkpoint = tm.get_latest_checkpoint(task_id=123)
    tm.resume_from_checkpoint(task_id=123, checkpoint_id=latest_checkpoint.id)
```

#### Task Splitting
```python
# Split overly complex task into smaller pieces
if task.estimated_complexity > 0.8:
    subtasks = tm.split_task(
        task_id=task.id,
        split_strategy="complexity_based",
        max_subtask_complexity=0.5
    )
    
    # Execute subtasks individually
    for subtask in subtasks:
        tm.start_task(subtask.id)
```

#### Error Recovery
```python
from penguin.project import ErrorRecovery

# Automatic error recovery strategies
recovery = ErrorRecovery()

@recovery.handler("TokenLimitExceeded")
def handle_token_limit(task, error):
    # Increase token budget and retry
    tm.update_task_constraints(
        task.id,
        max_tokens=task.resource_constraints.max_tokens * 1.5
    )
    return "retry"

@recovery.handler("ToolPermissionDenied")
def handle_permission_error(task, error):
    # Request human intervention
    return "request_human_approval"
```

## Best Practices Summary

### Task Design
1. **Clear Objectives**: Every task should have a clear, measurable goal
2. **Appropriate Scope**: Neither too large nor too small
3. **Resource Planning**: Set realistic budgets based on complexity
4. **Tool Selection**: Only allow necessary tools for security
5. **Dependency Management**: Model real-world constraints accurately

### Execution Management  
1. **Progress Monitoring**: Track execution in real-time
2. **Resource Monitoring**: Watch token and time usage
3. **Error Handling**: Implement recovery strategies
4. **Checkpointing**: Save progress for long-running tasks
5. **Quality Gates**: Include review and approval steps

### Collaboration
1. **Agent Selection**: Match agents to task requirements
2. **Handoff Protocols**: Clear interfaces between agents
3. **Human Oversight**: Include human review for critical tasks
4. **Documentation**: Maintain clear execution records
5. **Feedback Loops**: Learn from completed tasks

For more advanced task management patterns, see the [Project Management Guide](project_management.md) and [API Reference](../api_reference/project_api.md).

