#!/usr/bin/env python3
"""
Test script specifically for diff application functionality.
Tests the difference between enhanced_diff (comparison) and apply_diff (editing).
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
    enhanced_diff,
    apply_diff_to_file,
    edit_file_with_pattern,
    generate_diff_patch,
    enhanced_write_to_file,
    enhanced_read_file
)

def create_test_files():
    """Create test files for diff application."""
    test_dir = tempfile.mkdtemp(prefix="penguin_diff_test_")
    print(f"Created test directory: {test_dir}")
    
    # Original file
    original_content = """class Calculator:
    def __init__(self):
        self.result = 0
    
    def add(self, x, y):
        return x + y
    
    def subtract(self, x, y):
        return x - y
"""
    
    original_file = Path(test_dir) / "calculator.py"
    original_file.write_text(original_content)
    
    # Modified version (what we want to achieve)
    modified_content = """class Calculator:
    def __init__(self):
        self.result = 0
    
    def add(self, x, y):
        \"\"\"Add two numbers.\"\"\"
        return x + y
    
    def subtract(self, x, y):
        \"\"\"Subtract two numbers.\"\"\"
        return x - y
    
    def multiply(self, x, y):
        \"\"\"Multiply two numbers.\"\"\"
        return x * y
    
    def divide(self, x, y):
        \"\"\"Divide two numbers.\"\"\"
        if y == 0:
            raise ValueError("Cannot divide by zero")
        return x / y
"""
    
    return test_dir, original_file, original_content, modified_content

def test_enhanced_diff_vs_apply_diff():
    """Test the difference between enhanced_diff (comparison) and apply_diff (editing)."""
    print("=" * 60)
    print("🔍 Testing: enhanced_diff vs apply_diff")
    print("=" * 60)
    
    test_dir, original_file, original_content, modified_content = create_test_files()
    
    try:
        # Create a second file with the modified content
        modified_file = Path(test_dir) / "calculator_modified.py"
        modified_file.write_text(modified_content)
        
        print("\n1. ENHANCED_DIFF (Comparison Only):")
        print("   This shows what's different between two files but doesn't edit anything.")
        
        # Use enhanced_diff to compare (this doesn't edit files)
        diff_result = enhanced_diff(str(original_file), str(modified_file))
        print(diff_result)
        
        # Verify original file is unchanged
        current_content = enhanced_read_file(str(original_file))
        print(f"\n   Original file unchanged: {current_content == original_content}")
        
        print("\n" + "="*60)
        print("\n2. APPLY_DIFF (Actual File Editing):")
        print("   This takes a diff and applies it to edit the actual file.")
        
        # Generate a diff patch
        diff_patch = generate_diff_patch(original_content, modified_content, "calculator.py")
        print(f"   Generated diff patch:\n{diff_patch}")
        
        # Apply the diff to edit the original file
        apply_result = apply_diff_to_file(str(original_file), diff_patch)
        print(f"   Apply result: {apply_result}")
        
        # Verify the file was actually edited
        edited_content = enhanced_read_file(str(original_file))
        print(f"   File was actually edited: {edited_content != original_content}")
        print(f"   Content matches target: {edited_content.strip() == modified_content.strip()}")
        
    finally:
        shutil.rmtree(test_dir)

def test_edit_with_pattern():
    """Test pattern-based editing."""
    print("\n" + "="*60)
    print("🔧 Testing: edit_with_pattern")
    print("=" * 60)
    
    test_dir, original_file, original_content, _ = create_test_files()
    
    try:
        print("\n1. Original file content:")
        print(enhanced_read_file(str(original_file)))
        
        print("\n2. Adding docstrings to methods using pattern replacement:")
        
        # Add docstring to add method
        result = edit_file_with_pattern(
            str(original_file),
            r'(def add\(self, x, y\):)',
            r'\1\n        """Add two numbers."""'
        )
        print(f"   Result: {result}")
        
        # Add docstring to subtract method
        result = edit_file_with_pattern(
            str(original_file),
            r'(def subtract\(self, x, y\):)',
            r'\1\n        """Subtract two numbers."""'
        )
        print(f"   Result: {result}")
        
        print("\n3. Final file content after pattern edits:")
        print(enhanced_read_file(str(original_file)))
        
    finally:
        shutil.rmtree(test_dir)

def test_action_tag_examples():
    """Show examples of how to use the new action tags."""
    print("\n" + "="*60)
    print("🏷️  Action Tag Examples")
    print("=" * 60)
    
    examples = [
        ("enhanced_diff", "old_file.py:new_file.py:true", "Compare two files (no editing)"),
        ("apply_diff", "target_file.py:--- a/target_file.py\n+++ b/target_file.py\n@@ -1,3 +1,4 @@\n def hello():\n+    \"\"\"Say hello.\"\"\"\n     print('Hello'):true", "Apply diff to edit file"),
        ("edit_with_pattern", "config.py:debug = False:debug = True:true", "Replace pattern in file"),
    ]
    
    print("\nNow Penguin can use these action tags for file editing:")
    
    for action, params, description in examples:
        print(f"\n<!-- {description} -->")
        print(f"<{action}>{params}</{action}>")

def test_workflow_example():
    """Show a complete workflow example."""
    print("\n" + "="*60)
    print("🔄 Complete Workflow Example")
    print("=" * 60)
    
    test_dir, original_file, original_content, modified_content = create_test_files()
    
    try:
        print("\n1. Read original file:")
        content = enhanced_read_file(str(original_file))
        print(f"   Original has {len(content.splitlines())} lines")
        
        print("\n2. Add a new method using pattern replacement:")
        result = edit_file_with_pattern(
            str(original_file),
            r'(    def subtract\(self, x, y\):\n        return x - y)',
            r'\1\n\n    def multiply(self, x, y):\n        return x * y'
        )
        print(f"   Added multiply method")
        
        print("\n3. Add docstrings using multiple pattern replacements:")
        patterns = [
            (r'(def add\(self, x, y\):)', r'\1\n        """Add two numbers."""'),
            (r'(def subtract\(self, x, y\):)', r'\1\n        """Subtract two numbers."""'),
            (r'(def multiply\(self, x, y\):)', r'\1\n        """Multiply two numbers."""')
        ]
        
        for pattern, replacement in patterns:
            edit_file_with_pattern(str(original_file), pattern, replacement)
        
        print("\n4. Final result:")
        final_content = enhanced_read_file(str(original_file))
        print(f"   Final file has {len(final_content.splitlines())} lines")
        print(f"   Contains 'Add two numbers': {'Add two numbers' in final_content}")
        print(f"   Contains 'multiply': {'multiply' in final_content}")
        
        print("\n5. This workflow could be done with action tags:")
        print("   <enhanced_read>calculator.py:false</enhanced_read>")
        print("   <edit_with_pattern>calculator.py:(def add\\(self, x, y\\):):\\1\\n        \"\"\"Add two numbers.\"\"\":true</edit_with_pattern>")
        print("   <edit_with_pattern>calculator.py:(def subtract\\(self, x, y\\):):\\1\\n        \"\"\"Subtract two numbers.\"\"\":true</edit_with_pattern>")
        print("   <enhanced_read>calculator.py:true</enhanced_read>")
        
    finally:
        shutil.rmtree(test_dir)

def main():
    """Run all diff application tests."""
    print("🧪 Testing Diff Application vs Comparison")
    print("=" * 60)
    
    test_enhanced_diff_vs_apply_diff()
    test_edit_with_pattern()
    test_action_tag_examples()
    test_workflow_example()
    
    print("\n" + "="*60)
    print("✅ All diff application tests completed!")
    print("=" * 60)
    
    print("\nKey Takeaways:")
    print("• enhanced_diff: Compares files and shows differences (no editing)")
    print("• apply_diff: Applies a diff to actually edit a file") 
    print("• edit_with_pattern: Edits files using regex find/replace")
    print("• All tools create backups by default")
    print("• All tools show exact paths to prevent confusion")
    print("• Action tags support both comparison and editing workflows")

if __name__ == "__main__":
    main()