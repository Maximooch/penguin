#!/usr/bin/env python3
"""
Quick test script to verify PyGithub integration with penguin-test-repo.
This script tests the GitHub API connection and basic repository operations.
"""

import os
import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))

from github import Github, GithubException
from penguin.config import GITHUB_TOKEN, GITHUB_REPOSITORY

def test_github_connection():
    """Test basic GitHub API connection."""
    print("Testing GitHub API connection...")
    
    if not GITHUB_TOKEN:
        print("❌ GITHUB_TOKEN not found in environment")
        return False
    
    try:
        g = Github(GITHUB_TOKEN)
        user = g.get_user()
        print(f"✅ Connected to GitHub as: {user.login}")
        return True
    except GithubException as e:
        print(f"❌ GitHub API error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def test_repository_access():
    """Test access to the penguin-test-repo."""
    print("\nTesting repository access...")
    
    repo_name = "Maximooch/penguin-test-repo"
    
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(repo_name)
        print(f"✅ Successfully accessed repository: {repo.full_name}")
        print(f"   - Description: {repo.description}")
        print(f"   - Default branch: {repo.default_branch}")
        print(f"   - Open issues: {repo.open_issues_count}")
        return True
    except GithubException as e:
        print(f"❌ Could not access repository {repo_name}: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error accessing repository: {e}")
        return False

def test_pull_request_simulation():
    """Simulate creating a pull request structure (without actually creating one)."""
    print("\nTesting pull request simulation...")
    
    repo_name = "Maximooch/penguin-test-repo"
    
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(repo_name)
        
        # Get existing branches
        branches = list(repo.get_branches())
        print(f"✅ Found {len(branches)} branches:")
        for branch in branches[:5]:  # Show first 5
            print(f"   - {branch.name}")
        
        # Get existing pull requests
        prs = list(repo.get_pulls(state='all'))
        print(f"✅ Found {len(prs)} pull requests (all states)")
        
        # Test PR creation parameters (without actually creating)
        pr_title = "feat(task): Test PyGithub Integration"
        pr_body = """### ✅ Task Complete: Test PyGithub Integration

**Description:** Testing the new PyGithub integration with the penguin-test-repo

**Task ID:** `test-12345`

### 🤖 Validation Results

**Summary:** All tests passed

```
Test results: PASSED
```
"""
        
        print(f"✅ PR creation parameters prepared:")
        print(f"   - Title: {pr_title}")
        print(f"   - Base branch: {repo.default_branch}")
        print(f"   - Body length: {len(pr_body)} characters")
        
        return True
    except GithubException as e:
        print(f"❌ Error during PR simulation: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

if __name__ == "__main__":
    print("🐧 Penguin GitHub Integration Test")
    print("=" * 40)
    
    success = True
    success &= test_github_connection()
    success &= test_repository_access()
    success &= test_pull_request_simulation()
    
    print("\n" + "=" * 40)
    if success:
        print("✅ All tests passed! PyGithub integration is working correctly.")
    else:
        print("❌ Some tests failed. Check the output above.")
    
    sys.exit(0 if success else 1)