import asyncio
import logging
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock
import traceback

from run_mode import RunMode
from local_task.manager import ProjectManager

# Configure logging
logging.basicConfig(level=logging.DEBUG,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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

def setup_mock_core():
    """Create a mock core with required attributes"""
    core = MagicMock()
    
    # Setup project manager
    core.project_manager = ProjectManager(Path("test_workspace"))
    
    # Setup async method mocks
    async def mock_process_input(input_data):
        return None
    async def mock_get_response(*args, **kwargs):
        return ({"assistant_response": "Task completed", "action_results": []}, True)
    
    # Assign async mocks
    core.process_input = MagicMock(side_effect=mock_process_input)
    core.get_response = MagicMock(side_effect=mock_get_response)
    
    # Other required attributes
    core._interrupt_pending = False
    core.diagnostics = MagicMock()
    core.diagnostics.get_cpu_usage.return_value = 50
    core.diagnostics.get_memory_usage.return_value = 50
    
    return core

async def test_continuous_mode_basic(run_mode, mock_core):
    """Test basic continuous mode operation"""
    logger.info("\nTesting continuous mode basic operation...")
    try:
        # Create some test tasks
        pm = mock_core.project_manager
        task1 = pm._create_independent_task("High Priority", "Important task")
        task1.priority = 1
        logger.debug(f"Created high priority task: {task1.__dict__}")
        
        task2 = pm._create_independent_task("Low Priority", "Less important task")
        task2.priority = 3
        logger.debug(f"Created low priority task: {task2.__dict__}")
        
        # Start continuous mode in background
        continuous_task = asyncio.create_task(run_mode.start_continuous())
        
        # Let it run for a short time
        await asyncio.sleep(2)
        
        # Request shutdown
        run_mode._shutdown_requested = True
        await continuous_task
        
        # Verify behavior
        assert mock_core.process_input.called, "Core process_input was not called"
        assert mock_core.get_response.called, "Core get_response was not called"
        
        # Check that high priority task was processed first
        first_call = mock_core.process_input.call_args_list[0]
        assert "High Priority" in str(first_call), "High priority task was not processed first"
        print("✓ Basic continuous mode operation successful")
        
    except Exception as e:
        logger.error(f"Continuous mode basic test failed: {str(e)}")
        logger.error(traceback.format_exc())
        raise

async def test_continuous_mode_time_limit(run_mode, mock_core):
    """Test continuous mode time limit"""
    logger.info("\nTesting continuous mode time limit...")
    try:
        # Set a very short time limit
        run_mode.time_limit = timedelta(seconds=2)
        
        # Create a test task
        pm = mock_core.project_manager
        task = pm._create_independent_task("Test Task", "Task description")
        logger.debug(f"Created task: {task.__dict__}")
        
        # Start continuous mode
        start_time = datetime.now()
        await run_mode.start_continuous()
        end_time = datetime.now()
        
        # Verify time limit was respected
        duration = end_time - start_time
        assert duration.total_seconds() <= 3, f"Ran too long: {duration.total_seconds()} seconds"
        print("✓ Time limit test successful")
        
    except Exception as e:
        logger.error(f"Time limit test failed: {str(e)}")
        raise

async def test_continuous_mode_error_handling(run_mode, mock_core):
    """Test error handling in continuous mode"""
    logger.info("\nTesting continuous mode error handling...")
    try:
        # Create a test task
        pm = mock_core.project_manager
        task = pm._create_independent_task("Error Task", "Task that will fail")
        logger.debug(f"Created error task: {task.__dict__}")
        
        # Make core.process_input raise an exception
        mock_core.process_input.side_effect = Exception("Test error")
        
        # Start continuous mode
        await run_mode.start_continuous()
        
        # Verify error was handled gracefully
        assert not run_mode.continuous_mode, "Continuous mode not properly stopped after error"
        print("✓ Error handling test successful")
        
    except Exception as e:
        logger.error(f"Error handling test failed: {str(e)}")
        raise

async def run_tests():
    """Run all tests"""
    logger.info("Starting RunMode tests...")
    
    # Setup
    test_workspace = setup_test_workspace()
    mock_core = setup_mock_core()
    run_mode = RunMode(mock_core, max_iterations=5, time_limit=1)
    
    try:
        # Run tests
        await test_continuous_mode_basic(run_mode, mock_core)
        await test_continuous_mode_time_limit(run_mode, mock_core)
        await test_continuous_mode_error_handling(run_mode, mock_core)
        
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