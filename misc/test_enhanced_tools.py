#!/usr/bin/env python3
"""
Test script for enhanced tools integration.
Tests both function call interface and action tag interface.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

# Add the penguin directory to sys.path
penguin_dir = Path(__file__).parent / "penguin"
sys.path.insert(0, str(penguin_dir))

from penguin.tools.core.support import (
    list_files_filtered,
    find_files_enhanced,
    enhanced_diff,
    analyze_project_structure,
    enhanced_read_file,
    enhanced_write_to_file
)

def create_test_workspace():
    """Create a temporary test workspace with sample files."""
    test_dir = tempfile.mkdtemp(prefix="penguin_test_")
    print(f"Created test workspace: {test_dir}")
    
    # Create some sample files
    (Path(test_dir) / "src").mkdir()
    (Path(test_dir) / "tests").mkdir()
    (Path(test_dir) / ".git").mkdir()  # Should be filtered out
    (Path(test_dir) / "__pycache__").mkdir()  # Should be filtered out
    
    # Python files
    (Path(test_dir) / "src" / "main.py").write_text("""
import os
import sys
from pathlib import Path

class Calculator:
    def __init__(self):
        self.result = 0
    
    def add(self, x, y):
        return x + y
    
    def subtract(self, x, y):
        return x - y

def main():
    calc = Calculator()
    print(calc.add(5, 3))

if __name__ == "__main__":
    main()
""")
    
    (Path(test_dir) / "src" / "utils.py").write_text("""
import json
import logging

def load_config(path):
    with open(path, 'r') as f:
        return json.load(f)

def setup_logging():
    logging.basicConfig(level=logging.INFO)
""")
    
    (Path(test_dir) / "tests" / "test_main.py").write_text("""
import unittest
from src.main import Calculator

class TestCalculator(unittest.TestCase):
    def setUp(self):
        self.calc = Calculator()
    
    def test_add(self):
        self.assertEqual(self.calc.add(2, 3), 5)
    
    def test_subtract(self):
        self.assertEqual(self.calc.subtract(5, 3), 2)

if __name__ == "__main__":
    unittest.main()
""")
    
    # Config files
    (Path(test_dir) / "config.json").write_text("""
{
    "app_name": "TestApp",
    "version": "1.0.0",
    "debug": true
}
""")
    
    (Path(test_dir) / "README.md").write_text("""
# Test Project

This is a test project for enhanced tools.

## Features
- Calculator functionality
- JSON configuration
- Unit tests
""")
    
    return test_dir

def test_list_files_filtered(test_dir):
    """Test enhanced file listing."""
    print("\n=== Testing list_files_filtered ===")
    
    # Basic listing
    result = list_files_filtered(test_dir)
    print("Basic listing:")
    print(result)
    
    # Grouped by type
    result = list_files_filtered(test_dir, group_by_type=True)
    print("\nGrouped by type:")
    print(result)
    
    # Show hidden files
    result = list_files_filtered(test_dir, show_hidden=True)
    print("\nWith hidden files:")
    print(result)

def test_find_files_enhanced(test_dir):
    """Test enhanced file finding."""
    print("\n=== Testing find_files_enhanced ===")
    
    # Find Python files
    result = find_files_enhanced("*.py", test_dir)
    print("Find *.py files:")
    print(result)
    
    # Find specific file
    result = find_files_enhanced("main.py", test_dir)
    print("\nFind main.py:")
    print(result)
    
    # Find only directories
    result = find_files_enhanced("*", test_dir, file_type="directory")
    print("\nFind directories:")
    print(result)

def test_enhanced_read_file(test_dir):
    """Test enhanced file reading."""
    print("\n=== Testing enhanced_read_file ===")
    
    main_file = Path(test_dir) / "src" / "main.py"
    
    # Basic read
    result = enhanced_read_file(str(main_file))
    print("Basic read:")
    print(result[:200] + "..." if len(result) > 200 else result)
    
    # Read with line numbers
    result = enhanced_read_file(str(main_file), show_line_numbers=True, max_lines=10)
    print("\nWith line numbers (first 10 lines):")
    print(result)

def test_enhanced_write_to_file(test_dir):
    """Test enhanced file writing."""
    print("\n=== Testing enhanced_write_to_file ===")
    
    test_file = Path(test_dir) / "test_write.py"
    
    # Write new file
    content = '''def hello_world():
    print("Hello, World!")
    
if __name__ == "__main__":
    hello_world()
'''
    result = enhanced_write_to_file(str(test_file), content)
    print("Write new file:")
    print(result)
    
    # Modify existing file
    modified_content = '''def hello_world():
    print("Hello, Enhanced World!")
    print("This is a modification!")
    
if __name__ == "__main__":
    hello_world()
'''
    result = enhanced_write_to_file(str(test_file), modified_content)
    print("\nModify existing file:")
    print(result)

def test_enhanced_diff(test_dir):
    """Test enhanced diff functionality."""
    print("\n=== Testing enhanced_diff ===")
    
    # Create two versions of a file
    file1 = Path(test_dir) / "version1.py"
    file2 = Path(test_dir) / "version2.py"
    
    file1.write_text('''class Calculator:
    def add(self, x, y):
        return x + y
    
    def subtract(self, x, y):
        return x - y
''')
    
    file2.write_text('''class Calculator:
    def add(self, x, y):
        return x + y
    
    def subtract(self, x, y):
        return x - y
    
    def multiply(self, x, y):
        return x * y
    
    def divide(self, x, y):
        if y == 0:
            raise ValueError("Cannot divide by zero")
        return x / y
''')
    
    result = enhanced_diff(str(file1), str(file2))
    print("Diff with semantic analysis:")
    print(result)

def test_analyze_project_structure(test_dir):
    """Test project structure analysis."""
    print("\n=== Testing analyze_project_structure ===")
    
    result = analyze_project_structure(test_dir)
    print("Project structure analysis:")
    print(result)

def test_action_tags_simulation():
    """Simulate action tag parsing and execution."""
    print("\n=== Testing Action Tag Simulation ===")
    
    # This would normally be handled by the parser, but we'll simulate it
    from penguin.utils.parser import ActionType, CodeActAction
    
    # Simulate action tag parsing
    action_examples = [
        ("list_files_filtered", ".:true:false"),
        ("find_files_enhanced", "*.py:.:false:file"),
        ("enhanced_read", "README.md:true:20"),
        ("analyze_project", ".:false")
    ]
    
    print("Action tag examples that would be parsed:")
    for action_name, params in action_examples:
        print(f"<{action_name}>{params}</{action_name}>")
    
    print("\nThese would be converted to:")
    for action_name, params in action_examples:
        try:
            action_type = ActionType[action_name.upper()]
            action = CodeActAction(action_type, params)
            print(f"Action: {action.action_type.value}, Params: {action.params}")
        except KeyError:
            print(f"Action type {action_name} not found in enum")

def main():
    """Run all tests."""
    print("🧪 Testing Enhanced Tools Integration")
    print("=" * 50)
    
    # Create test workspace
    test_dir = create_test_workspace()
    
    try:
        # Test all enhanced tools
        test_list_files_filtered(test_dir)
        test_find_files_enhanced(test_dir)
        test_enhanced_read_file(test_dir)
        test_enhanced_write_to_file(test_dir)
        test_enhanced_diff(test_dir)
        test_analyze_project_structure(test_dir)
        test_action_tags_simulation()
        
        print("\n✅ All tests completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Clean up
        print(f"\n🧹 Cleaning up test workspace: {test_dir}")
        shutil.rmtree(test_dir)

if __name__ == "__main__":
    main()