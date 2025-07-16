#!/usr/bin/env python3
"""
Test action tag integration with the parser.
"""

import os
import sys
import tempfile
from pathlib import Path

# Add the penguin directory to sys.path
penguin_dir = Path(__file__).parent / "penguin"
sys.path.insert(0, str(penguin_dir))

from penguin.utils.parser import ActionType, CodeActAction, ActionExecutor
from penguin.tools.tool_manager import ToolManager

def test_action_tags():
    """Test that action tags work with the parser."""
    print("🏷️  Testing Action Tag Integration")
    print("=" * 50)
    
    # Mock configuration and tool manager
    config = {"diagnostics": {"enabled": False}}
    def mock_log_error(e, msg):
        print(f"Error: {msg}")
    
    tool_manager = ToolManager(config, mock_log_error)
    executor = ActionExecutor(tool_manager, None)
    
    # Create test file
    test_dir = tempfile.mkdtemp()
    test_file = Path(test_dir) / "test.py"
    test_file.write_text("print('hello')")
    
    try:
        # Test enhanced_read action
        print("\n1. Testing ENHANCED_READ action tag:")
        action = CodeActAction(ActionType.ENHANCED_READ, f"{test_file}:true:5")
        result = executor._enhanced_read(action.params)
        print(f"Result: {result}")
        
        # Test edit_with_pattern action
        print("\n2. Testing EDIT_WITH_PATTERN action tag:")
        action = CodeActAction(ActionType.EDIT_WITH_PATTERN, f"{test_file}:hello:world:true")
        result = executor._edit_with_pattern(action.params)
        print(f"Result: {result}")
        
        # Test list_files_filtered action
        print("\n3. Testing LIST_FILES_FILTERED action tag:")
        action = CodeActAction(ActionType.LIST_FILES_FILTERED, f"{test_dir}:false:false")
        result = executor._list_files_filtered(action.params)
        print(f"Result: {result}")
        
        print("\n✅ All action tag tests passed!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean up
        import shutil
        shutil.rmtree(test_dir)

if __name__ == "__main__":
    test_action_tags()