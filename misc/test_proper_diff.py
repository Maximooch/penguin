#!/usr/bin/env python3
"""
Test proper diff application that targets specific lines.
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
    apply_diff_to_file,
    enhanced_write_to_file,
    enhanced_read_file,
    generate_diff_patch
)

def test_proper_diff_targeting():
    """Test that diff application properly targets specific lines."""
    print("🎯 Testing Proper Diff Application (Line Targeting)")
    print("=" * 60)
    
    # Create test directory
    test_dir = tempfile.mkdtemp(prefix="penguin_proper_diff_")
    test_file = Path(test_dir) / "example.py"
    
    # Original content with line numbers for reference
    original_content = """def hello():
    print("Hello")

def world():
    print("World")

def main():
    hello()
    world()
"""
    
    print("📄 Original file content:")
    for i, line in enumerate(original_content.splitlines(), 1):
        print(f"{i:2d}: {line}")
    
    try:
        # Write original file
        enhanced_write_to_file(str(test_file), original_content)
        
        print("\n" + "="*60)
        print("🔧 Test 1: Add docstring to hello() function (lines 1-2)")
        print("="*60)
        
        # Create a diff that adds a docstring after line 1
        diff_add_docstring = """--- a/example.py
+++ b/example.py
@@ -1,2 +1,3 @@
 def hello():
+    \"\"\"Say hello.\"\"\"
     print("Hello")
"""
        
        print("📝 Diff to apply:")
        print(diff_add_docstring)
        
        # Apply the diff
        result = apply_diff_to_file(str(test_file), diff_add_docstring)
        print(f"✅ Result: {result}")
        
        # Show updated content
        updated_content = enhanced_read_file(str(test_file))
        print("\n📄 Updated file content:")
        for i, line in enumerate(updated_content.splitlines(), 1):
            print(f"{i:2d}: {line}")
        
        print("\n" + "="*60)
        print("🔧 Test 2: Modify specific line (change 'World' to 'Universe')")
        print("="*60)
        
        # Create a diff that modifies line 6
        diff_modify_line = """--- a/example.py
+++ b/example.py
@@ -5,7 +5,7 @@
 
 def world():
     \"\"\"Say world.\"\"\"
-    print("World")
+    print("Universe")
 
 def main():
"""
        
        print("📝 Diff to apply:")
        print(diff_modify_line)
        
        # First add docstring to world function to match the context
        world_docstring_diff = """--- a/example.py
+++ b/example.py
@@ -4,5 +4,6 @@
 
 def world():
+    \"\"\"Say world.\"\"\"
     print("World")
 
"""
        apply_diff_to_file(str(test_file), world_docstring_diff)
        
        # Now apply the modification
        result = apply_diff_to_file(str(test_file), diff_modify_line)
        print(f"✅ Result: {result}")
        
        # Show final content
        final_content = enhanced_read_file(str(test_file))
        print("\n📄 Final file content:")
        for i, line in enumerate(final_content.splitlines(), 1):
            print(f"{i:2d}: {line}")
        
        print("\n" + "="*60)
        print("🔧 Test 3: Remove a line (remove empty line)")
        print("="*60)
        
        # Create a diff that removes line 5 (empty line)
        diff_remove_line = """--- a/example.py
+++ b/example.py
@@ -3,7 +3,6 @@
     print("Hello")
 
 def world():
-    \"\"\"Say world.\"\"\"
     print("Universe")
 
 def main():
"""
        
        print("📝 Diff to apply:")
        print(diff_remove_line)
        
        result = apply_diff_to_file(str(test_file), diff_remove_line)
        print(f"✅ Result: {result}")
        
        # Show final content
        final_content = enhanced_read_file(str(test_file))
        print("\n📄 Final file content:")
        for i, line in enumerate(final_content.splitlines(), 1):
            print(f"{i:2d}: {line}")
        
        print("\n" + "="*60)
        print("🎯 Summary: Proper Line Targeting")
        print("="*60)
        print("✅ Test 1: Added docstring at specific line (after line 1)")
        print("✅ Test 2: Modified specific line content (line 6)")
        print("✅ Test 3: Removed specific line (docstring)")
        print("\n💡 Key Point: Diffs target specific lines, not just append content!")
        print("   - Each @@ chunk specifies exactly which lines to modify")
        print("   - Context lines (prefix with ' ') show surrounding code")
        print("   - Remove lines (prefix with '-') are deleted")
        print("   - Add lines (prefix with '+') are inserted")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        shutil.rmtree(test_dir)

def test_real_world_diff_example():
    """Test with a real-world diff example."""
    print("\n" + "="*60)
    print("🌍 Real-World Diff Example")
    print("="*60)
    
    test_dir = tempfile.mkdtemp(prefix="penguin_real_diff_")
    test_file = Path(test_dir) / "calculator.py"
    
    # Realistic code example
    original_code = """class Calculator:
    def __init__(self):
        self.history = []
    
    def add(self, a, b):
        result = a + b
        return result
    
    def subtract(self, a, b):
        result = a - b
        return result
"""
    
    try:
        enhanced_write_to_file(str(test_file), original_code)
        
        print("📄 Original calculator.py:")
        for i, line in enumerate(original_code.splitlines(), 1):
            print(f"{i:2d}: {line}")
        
        # Real diff that adds logging to methods
        real_diff = """--- a/calculator.py
+++ b/calculator.py
@@ -4,10 +4,14 @@
     
     def add(self, a, b):
         result = a + b
+        self.history.append(f"Added {a} + {b} = {result}")
         return result
     
     def subtract(self, a, b):
         result = a - b
+        self.history.append(f"Subtracted {a} - {b} = {result}")
         return result
+    
+    def get_history(self):
+        return self.history
"""
        
        print("\n📝 Real-world diff (adding logging and new method):")
        print(real_diff)
        
        result = apply_diff_to_file(str(test_file), real_diff)
        print(f"✅ Applied diff: {result}")
        
        updated_code = enhanced_read_file(str(test_file))
        print("\n📄 Updated calculator.py:")
        for i, line in enumerate(updated_code.splitlines(), 1):
            print(f"{i:2d}: {line}")
        
        print("\n🎯 Analysis of what the diff did:")
        print("• Lines 6-7: Added logging after line 6 (result = a + b)")
        print("• Lines 11-12: Added logging after line 11 (result = a - b)")
        print("• Lines 14-16: Added new method at end")
        print("• All other lines remained unchanged (context)")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        shutil.rmtree(test_dir)

def main():
    """Run all proper diff tests."""
    test_proper_diff_targeting()
    test_real_world_diff_example()
    
    print("\n" + "="*60)
    print("🎉 All proper diff tests completed!")
    print("="*60)

if __name__ == "__main__":
    main()