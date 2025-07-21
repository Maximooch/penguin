"""
Repository management tools for Penguin.

These tools allow Penguin to interact with GitHub repositories,
create PRs, and manage code changes.
"""

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from penguin.project.repository_manager import (
    get_penguin_repository_manager,
    get_test_repository_manager,
    RepositoryManager,
    RepositoryConfig
)

logger = logging.getLogger(__name__)

def create_penguin_improvement_pr(
    title: str,
    description: str,
    files_changed: Optional[str] = None
) -> str:
    """
    Create a pull request for improvements to the main Penguin repository.
    
    Args:
        title: Title of the improvement PR
        description: Detailed description of the improvements
        files_changed: Comma-separated list of files that were changed
        
    Returns:
        String with PR creation result
    """
    try:
        # Get repository manager
        repo_manager = get_penguin_repository_manager()
        
        # Parse files changed
        file_list = []
        if files_changed:
            file_list = [f.strip() for f in files_changed.split(",")]
        
        # Create PR
        result = asyncio.run(repo_manager.create_improvement_pr(
            title=title,
            description=description,
            file_changes=file_list
        ))
        
        if result["status"] == "created":
            return f"✅ PR created successfully: {result['pr_url']}"
        elif result["status"] == "already_exists":
            return f"ℹ️  PR already exists: {result['pr_url']}"
        else:
            return f"❌ Failed to create PR: {result['message']}"
            
    except Exception as e:
        logger.error(f"Error creating Penguin improvement PR: {e}")
        return f"❌ Error creating PR: {str(e)}"

def create_penguin_feature_pr(
    feature_name: str,
    description: str,
    implementation_notes: str = "",
    files_modified: Optional[str] = None
) -> str:
    """
    Create a pull request for a new feature in the Penguin repository.
    
    Args:
        feature_name: Name of the new feature
        description: Description of what the feature does
        implementation_notes: Additional implementation details
        files_modified: Comma-separated list of files that were modified
        
    Returns:
        String with PR creation result
    """
    try:
        repo_manager = get_penguin_repository_manager()
        
        file_list = []
        if files_modified:
            file_list = [f.strip() for f in files_modified.split(",")]
        
        result = asyncio.run(repo_manager.create_feature_pr(
            feature_name=feature_name,
            feature_description=description,
            implementation_notes=implementation_notes,
            files_modified=file_list
        ))
        
        if result["status"] == "created":
            return f"✅ Feature PR created: {result['pr_url']}"
        elif result["status"] == "already_exists":
            return f"ℹ️  Feature PR already exists: {result['pr_url']}"
        else:
            return f"❌ Failed to create feature PR: {result['message']}"
            
    except Exception as e:
        logger.error(f"Error creating Penguin feature PR: {e}")
        return f"❌ Error creating feature PR: {str(e)}"

def create_penguin_bugfix_pr(
    bug_description: str,
    fix_description: str,
    files_fixed: Optional[str] = None
) -> str:
    """
    Create a pull request for a bug fix in the Penguin repository.
    
    Args:
        bug_description: Description of the bug that was fixed
        fix_description: Description of how the bug was fixed
        files_fixed: Comma-separated list of files that were fixed
        
    Returns:
        String with PR creation result
    """
    try:
        repo_manager = get_penguin_repository_manager()
        
        file_list = []
        if files_fixed:
            file_list = [f.strip() for f in files_fixed.split(",")]
        
        result = asyncio.run(repo_manager.create_bugfix_pr(
            bug_description=bug_description,
            fix_description=fix_description,
            files_fixed=file_list
        ))
        
        if result["status"] == "created":
            return f"✅ Bug fix PR created: {result['pr_url']}"
        elif result["status"] == "already_exists":
            return f"ℹ️  Bug fix PR already exists: {result['pr_url']}"
        else:
            return f"❌ Failed to create bug fix PR: {result['message']}"
            
    except Exception as e:
        logger.error(f"Error creating Penguin bug fix PR: {e}")
        return f"❌ Error creating bug fix PR: {str(e)}"

def get_penguin_repository_status() -> str:
    """
    Get the current status of the Penguin repository.
    
    Returns:
        String with repository status information
    """
    try:
        repo_manager = get_penguin_repository_manager()
        status = repo_manager.get_repository_status()
        
        if "error" in status:
            return f"❌ Error getting repository status: {status['error']}"
        
        result = f"""
🐧 **Penguin Repository Status**

📁 **Repository:** {status['repository']}
📂 **Local Path:** {status['local_path']}
🌿 **Current Branch:** {status['current_branch']}
📝 **Changed Files:** {len(status['changed_files'])}
🔗 **GitHub Configured:** {'✅' if status['github_configured'] else '❌'}

"""
        
        if status['changed_files']:
            result += "**Modified Files:**\n"
            for file in status['changed_files']:
                result += f"- {file}\n"
        else:
            result += "**No uncommitted changes**\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Error getting repository status: {e}")
        return f"❌ Error getting repository status: {str(e)}"

def commit_and_push_changes(
    commit_message: str,
    files_to_add: Optional[str] = None
) -> str:
    """
    Commit and push changes to the current branch.
    
    Args:
        commit_message: Commit message
        files_to_add: Comma-separated list of files to add, or None for all changes
        
    Returns:
        String with commit result
    """
    try:
        repo_manager = get_penguin_repository_manager()
        git_integration = repo_manager.git_manager.git_integration
        
        # Add files
        if files_to_add:
            file_list = [f.strip() for f in files_to_add.split(",")]
            for file in file_list:
                git_integration.repo.index.add([file])
        else:
            # Add all changed files
            changed_files = git_integration.get_changed_files()
            if changed_files:
                git_integration.repo.index.add(changed_files)
        
        # Commit
        commit_hash = git_integration.commit(commit_message)
        if not commit_hash:
            return "❌ Failed to commit changes"
        
        # Push
        current_branch = git_integration.get_current_branch()
        pushed = git_integration.push_branch(current_branch)
        
        if pushed:
            return f"✅ Changes committed and pushed successfully\n📝 Commit: {commit_hash[:8]}\n🌿 Branch: {current_branch}"
        else:
            return f"⚠️  Changes committed but push failed\n📝 Commit: {commit_hash[:8]}"
            
    except Exception as e:
        logger.error(f"Error committing and pushing changes: {e}")
        return f"❌ Error committing changes: {str(e)}"

def create_and_switch_branch(branch_name: str) -> str:
    """
    Create a new branch and switch to it.
    
    Args:
        branch_name: Name of the new branch to create
        
    Returns:
        String with branch creation result
    """
    try:
        repo_manager = get_penguin_repository_manager()
        git_integration = repo_manager.git_manager.git_integration
        
        # Create and switch to branch
        success = git_integration.create_branch(branch_name)
        
        if success:
            return f"✅ Created and switched to branch: {branch_name}"
        else:
            return f"❌ Failed to create branch: {branch_name}"
            
    except Exception as e:
        logger.error(f"Error creating branch: {e}")
        return f"❌ Error creating branch: {str(e)}"

# Tool definitions for integration with Penguin's tool system
REPOSITORY_TOOLS = [
    {
        "name": "create_penguin_improvement_pr",
        "description": "Create a pull request for improvements to the main Penguin repository",
        "function": create_penguin_improvement_pr,
        "parameters": {
            "title": "Title of the improvement PR",
            "description": "Detailed description of the improvements",
            "files_changed": "Comma-separated list of files that were changed (optional)"
        }
    },
    {
        "name": "create_penguin_feature_pr", 
        "description": "Create a pull request for a new feature in the Penguin repository",
        "function": create_penguin_feature_pr,
        "parameters": {
            "feature_name": "Name of the new feature",
            "description": "Description of what the feature does",
            "implementation_notes": "Additional implementation details (optional)",
            "files_modified": "Comma-separated list of files that were modified (optional)"
        }
    },
    {
        "name": "create_penguin_bugfix_pr",
        "description": "Create a pull request for a bug fix in the Penguin repository", 
        "function": create_penguin_bugfix_pr,
        "parameters": {
            "bug_description": "Description of the bug that was fixed",
            "fix_description": "Description of how the bug was fixed",
            "files_fixed": "Comma-separated list of files that were fixed (optional)"
        }
    },
    {
        "name": "get_penguin_repository_status",
        "description": "Get the current status of the Penguin repository",
        "function": get_penguin_repository_status,
        "parameters": {}
    },
    {
        "name": "commit_and_push_changes",
        "description": "Commit and push changes to the current branch",
        "function": commit_and_push_changes,
        "parameters": {
            "commit_message": "Commit message",
            "files_to_add": "Comma-separated list of files to add, or None for all changes (optional)"
        }
    },
    {
        "name": "create_and_switch_branch",
        "description": "Create a new branch and switch to it",
        "function": create_and_switch_branch,
        "parameters": {
            "branch_name": "Name of the new branch to create"
        }
    }
]