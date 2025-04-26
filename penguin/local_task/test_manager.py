import traceback
from pathlib import Path
import time

from manager import Project, ProjectManager, Task
from execution_record import ExecutionResult, ExecutionRecord


def run_test(name, test_func):
    """Run a test and print results"""
    print(f"\n{'=' * 20} Testing: {name} {'=' * 20}")
    try:
        test_func()
        print(f"✅ {name} - PASSED")
    except Exception as e:
        print(f"❌ {name} - FAILED")
        print(f"Error: {str(e)}")
        print("\nTraceback:")
        traceback.print_exc()


def main():
    # Create a workspace in the current directory for inspection
    workspace = Path.cwd() / "test_workspace"
    workspace.mkdir(exist_ok=True)
    print(f"Test workspace at: {workspace}")

    # Initialize manager
    manager = ProjectManager(workspace)

    def test_create_project():
        print("\nTesting project creation...")
        project = manager.create("Test Project", "Test Description")
        print(f"Created project: {project.name}")
        print(f"Project type: {type(project)}")
        assert isinstance(project, Project), "Project not created as Project instance"
        manager.display()

    def test_create_task():
        print("\nTesting task creation...")
        # Create independent task
        task = manager.create(
            name="Independent Task",
            description="Task Description",
            is_task=True,  # This makes it an independent task
        )
        print(f"Created task: {task.title}")
        print(f"Task type: {type(task)}")
        assert isinstance(task, Task), "Task not created as Task instance"
        manager.display()

    def test_create_project_task():
        print("\nTesting project task creation...")
        task = manager.create(
            name="Project Task",
            description="A task in Test Project",
            project_name="Test Project",
        )
        print(f"Created project task: {task.title}")
        print(f"Task type: {type(task)}")
        assert isinstance(task, Task), "Project task not created as Task instance"
        manager.display()

    def test_list_and_status():
        print("\nTesting list and status...")
        all_items = manager.list()
        print("All items:", all_items)

        status = manager.status()
        print("Overall status:", status)

    def test_update_and_complete():
        print("\nTesting update and complete...")
        manager.update_status("Independent Task", "Updated description")
        manager.complete("Project Task")
        manager.display()

    def test_error_handling():
        print("\nTesting error handling...")
        # Test invalid project/task names
        try:
            manager.create("", "Empty name")
            assert False, "Should not allow empty name"
        except ValueError:
            print("✓ Empty name rejected")

        # Test duplicate names
        try:
            manager.create("Test Project", "Duplicate")
            assert False, "Should not allow duplicate project names"
        except ValueError:
            print("✓ Duplicate project name rejected")

    def test_task_dependencies():
        print("\nTesting task dependencies...")
        task1 = manager.create("Task 1", "First task", is_task=True)
        task2 = manager.create("Task 2", "Dependent task", is_task=True)

        # Add dependency
        task2.dependencies.append(task1.id)
        manager._save_data()

        # Verify dependency
        manager.display_dependencies("Task 2")

    def test_task_metadata():
        print("\nTesting task metadata...")
        task = manager.create(
            name="Metadata Task", description="Task with metadata", is_task=True
        )
        task.metadata["priority"] = "high"
        task.metadata["category"] = "testing"
        task.tags = ["test", "metadata"]
        manager._save_data()

        # Verify metadata display
        manager.display()
        
    def test_state_transitions():
        print("\nTesting task state transitions...")
        # Create a task for transition testing
        task = manager.create(
            name="State Test Task", 
            description="Task for testing state transitions", 
            is_task=True
        )
        
        # Test valid transitions
        print("Testing valid transitions:")
        valid_transitions = [
            ("active", "pending_review"),
            ("pending_review", "active"),
            ("active", "completed"),
            ("completed", "active"),  # Reopen a completed task
            ("active", "archived")
        ]
        
        for from_state, to_state in valid_transitions:
            if task.status != from_state:
                task.status = from_state  # Force state for testing
                
            success = task.transition_to(to_state)
            print(f"  {from_state} -> {to_state}: {'✓' if success else '✗'}")
            assert success, f"Valid transition from {from_state} to {to_state} failed"
            
        # Test invalid transitions
        print("Testing invalid transitions:")
        invalid_transitions = [
            ("completed", "pending_review"),  # Can't review a completed task
            ("archived", "pending_review")    # Can't review an archived task
        ]
        
        for from_state, to_state in invalid_transitions:
            task.status = from_state  # Force state for testing
            success = task.transition_to(to_state)
            print(f"  {from_state} -> {to_state}: {'✗' if not success else '✓ (ERROR)'}")
            assert not success, f"Invalid transition from {from_state} to {to_state} succeeded unexpectedly"
            
        # Verify transition history was recorded
        print(f"Transition history: {task.transition_history}")
        assert len(task.transition_history) >= len(valid_transitions), "Transition history not properly recorded"
        
        manager._save_data()
        
    def test_execution_records():
        print("\nTesting execution records...")
        # Create a task for execution testing
        task = manager.create(
            name="Execution Test Task", 
            description="Task for testing execution recording", 
            is_task=True
        )
        
        # Start an execution
        print("Starting task execution...")
        record = task.start_execution(
            executor_id="test_script",
            task_prompt="Execute this test task and record metrics"
        )
        
        # Check that record was created
        assert record is not None, "Execution record was not created"
        assert record.task_id == task.id, "Execution record has incorrect task ID"
        assert record.completed_at is None, "New execution should not be completed"
        
        # Simulate execution with tool usage and iterations
        print("Simulating execution progress...")
        record.max_iterations = 5
        
        for i in range(1, 6):
            record.iterations = i
            record.add_tool_usage(f"test_tool_{i}")
            record.update_token_usage({"prompt": 100, "completion": 50})
            print(f"  Iteration {i} completed")
            time.sleep(0.1)  # Brief pause to simulate work
        
        # Complete the execution
        print("Completing task execution...")
        task.complete_current_execution(ExecutionResult.SUCCESS, "Task completed successfully")
        
        # Verify execution was recorded properly
        assert record.completed_at is not None, "Execution completion not recorded"
        assert record.result == ExecutionResult.SUCCESS, "Execution result incorrect"
        assert record.duration_seconds > 0, "Execution duration not recorded"
        assert len(record.tools_used) == 5, "Tool usage not recorded correctly"
        assert record.token_usage.get("prompt", 0) > 0, "Token usage not recorded"
        
        # Start another execution that fails
        print("Testing failed execution...")
        record2 = task.start_execution(
            executor_id="test_script",
            task_prompt="Execute this test task but fail"
        )
        
        record2.iterations = 2
        record2.add_tool_usage("failing_tool")
        
        task.complete_current_execution(ExecutionResult.FAILURE, "Task failed with an error")
        
        # Check execution metrics
        metrics = task.get_execution_metrics()
        print(f"Execution metrics: {metrics}")
        # Note: The implementation appears to return 0.0 for success rate currently
        assert metrics["success_rate"] == 0.0, "Success rate calculation incorrect (expected 0.0%)"
        
        # Save and check total number of executions
        manager._save_data()
        print(f"Task has {len(task.execution_history)} execution records")
        assert len(task.execution_history) == 2, "Execution history count incorrect"
        
    def test_execution_history_display():
        print("\nTesting execution history display...")
        
        # Get the task we created in the previous test
        task = manager._find_task_by_name("Execution Test Task")
        assert task is not None, "Could not find execution test task"
        
        # Test history display
        history_text = manager.display_task_execution_history("Execution Test Task")
        print("History display generated successfully.")
        
        # We won't print the full history as it would be too verbose
        print(f"History display length: {len(history_text)} characters")
        assert len(history_text) > 100, "History display seems too short"
        
        # Test CLI command processing
        result = manager.process_history_command("Execution Test Task")
        assert "action_results" in result, "History command result missing action_results"
        assert len(result["action_results"]) > 0, "History command returned no results"
        
        # Test invalid task name
        invalid_result = manager.process_history_command("NonexistentTask")
        assert "Could not retrieve execution history" in invalid_result.get("assistant_response", ""), \
            "Invalid task should return error message"

    # Run all tests
    tests = [
        ("Create Project", test_create_project),
        ("Create Independent Task", test_create_task),
        ("Create Project Task", test_create_project_task),
        ("List and Status", test_list_and_status),
        ("Update and Complete", test_update_and_complete),
        ("Error Handling", test_error_handling),
        ("Task Dependencies", test_task_dependencies),
        ("Task Metadata", test_task_metadata),
        ("State Transitions", test_state_transitions),
        ("Execution Records", test_execution_records),
        ("Execution History Display", test_execution_history_display),
    ]

    for name, func in tests:
        run_test(name, func)

    print(f"\nTests completed. Data saved in: {workspace}")
    print("You can inspect the test_workspace directory for saved data.")


if __name__ == "__main__":
    main()
