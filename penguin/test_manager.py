import sys
from pathlib import Path
import shutil
import asyncio
from datetime import datetime
import traceback
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add parent directory to path to import manager
from local_task.manager import ProjectManager, Task, Project

def setup_test_workspace():
    """Create a test workspace that persists between runs"""
    test_workspace = Path("test_workspace")
    if not test_workspace.exists():
        test_workspace.mkdir()
        logger.info(f"Created test workspace at {test_workspace.absolute()}")
    
    # Create expected files if they don't exist
    data_file = test_workspace / "projects_and_tasks.json"
    workspace_file = test_workspace / "independent_tasks.json"
    
    if not data_file.exists():
        data_file.write_text("{}")
        logger.debug(f"Created empty projects file: {data_file}")
    
    if not workspace_file.exists():
        workspace_file.write_text('{"independent_tasks": {}}')
        logger.debug(f"Created empty tasks file: {workspace_file}")
        
    return test_workspace

def test_project_creation(manager):
    """Test creating a project"""
    logger.info("\nTesting project creation...")
    try:
        # Create project
        project = manager._create_project("Test Project", "A test project")
        logger.debug(f"Created project: {project.__dict__}")
        
        assert project.name == "Test Project", f"Project name mismatch: {project.name}"
        assert project.description == "A test project", f"Project description mismatch: {project.description}"
        assert project.id in manager.projects, f"Project ID not found in manager: {project.id}"
        assert (manager.projects_dir / "Test Project").exists(), "Project directory not created"
        assert (manager.projects_dir / "Test Project" / "context").exists(), "Project context directory not created"
        
        print("✓ Project creation successful")
        return project
        
    except Exception as e:
        logger.error(f"Project creation failed: {str(e)}")
        logger.error(traceback.format_exc())
        raise

def test_task_creation(manager, project):
    """Test creating independent and project tasks"""
    logger.info("\nTesting task creation...")
    try:
        # Create independent task
        task1 = manager._create_independent_task("Test Task", "A test task")
        logger.debug(f"Created independent task: {task1.__dict__}")
        
        assert task1.title == "Test Task", f"Task title mismatch: {task1.title}"
        assert task1.description == "A test task", f"Task description mismatch: {task1.description}"
        assert task1.id in manager.independent_tasks, f"Task ID not found in manager: {task1.id}"
        print("✓ Independent task creation successful")
        
        # Create project task
        task2 = manager._create_project_task(project.id, "Project Task", "A project task")
        logger.debug(f"Created project task: {task2.__dict__}")
        
        assert task2.title == "Project Task", f"Project task title mismatch: {task2.title}"
        assert task2.description == "A project task", f"Project task description mismatch: {task2.description}"
        assert task2.id in project.tasks, f"Task ID not found in project: {task2.id}"
        print("✓ Project task creation successful")
        
        return task1, task2
        
    except Exception as e:
        logger.error(f"Task creation failed: {str(e)}")
        logger.error(traceback.format_exc())
        raise

async def test_get_next_task(manager):
    """Test getting next task based on priority"""
    logger.info("\nTesting get_next_task...")
    try:
        # Create tasks with different priorities
        task1 = manager._create_independent_task("High Priority", "Important task")
        task1.priority = 1
        logger.debug(f"Created high priority task: {task1.__dict__}")
        
        task2 = manager._create_independent_task("Low Priority", "Less important task")
        task2.priority = 3
        logger.debug(f"Created low priority task: {task2.__dict__}")
        
        project = manager._create_project("Priority Project", "Project with tasks")
        task3 = manager._create_project_task(project.id, "Medium Priority", "Project task")
        task3.priority = 2
        logger.debug(f"Created medium priority project task: {task3.__dict__}")
        
        # Get next task
        next_task = await manager.get_next_task()
        logger.debug(f"Retrieved next task: {next_task}")
        
        assert next_task is not None, "No task returned"
        assert next_task["title"] == "High Priority", f"Wrong task returned: {next_task['title']}"
        assert next_task["priority"] == 1, f"Wrong priority: {next_task['priority']}"
        print("✓ Next task retrieval successful")
        
    except Exception as e:
        logger.error(f"Get next task failed: {str(e)}")
        logger.error(traceback.format_exc())
        raise

def test_task_completion(manager):
    """Test completing tasks"""
    logger.info("\nTesting task completion...")
    try:
        # Create and complete task
        task = manager._create_independent_task("Complete Me", "Task to complete")
        logger.debug(f"Created task for completion: {task.__dict__}")
        
        result = manager.complete_task("Complete Me")
        logger.debug(f"Completion result: {result}")
        
        assert result["status"] == "completed", f"Task not completed: {result}"
        assert manager.independent_tasks[task.id].status == "completed", f"Task status not updated: {manager.independent_tasks[task.id].status}"
        print("✓ Task completion successful")
        
    except Exception as e:
        logger.error(f"Task completion failed: {str(e)}")
        logger.error(traceback.format_exc())
        raise

async def run_tests():
    """Run all tests"""
    logger.info("Starting ProjectManager tests...")
    
    # Setup
    test_workspace = setup_test_workspace()
    manager = ProjectManager(test_workspace)
    
    try:
        # Run tests
        project = test_project_creation(manager)
        task1, task2 = test_task_creation(manager, project)
        await test_get_next_task(manager)
        test_task_completion(manager)
        
        print("\nAll tests passed! ✓")
        logger.info("Test data preserved in ./test_workspace")
        
    except AssertionError as e:
        logger.error(f"Test failed: {str(e)}")
        logger.error(traceback.format_exc())
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    asyncio.run(run_tests())