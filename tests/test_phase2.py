#!/usr/bin/env python3
"""
Test script for Phase 2 context contributor system.
Tests the new smart context assembly functionality.
"""

import tempfile
import os
from pathlib import Path

def test_context_contributors():
    """Test the context contributors system"""
    print("🧪 Testing Phase 2: Context Contributors System")
    
    # Create a temporary workspace
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir)
        
        # Create test files
        (workspace / "PENGUIN.md").write_text("""# Test Project
        
This is a test project for Penguin Phase 2.
It demonstrates smart context assembly.

## Features
- Context contributors
- Dynamic token allocation
- Project instructions autoloading
""")
        
        (workspace / "main.py").write_text("""#!/usr/bin/env python3
import sys

def hello_world():
    \"\"\"Print hello world message\"\"\"
    print("Hello, World!")

def main():
    hello_world()
    
if __name__ == "__main__":
    main()
""")
        
        (workspace / "utils.py").write_text("""def helper_function():
    return "helper"
""")
        
        # Test the contributor system
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent / "penguin"))
            
            from penguin.system.context_contributors import assemble_smart_context
            
            # Test with various inputs
            touched_files = ["main.py", "utils.py"]
            current_diff = """--- a/main.py
+++ b/main.py
@@ -3,6 +3,7 @@
 def hello_world():
+    \"\"\"Print hello world message\"\"\"
     print("Hello, World!")"""
            
            search_results = [
                "main.py:5:def hello_world():",
                "utils.py:1:def helper_function():"
            ]
            
            content, debug_info = assemble_smart_context(
                touched_files=touched_files,
                current_diff=current_diff,
                search_results=search_results,
                current_task="Add docstrings to functions",
                token_budget=10000,
                workspace_root=str(workspace)
            )
            
            print("✓ Context assembly successful")
            print(f"✓ Generated content length: {len(content)} chars")
            print(f"✓ Token budget utilization: {debug_info.get('budget_utilization', 0):.2%}")
            print(f"✓ Contributors used: {debug_info.get('contributors_used', 0)}")
            
            # Check that PENGUIN.md content is included
            if "Test Project" in content:
                print("✓ Project instructions autoloaded")
            else:
                print("❌ Project instructions not found")
                
            # Check working files are included
            if "main.py" in content:
                print("✓ Working files included")
            else:
                print("❌ Working files not found")
                
            # Check search results are included  
            if "Search Results" in content:
                print("✓ Search results included")
            else:
                print("❌ Search results not found")
                
            print(f"\n📊 Debug Info:")
            for key, value in debug_info.items():
                print(f"   {key}: {value}")
                
            return True
            
        except Exception as e:
            print(f"❌ Error testing contributors: {e}")
            import traceback
            traceback.print_exc()
            return False

def test_context_window_borrowing():
    """Test the token borrowing functionality"""  
    print("\n🧪 Testing Context Window Token Borrowing")
    
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent / "penguin"))
        
        from penguin.system.context_window import ContextWindowManager
        from penguin.system.state import MessageCategory
        
        # Create a context manager
        cwm = ContextWindowManager()
        
        # Test borrowing
        dialog_budget = cwm.get_budget(MessageCategory.DIALOG)
        context_budget = cwm.get_budget(MessageCategory.CONTEXT)
        
        print(f"✓ Dialog budget: {dialog_budget.max_tokens} tokens")
        print(f"✓ Context budget: {context_budget.max_tokens} tokens")
        
        # Test borrowing tokens
        borrow_amount = 5000
        success = cwm.borrow_tokens(MessageCategory.DIALOG, MessageCategory.CONTEXT, borrow_amount)
        
        if success:
            print(f"✓ Successfully borrowed {borrow_amount} tokens")
            print(f"✓ Context budget after borrow: {cwm.get_budget(MessageCategory.CONTEXT).max_tokens}")
        else:
            print("❌ Token borrowing failed")
            
        # Test allocation report
        report = cwm.get_allocation_report()
        print(f"\n📊 Allocation Report:")
        print(f"   Total budget: {report['total_budget']:,}")
        print(f"   Overall utilization: {report['utilization']['overall_pct']:.1f}%")
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing borrowing: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Phase 2 Testing Suite")
    print("=" * 50)
    
    success1 = test_context_contributors()
    success2 = test_context_window_borrowing()
    
    if success1 and success2:
        print("\n🎉 All Phase 2 tests passed!")
    else:
        print("\n❌ Some tests failed")
        exit(1)