import traceback
from pathlib import Path

from manager import Project, ProjectManager, Task


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
    ]

    for name, func in tests:
        run_test(name, func)

    print(f"\nTests completed. Data saved in: {workspace}")
    print("You can inspect the test_workspace directory for saved data.")


if __name__ == "__main__":
    main()
