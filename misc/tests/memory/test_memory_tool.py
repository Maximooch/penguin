"""
Direct test script for the memory_search tool via the ToolManager.
"""

import asyncio
import json
import shutil
import tempfile
from pathlib import Path
import os
import yaml

# This setup is to allow running the script directly
if __name__ == "__main__":
    import sys
    project_root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(project_root))

from penguin.tools.tool_manager import ToolManager
from penguin.config import load_config, WORKSPACE_PATH

# A dummy error logger for the tool manager
def log_error(err, msg):
    print(f"ERROR: {msg}\n{err}")

async def main():
    """Sets up a temporary workspace, runs the memory tool, and cleans up."""
    # Use a temporary directory for the workspace to keep tests isolated
    temp_workspace = tempfile.mkdtemp()
    print(f"--- Using temporary workspace: {temp_workspace} ---")

    # Temporarily override the WORKSPACE_PATH for the test
    os.environ['PENGUIN_WORKSPACE'] = temp_workspace
    
    # Manually load the config and override paths
    main_config_path = project_root / "penguin" / "penguin" / "config.yml"
    with open(main_config_path, 'r') as f:
        config_data = yaml.safe_load(f)
    
    config_data["memory"]["storage_path"] = temp_workspace

    try:
        # 1. Initialize ToolManager
        tool_manager = ToolManager(config_data, log_error)

        # 2. Add some data to the memory via the underlying provider
        provider_config = config_data.get("memory", {})
        if not provider_config:
            print("Memory configuration missing from config.yml. Aborting.")
            return

        from penguin.memory.providers.factory import MemoryProviderFactory
        provider = MemoryProviderFactory.create_provider(provider_config)
        await provider.initialize()
        
        print("\n--- Adding items to memory ---")
        await provider.add_memory("The first penguin was a software engineer.", {"doc": "history_a"})
        await provider.add_memory("The second penguin was a data scientist.", {"doc": "history_b"})
        print("... Items added.")

        # 3. Use the tool_manager to perform a search
        print("\n--- Performing memory_search via ToolManager ---")
        tool_input = {"query": "penguin profession"}
        result_json = await tool_manager.perform_memory_search(
            query=tool_input["query"], k=5
        )
        
        print("\n--- Search Result ---")
        try:
            result_data = json.loads(result_json)
            print(json.dumps(result_data, indent=2))

            if "error" in result_data:
                print(f"XXX Test FAILED: Tool returned an error: {result_data['error']} XXX")
            else:
                assert len(result_data) > 0
                assert "penguin" in result_data[0]['content']
                print("\n--- Test Assertion PASSED ---")

        except (json.JSONDecodeError, AssertionError, IndexError) as e:
            print(f"XXX Test Assertion FAILED: {e} XXX")
            print("Raw output:", result_json)

    finally:
        # Cleanup
        print("\n--- Cleaning up temporary workspace ---")
        shutil.rmtree(temp_workspace)
        if 'PENGUIN_WORKSPACE' in os.environ:
            del os.environ['PENGUIN_WORKSPACE']


if __name__ == "__main__":
    asyncio.run(main()) 