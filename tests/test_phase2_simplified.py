#!/usr/bin/env python3
"""
Test script for simplified Phase 2: Keep dynamic reallocation and project docs, disable contributors.
"""

import tempfile
import sys
from pathlib import Path

def test_project_docs_loading():
    """Test simple project docs autoloading (PENGUIN.md, AGENTS.md, README.md)"""
    print("🧪 Testing Project Documentation Auto-loading")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir)
        
        # Create test files
        (workspace / "PENGUIN.md").write_text("""# Penguin Project Instructions

This project uses Penguin for development tasks.

## Guidelines
- Follow the established patterns
- Write tests for new features
- Use semantic versioning
""")
        
        (workspace / "AGENTS.md").write_text("""# Agent Specifications

## Code Review Agent
Reviews code for quality and security issues.

## Test Runner Agent  
Runs tests and reports results.
""")
        
        (workspace / "README.md").write_text("""# Test Project

This is a sample project for testing Penguin's context loading.
""")
        
        try:
            # Test the simplified project docs loading
            sys.path.insert(0, str(Path(__file__).parent / "penguin"))
            from penguin.system.context_window import ContextWindowManager
            
            cwm = ContextWindowManager()
            content, debug_info = cwm.load_project_instructions(str(workspace))
            
            print(f"✓ Content loaded: {len(content)} characters")
            print(f"✓ Files loaded: {debug_info['loaded_files']}")
            print(f"✓ Token count: {debug_info['total_tokens']}")
            
            # Check priority loading (should load PENGUIN.md and stop, not README.md)
            if "PENGUIN.md" in debug_info['loaded_files'] and "README.md" not in debug_info['loaded_files']:
                print("✓ Priority loading works (PENGUIN.md loaded, README.md skipped)")
            elif debug_info['loaded_files']:
                print(f"✓ Files loaded: {debug_info['loaded_files']}")
            else:
                print("❌ No files loaded")
                
            return "Penguin Project Instructions" in content
            
        except Exception as e:
            print(f"❌ Error testing project docs: {e}")
            import traceback
            traceback.print_exc()
            return False

def test_dynamic_reallocation():
    """Test token borrowing between categories"""
    print("\n🧪 Testing Dynamic Token Reallocation")
    
    try:
        sys.path.insert(0, str(Path(__file__).parent / "penguin")) 
        from penguin.system.context_window import ContextWindowManager
        from penguin.system.state import MessageCategory
        
        cwm = ContextWindowManager()
        
        # Get initial budgets
        context_budget = cwm.get_budget(MessageCategory.CONTEXT)
        dialog_budget = cwm.get_budget(MessageCategory.DIALOG)
        
        initial_context_max = context_budget.max_tokens
        initial_dialog_max = dialog_budget.max_tokens
        
        print(f"✓ Initial Context budget: {initial_context_max:,}")
        print(f"✓ Initial Dialog budget: {initial_dialog_max:,}")
        
        # Test borrowing 10k tokens
        borrow_amount = 10000
        success = cwm.borrow_tokens(MessageCategory.DIALOG, MessageCategory.CONTEXT, borrow_amount)
        
        if success:
            new_context_max = cwm.get_budget(MessageCategory.CONTEXT).max_tokens
            new_dialog_max = cwm.get_budget(MessageCategory.DIALOG).max_tokens
            
            print(f"✓ Borrowed {borrow_amount:,} tokens successfully")
            print(f"✓ Context budget after: {new_context_max:,} (+{new_context_max - initial_context_max:,})")
            print(f"✓ Dialog budget after: {new_dialog_max:,} ({new_dialog_max - initial_dialog_max:+,})")
            
            # Verify the math
            context_increase = new_context_max - initial_context_max
            dialog_decrease = initial_dialog_max - new_dialog_max
            
            if context_increase == borrow_amount and dialog_decrease == borrow_amount:
                print("✓ Token borrowing math correct")
                return True
            else:
                print(f"❌ Token borrowing math incorrect: +{context_increase} vs -{dialog_decrease}")
                return False
        else:
            print("❌ Token borrowing failed")
            return False
            
    except Exception as e:
        print(f"❌ Error testing reallocation: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_contributors_disabled():
    """Verify that complex contributor system is disabled"""
    print("\n🧪 Testing Context Contributors Are Disabled")
    
    try:
        sys.path.insert(0, str(Path(__file__).parent / "penguin"))
        from penguin.system import context_contributors
        
        print(f"✓ Contributors enabled flag: {context_contributors.CONTEXT_CONTRIBUTORS_ENABLED}")
        
        # Try to call the disabled function
        content, debug_info = context_contributors.assemble_smart_context(
            touched_files=["test.py"],
            current_task="test task"
        )
        
        if debug_info.get("status") == "disabled":
            print("✓ Context contributors system properly disabled")
            return True
        else:
            print("❌ Context contributors system not disabled")  
            print(f"   Debug info: {debug_info}")
            return False
            
    except Exception as e:
        print(f"❌ Error testing disabled contributors: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Phase 2 Simplified Testing Suite")
    print("=" * 50)
    
    test1 = test_project_docs_loading()
    test2 = test_dynamic_reallocation()
    test3 = test_contributors_disabled()
    
    print(f"\n📊 Results:")
    print(f"   Project Docs Loading: {'✅' if test1 else '❌'}")  
    print(f"   Dynamic Reallocation: {'✅' if test2 else '❌'}")
    print(f"   Contributors Disabled: {'✅' if test3 else '❌'}")
    
    if test1 and test2 and test3:
        print("\n🎉 Simplified Phase 2 working correctly!")
        print("   ✅ Dynamic token borrowing preserved")
        print("   ✅ Project instructions autoloading preserved") 
        print("   ✅ Complex contributor system safely disabled")
    else:
        print("\n❌ Some functionality not working correctly")
        exit(1)