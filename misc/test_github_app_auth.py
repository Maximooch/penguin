#!/usr/bin/env python3
"""
Test script to verify GitHub App authentication works correctly.
"""

import os
import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))

from penguin.project.git_manager import GitManager
from penguin.project.manager import ProjectManager
from penguin.config import GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY_PATH, GITHUB_APP_INSTALLATION_ID

def test_github_app_authentication():
    """Test GitHub App authentication setup."""
    print("🐧 Testing GitHub App Authentication")
    print("=" * 50)
    
    # Check environment variables
    print("Environment Variables:")
    print(f"  GITHUB_APP_ID: {'✅ Set' if GITHUB_APP_ID else '❌ Not set'}")
    print(f"  GITHUB_APP_PRIVATE_KEY_PATH: {'✅ Set' if GITHUB_APP_PRIVATE_KEY_PATH else '❌ Not set'}")
    print(f"  GITHUB_APP_INSTALLATION_ID: {'✅ Set' if GITHUB_APP_INSTALLATION_ID else '❌ Not set'}")
    
    if not all([GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY_PATH, GITHUB_APP_INSTALLATION_ID]):
        print("\n❌ GitHub App environment variables not properly configured!")
        return False
    
    # Check private key file exists
    private_key_path = Path(GITHUB_APP_PRIVATE_KEY_PATH)
    if not private_key_path.exists():
        print(f"\n❌ Private key file not found at: {private_key_path}")
        return False
    
    print(f"  Private key file: ✅ Found at {private_key_path}")
    
    # Test GitManager initialization
    print("\nTesting GitManager initialization...")
    try:
        # Create a temporary workspace for testing
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            # Initialize git repo
            import subprocess
            subprocess.run(["git", "init"], cwd=temp_dir, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=temp_dir, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=temp_dir, check=True)
            
            # Initialize project manager and git manager
            project_manager = ProjectManager(workspace_path=temp_dir)
            git_manager = GitManager(
                workspace_path=temp_dir,
                project_manager=project_manager,
                repo_owner_and_name="Maximooch/penguin-test-repo"
            )
            
            # Check if GitHub client was initialized
            if git_manager.github is None:
                print("❌ GitManager failed to initialize GitHub client")
                return False
            
            print("✅ GitManager initialized successfully")
            
            # Test GitHub API access
            print("\nTesting GitHub API access...")
            try:
                # Try to access the test repository
                repo = git_manager.github.get_repo("Maximooch/penguin-test-repo")
                print(f"✅ Successfully accessed repository: {repo.full_name}")
                
                # Get the authenticated user/app
                user = git_manager.github.get_user()
                print(f"✅ Authenticated as: {user.login}")
                
                return True
                
            except Exception as e:
                print(f"❌ GitHub API access failed: {e}")
                return False
                
    except Exception as e:
        print(f"❌ GitManager initialization failed: {e}")
        return False

if __name__ == "__main__":
    success = test_github_app_authentication()
    
    print("\n" + "=" * 50)
    if success:
        print("✅ GitHub App authentication test PASSED!")
        print("Your GitHub App is properly configured and working.")
    else:
        print("❌ GitHub App authentication test FAILED!")
        print("Please check your environment variables and private key file.")
    
    sys.exit(0 if success else 1)