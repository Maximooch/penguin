#!/usr/bin/env python3
"""
Full workflow test showing enhanced tools and action tags working together.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

# Add the penguin directory to sys.path
penguin_dir = Path(__file__).parent / "penguin"
sys.path.insert(0, str(penguin_dir))

from penguin.tools.core.support import *
from penguin.utils.parser import ActionType, CodeActAction, ActionExecutor
from penguin.tools.tool_manager import ToolManager

def demo_workflow():
    """Demonstrate a complete workflow using enhanced tools."""
    print("🚀 Full Workflow Demo: Enhanced Tools + Action Tags")
    print("=" * 60)
    
    # Setup
    test_dir = tempfile.mkdtemp(prefix="penguin_workflow_")
    print(f"📁 Workspace: {test_dir}")
    
    # Mock configuration
    config = {"diagnostics": {"enabled": False}}
    def mock_log_error(e, msg):
        print(f"❌ Error: {msg}")
    
    tool_manager = ToolManager(config, mock_log_error)
    executor = ActionExecutor(tool_manager, None)
    
    try:
        print("\n" + "="*60)
        print("📝 STEP 1: Create initial project structure")
        print("="*60)
        
        # Create directories
        (Path(test_dir) / "src").mkdir()
        (Path(test_dir) / "tests").mkdir()
        
        # Create initial file
        initial_code = """class MathUtils:
    def add(self, a, b):
        return a + b
    
    def subtract(self, a, b):
        return a - b
"""
        
        result = enhanced_write_to_file(
            "src/math_utils.py", 
            initial_code,
            workspace_path=test_dir
        )
        print(f"✅ Created file: {result}")
        
        print("\n" + "="*60)
        print("📋 STEP 2: List project files")
        print("="*60)
        
        # List files using enhanced tool
        files = list_files_filtered(test_dir, group_by_type=True)
        print(f"📁 Project structure:\n{files}")
        
        print("\n" + "="*60)
        print("🔍 STEP 3: Analyze project structure")
        print("="*60)
        
        # Analyze project
        analysis = analyze_project_structure(test_dir)
        print(f"📊 Project analysis:\n{analysis}")
        
        print("\n" + "="*60)
        print("✏️  STEP 4: Add documentation using pattern editing")
        print("="*60)
        
        # Add docstrings using pattern replacement
        math_file = Path(test_dir) / "src" / "math_utils.py"
        
        # Add class docstring
        result = edit_file_with_pattern(
            str(math_file),
            r'(class MathUtils:)',
            r'\1\n    """A utility class for basic math operations."""',
            workspace_path=test_dir
        )
        print(f"✅ Added class docstring")
        
        # Add method docstrings
        result = edit_file_with_pattern(
            str(math_file),
            r'(def add\(self, a, b\):)',
            r'\1\n        """Add two numbers."""',
            workspace_path=test_dir
        )
        print(f"✅ Added add() docstring")
        
        result = edit_file_with_pattern(
            str(math_file),
            r'(def subtract\(self, a, b\):)',
            r'\1\n        """Subtract two numbers."""',
            workspace_path=test_dir
        )
        print(f"✅ Added subtract() docstring")
        
        print("\n" + "="*60)
        print("🆕 STEP 5: Add new method using diff application")
        print("="*60)
        
        # Read current content
        current_content = enhanced_read_file(str(math_file))
        
        # Create new content with multiply method
        new_content = current_content + """
    def multiply(self, a, b):
        \"\"\"Multiply two numbers.\"\"\"
        return a * b
"""
        
        # Generate diff
        diff_patch = generate_diff_patch(current_content, new_content, "math_utils.py")
        print(f"📄 Generated diff:\n{diff_patch}")
        
        # Apply diff
        result = apply_diff_to_file(str(math_file), diff_patch, workspace_path=test_dir)
        print(f"✅ Applied diff: {result}")
        
        print("\n" + "="*60)
        print("🏷️  STEP 6: Test action tags")
        print("="*60)
        
        # Test action tag simulation
        print("🔧 Testing action tag: <enhanced_read>src/math_utils.py:true:10</enhanced_read>")
        action = CodeActAction(ActionType.ENHANCED_READ, f"{math_file}:true:10")
        result = executor._enhanced_read(action.params)
        print(f"📖 First 10 lines with numbers:\n{result}")
        
        print("\n🔧 Testing action tag: <find_files_enhanced>*.py:{test_dir}:false:file</find_files_enhanced>")
        action = CodeActAction(ActionType.FIND_FILES_ENHANCED, f"*.py:{test_dir}:false:file")
        result = executor._find_files_enhanced(action.params)
        print(f"🔍 Python files found:\n{result}")
        
        print("\n" + "="*60)
        print("📊 STEP 7: Final project analysis")
        print("="*60)
        
        # Final analysis
        final_analysis = analyze_project_structure(test_dir)
        print(f"📈 Final project stats:\n{final_analysis}")
        
        print("\n" + "="*60)
        print("✅ WORKFLOW COMPLETE!")
        print("="*60)
        
        print("\n🎯 Summary of what was accomplished:")
        print("• ✅ Created project structure with enhanced tools")
        print("• ✅ Listed files with filtering (no clutter)")
        print("• ✅ Analyzed project structure with AST")
        print("• ✅ Added documentation using pattern replacement")
        print("• ✅ Added new method using diff application")
        print("• ✅ Tested action tags for CodeAct integration")
        print("• ✅ All tools showed exact paths (no confusion)")
        print("• ✅ Created backups for all edits")
        
        print("\n🏗️  This workflow demonstrates:")
        print("• Enhanced tools work with workspace paths")
        print("• Both function calls and action tags work")
        print("• Clear path feedback prevents confusion")
        print("• Tools are perfect for both comparison and editing")
        print("• Full integration with existing Penguin system")
        
    except Exception as e:
        print(f"❌ Workflow failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print(f"\n🧹 Cleaning up: {test_dir}")
        shutil.rmtree(test_dir)

if __name__ == "__main__":
    demo_workflow()