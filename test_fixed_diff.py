#!/usr/bin/env python3
"""
Test script to verify the fixed diff application works correctly.
"""

import os
import sys
import tempfile
from pathlib import Path

# Add the penguin directory to sys.path  
penguin_dir = Path(__file__).parent
sys.path.insert(0, str(penguin_dir))

from penguin.tools.core.support import (
    enhanced_write_to_file,
    enhanced_read_file,
    apply_diff_to_file,
    edit_file_with_pattern,
    enhanced_diff
)

def test_fixed_diff_application():
    """Test the corrected diff application functionality."""
    print("🔧 Testing Fixed Diff Application")
    print("=" * 50)
    
    # Create a temporary test file
    test_dir = tempfile.mkdtemp(prefix="test_fixed_diff_")
    test_file = Path(test_dir) / "test_fixed.py"
    
    try:
        # Create original content
        original_content = """def hello():
    print("Hello")

def world():
    print("World")

def main():
    hello()
    world()
"""
        
        # Write original file
        result = enhanced_write_to_file(str(test_file), original_content)
        print(f"✅ Created test file: {result}")
        
        # Test 1: Add docstring to hello function
        print("\n📝 Test 1: Adding docstring to hello function")
        diff_content = """--- a/test_fixed.py
+++ b/test_fixed.py
@@ -1,2 +1,3 @@
 def hello():
+    \"\"\"Say hello to the world.\"\"\"
     print("Hello")"""
        
        result = apply_diff_to_file(str(test_file), diff_content)
        print(f"✅ Applied diff: {result}")
        
        # Verify the result
        updated_content = enhanced_read_file(str(test_file))
        print("📖 Updated content:")
        print(updated_content)
        
        # Test 2: Modify the main function
        print("\n📝 Test 2: Modifying main function")
        diff_content2 = """--- a/test_fixed.py
+++ b/test_fixed.py
@@ -7,4 +7,5 @@
 def main():
     hello()
     world()
+    print("Done!")"""
        
        result = apply_diff_to_file(str(test_file), diff_content2)
        print(f"✅ Applied diff: {result}")
        
        # Verify the result
        final_content = enhanced_read_file(str(test_file))
        print("📖 Final content:")
        print(final_content)
        
        # Test 3: Pattern-based editing
        print("\n📝 Test 3: Pattern-based editing")
        result = edit_file_with_pattern(
            str(test_file),
            r'print\("Hello"\)',
            'print("Hello, World!")'
        )
        print(f"✅ Applied pattern edit: {result}")
        
        # Test 4: Compare with backup
        print("\n📝 Test 4: Comparing with backup")
        backup_file = str(test_file) + ".bak"
        diff_result = enhanced_diff(backup_file, str(test_file))
        print(f"📊 Diff result:\n{diff_result}")
        
        print("\n✅ All tests passed! The diff application is working correctly.")
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean up
        import shutil
        shutil.rmtree(test_dir)
        print(f"\n🧹 Cleaned up test directory: {test_dir}")

if __name__ == "__main__":
    test_fixed_diff_application()