#!/usr/bin/env python3
"""
Test script for generic repository tools with penguin-test-repo.

This script tests all the generic repository management tools to ensure they work
correctly with any GitHub repository (not just Penguin-specific ones).

Usage:
    python test_generic_repo_tools.py
"""

import sys
import os
from pathlib import Path

# Add penguin to path
penguin_path = Path(__file__).parent / "penguin"
sys.path.insert(0, str(penguin_path))

from penguin.tools.repository_tools import (
    get_repository_status,
    create_and_switch_branch,
    commit_and_push_changes,
    create_improvement_pr,
    create_feature_pr,
    create_bugfix_pr
)

# Test repository details
REPO_OWNER = "Maximooch"
REPO_NAME = "penguin-test-repo"

def test_repository_status():
    """Test getting repository status."""
    print("🔍 Testing repository status...")
    try:
        result = get_repository_status(REPO_OWNER, REPO_NAME)
        print(f"✅ Repository status result:\n{result}")
        return True
    except Exception as e:
        print(f"❌ Repository status failed: {e}")
        return False

def test_create_branch():
    """Test creating and switching to a new branch."""
    print("\n🌿 Testing branch creation...")
    branch_name = f"test-generic-tools-{int(time.time())}"
    try:
        result = create_and_switch_branch(REPO_OWNER, REPO_NAME, branch_name)
        print(f"✅ Branch creation result:\n{result}")
        return True, branch_name
    except Exception as e:
        print(f"❌ Branch creation failed: {e}")
        return False, None

def test_commit_and_push():
    """Test committing and pushing changes."""
    print("\n📝 Testing commit and push...")
    try:
        # First, let's create a small test file to commit
        test_file = Path("test_generic_tools.txt")
        test_file.write_text(f"Test file created by generic repository tools test at {time.time()}")
        print(f"Created test file: {test_file}")
        
        commit_message = "Test commit from generic repository tools"
        result = commit_and_push_changes(REPO_OWNER, REPO_NAME, commit_message, str(test_file))
        print(f"✅ Commit and push result:\n{result}")
        
        # Clean up
        if test_file.exists():
            test_file.unlink()
            print(f"Cleaned up test file: {test_file}")
            
        return True
    except Exception as e:
        print(f"❌ Commit and push failed: {e}")
        return False

def test_improvement_pr():
    """Test creating an improvement PR."""
    print("\n🔧 Testing improvement PR creation...")
    try:
        title = "Test Improvement PR from Generic Tools"
        description = """
This is a test improvement PR created by the generic repository tools.

## Changes Made
- Tested generic repository tool functionality
- Verified PR creation works with any repository

## Testing Notes
- Repository: {}/{}
- Tool: create_improvement_pr
- Status: Testing generic functionality
        """.format(REPO_OWNER, REPO_NAME)
        
        result = create_improvement_pr(
            REPO_OWNER, 
            REPO_NAME, 
            title, 
            description, 
            "test_generic_tools.txt"
        )
        print(f"✅ Improvement PR result:\n{result}")
        return True
    except Exception as e:
        print(f"❌ Improvement PR failed: {e}")
        return False

def test_feature_pr():
    """Test creating a feature PR."""
    print("\n🚀 Testing feature PR creation...")
    try:
        feature_name = "Generic Repository Tool Testing"
        description = "Add comprehensive testing for generic repository management tools"
        implementation_notes = """
Implementation includes:
- Generic tool parameter handling
- Repository-agnostic functionality  
- Cross-repository compatibility testing
        """
        
        result = create_feature_pr(
            REPO_OWNER,
            REPO_NAME,
            feature_name,
            description,
            implementation_notes,
            "test_generic_repo_tools.py"
        )
        print(f"✅ Feature PR result:\n{result}")
        return True
    except Exception as e:
        print(f"❌ Feature PR failed: {e}")
        return False

def test_bugfix_pr():
    """Test creating a bugfix PR."""
    print("\n🐛 Testing bugfix PR creation...")
    try:
        bug_description = "Repository tools were hardcoded to Penguin repository only"
        fix_description = """
Fixed repository tools to work with any GitHub repository by:
- Adding repo_owner and repo_name parameters to all functions
- Updating action tag formats to include repository information
- Making RepositoryManager instantiation dynamic
        """
        
        result = create_bugfix_pr(
            REPO_OWNER,
            REPO_NAME,
            bug_description,
            fix_description,
            "penguin/tools/repository_tools.py,penguin/utils/parser.py,penguin/prompt_actions.py"
        )
        print(f"✅ Bugfix PR result:\n{result}")
        return True
    except Exception as e:
        print(f"❌ Bugfix PR failed: {e}")
        return False

def run_all_tests():
    """Run all repository tool tests."""
    print(f"🧪 Testing Generic Repository Tools with {REPO_OWNER}/{REPO_NAME}")
    print("=" * 60)
    
    results = {}
    
    # Test 1: Repository Status
    results['status'] = test_repository_status()
    
    # Test 2: Branch Creation
    results['branch'], branch_name = test_create_branch()
    
    # Test 3: Commit and Push (only if branch creation succeeded)
    if results['branch']:
        results['commit'] = test_commit_and_push()
    else:
        results['commit'] = False
        print("\n⚠️  Skipping commit test due to branch creation failure")
    
    # Test 4: Improvement PR
    results['improvement_pr'] = test_improvement_pr()
    
    # Test 5: Feature PR
    results['feature_pr'] = test_feature_pr()
    
    # Test 6: Bugfix PR
    results['bugfix_pr'] = test_bugfix_pr()
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 TEST SUMMARY")
    print("=" * 60)
    
    total_tests = len(results)
    passed_tests = sum(results.values())
    
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{test_name.replace('_', ' ').title():<20} {status}")
    
    print("-" * 60)
    print(f"Total: {passed_tests}/{total_tests} tests passed")
    
    if passed_tests == total_tests:
        print("🎉 All tests passed! Generic repository tools are working correctly.")
        return True
    else:
        print("⚠️  Some tests failed. Check the output above for details.")
        return False

if __name__ == "__main__":
    import time
    
    print("🐧 Penguin Generic Repository Tools Test Suite")
    print(f"Target Repository: https://github.com/{REPO_OWNER}/{REPO_NAME}")
    print()
    
    try:
        success = run_all_tests()
        exit_code = 0 if success else 1
        
        print(f"\n🏁 Test suite completed with exit code: {exit_code}")
        sys.exit(exit_code)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Test suite interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n💥 Test suite crashed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)