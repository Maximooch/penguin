#!/usr/bin/env python3
"""Test script to verify the memory search fix."""

import asyncio
import yaml
import sys
import os
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from penguin.tools.tool_manager import ToolManager
from penguin.utils.log_error import log_error
from penguin.utils.parser import ActionExecutor, CodeActAction, ActionType
from penguin.local_task.manager import ProjectManager

async def test_memory_system():
    """Test the complete memory system functionality."""
    print("Testing memory system fix...")
    
    # Load config from the correct path
    config_path = project_root / "penguin" / "config.yml"
    config = yaml.safe_load(open(config_path))
    
    # Initialize components
    tm = ToolManager(config, log_error)
    
    # Initialize memory provider directly for adding test data
    from penguin.memory.providers.factory import MemoryProviderFactory
    memory_config = config.get("memory")
    provider = MemoryProviderFactory.create_provider(memory_config)
    await provider.initialize()
    
    print("1. Adding test memory...")
    memory_id = await provider.add_memory(
        content="This is a test memory for searching functionality",
        metadata={"type": "test", "source": "test_script"},
        categories=["test", "functionality"]
    )
    print(f"   Memory added with ID: {memory_id}")
    
    print("2. Testing memory search via ToolManager...")
    result = tm.execute_tool('memory_search', {'query': 'test memory'})
    print(f"   ToolManager result: {result}")
    
    print("3. Testing memory search via ActionExecutor...")
    pm = ProjectManager('/Users/maximusputnam/penguin_workspace')
    ae = ActionExecutor(tm, pm)
    action = CodeActAction(ActionType.MEMORY_SEARCH, 'test memory')
    ae_result = await ae.execute_action(action)
    print(f"   ActionExecutor result: {ae_result}")
    
    print("\nTest completed successfully!")
    return True

if __name__ == "__main__":
    asyncio.run(test_memory_system()) 