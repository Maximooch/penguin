"""
Generic repository management tools.

These tools allow interaction with any GitHub repository,
create PRs, and manage code changes.
"""

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from penguin.project.repository_checkout import validate_checkout
from penguin.system.execution_context import get_current_execution_context_dict
from penguin.system.tool_environment import hosted_tools_enabled
from penguin.project.repository_checkout import RepositoryError

from penguin.project.repository_manager import (
    RepositoryManager,
    RepositoryConfig
)

logger = logging.getLogger(__name__)

def _get_repository_manager(
    repo_owner: str, repo_name: str, directory: str | None = None
) -> RepositoryManager:
    """Resolve the execution checkout without changing process-wide CWD."""
    context = get_current_execution_context_dict()
    selected = directory or context.get("directory") or context.get("project_root")
    if not selected and hosted_tools_enabled():
        raise RepositoryError("Hosted repository tools require an execution checkout.")
    local_path = validate_checkout(Path(selected or Path.cwd()), f"{repo_owner}/{repo_name}")
    return RepositoryManager(RepositoryConfig(
        owner=repo_owner, name=repo_name, local_path=local_path, default_branch=None
    ))

def create_improvement_pr(
    repo_owner: str,
    repo_name: str,
    title: str,
    description: str,
    files_changed: Optional[str] = None,
    *, directory: str | None = None
) -> str:
    """
    Create a pull request for improvements to a GitHub repository.
    
    Args:
        repo_owner: GitHub repository owner
        repo_name: GitHub repository name
        title: Title of the improvement PR
        description: Detailed description of the improvements
        files_changed: Comma-separated list of files that were changed
        
    Returns:
        String with PR creation result
    """
    try:
        # Get repository manager
        repo_manager = _get_repository_manager(repo_owner, repo_name, directory)
        
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
        logger.error(f"Error creating improvement PR for {repo_owner}/{repo_name}: {e}")
        return f"❌ Error creating PR: {str(e)}"

def create_feature_pr(
    repo_owner: str,
    repo_name: str,
    feature_name: str,
    description: str,
    implementation_notes: str = "",
    files_modified: Optional[str] = None,
    *, directory: str | None = None
) -> str:
    """
    Create a pull request for a new feature in a GitHub repository.
    
    Args:
        repo_owner: GitHub repository owner
        repo_name: GitHub repository name
        feature_name: Name of the new feature
        description: Description of what the feature does
        implementation_notes: Additional implementation details
        files_modified: Comma-separated list of files that were modified
        
    Returns:
        String with PR creation result
    """
    try:
        repo_manager = _get_repository_manager(repo_owner, repo_name, directory)
        
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
        logger.error(f"Error creating feature PR for {repo_owner}/{repo_name}: {e}")
        return f"❌ Error creating feature PR: {str(e)}"

def create_bugfix_pr(
    repo_owner: str,
    repo_name: str,
    bug_description: str,
    fix_description: str,
    files_fixed: Optional[str] = None,
    *, directory: str | None = None
) -> str:
    """
    Create a pull request for a bug fix in a GitHub repository.
    
    Args:
        repo_owner: GitHub repository owner
        repo_name: GitHub repository name
        bug_description: Description of the bug that was fixed
        fix_description: Description of how the bug was fixed
        files_fixed: Comma-separated list of files that were fixed
        
    Returns:
        String with PR creation result
    """
    try:
        repo_manager = _get_repository_manager(repo_owner, repo_name, directory)
        
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
        logger.error(f"Error creating bug fix PR for {repo_owner}/{repo_name}: {e}")
        return f"❌ Error creating bug fix PR: {str(e)}"

def get_repository_status(
    repo_owner: str,
    repo_name: str,
    *, directory: str | None = None
) -> str:
    """
    Get the current status of a GitHub repository.
    
    Args:
        repo_owner: GitHub repository owner
        repo_name: GitHub repository name
    
    Returns:
        String with repository status information
    """
    try:
        repo_manager = _get_repository_manager(repo_owner, repo_name, directory)
        status = repo_manager.get_repository_status()
        
        if "error" in status:
            return f"❌ Error getting repository status: {status['error']}"
        
        result = f"""
📁 **Repository Status: {repo_owner}/{repo_name}**

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
    repo_owner: str,
    repo_name: str,
    commit_message: str,
    files_to_add: Optional[str] = None,
    *, directory: str | None = None
) -> str:
    """
    Commit and push changes to the current branch of a GitHub repository.
    
    Args:
        repo_owner: GitHub repository owner
        repo_name: GitHub repository name
        commit_message: Commit message
        files_to_add: Comma-separated list of files to add, or None for all changes
        
    Returns:
        String with commit result
    """
    try:
        repo_manager = _get_repository_manager(repo_owner, repo_name, directory)
        git_integration = repo_manager.git_manager.git_integration
        
        file_list = [f.strip() for f in files_to_add.split(",")] if files_to_add else None
        commit_hash = git_integration.commit(commit_message, files=file_list)
        if not commit_hash:
            commit_hash = git_integration.run("rev-parse", "HEAD")

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

def create_and_switch_branch(
    repo_owner: str,
    repo_name: str,
    branch_name: str,
    *, directory: str | None = None
) -> str:
    """
    Create a new branch and switch to it in a GitHub repository.
    
    Args:
        repo_owner: GitHub repository owner
        repo_name: GitHub repository name
        branch_name: Name of the new branch to create
        
    Returns:
        String with branch creation result
    """
    try:
        repo_manager = _get_repository_manager(repo_owner, repo_name, directory)
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
        "name": "create_improvement_pr",
        "description": "Create a pull request for improvements to a GitHub repository",
        "function": create_improvement_pr,
        "parameters": {
            "repo_owner": "GitHub repository owner",
            "repo_name": "GitHub repository name",
            "title": "Title of the improvement PR",
            "description": "Detailed description of the improvements",
            "files_changed": "Comma-separated list of files that were changed (optional)"
        }
    },
    {
        "name": "create_feature_pr", 
        "description": "Create a pull request for a new feature in a GitHub repository",
        "function": create_feature_pr,
        "parameters": {
            "repo_owner": "GitHub repository owner",
            "repo_name": "GitHub repository name",
            "feature_name": "Name of the new feature",
            "description": "Description of what the feature does",
            "implementation_notes": "Additional implementation details (optional)",
            "files_modified": "Comma-separated list of files that were modified (optional)"
        }
    },
    {
        "name": "create_bugfix_pr",
        "description": "Create a pull request for a bug fix in a GitHub repository", 
        "function": create_bugfix_pr,
        "parameters": {
            "repo_owner": "GitHub repository owner",
            "repo_name": "GitHub repository name",
            "bug_description": "Description of the bug that was fixed",
            "fix_description": "Description of how the bug was fixed",
            "files_fixed": "Comma-separated list of files that were fixed (optional)"
        }
    },
    {
        "name": "get_repository_status",
        "description": "Get the current status of a GitHub repository",
        "function": get_repository_status,
        "parameters": {
            "repo_owner": "GitHub repository owner",
            "repo_name": "GitHub repository name"
        }
    },
    {
        "name": "commit_and_push_changes",
        "description": "Commit and push changes to the current branch of a repository",
        "function": commit_and_push_changes,
        "parameters": {
            "repo_owner": "GitHub repository owner",
            "repo_name": "GitHub repository name",
            "commit_message": "Commit message",
            "files_to_add": "Comma-separated list of files to add, or None for all changes (optional)"
        }
    },
    {
        "name": "create_and_switch_branch",
        "description": "Create a new branch and switch to it in a repository",
        "function": create_and_switch_branch,
        "parameters": {
            "repo_owner": "GitHub repository owner",
            "repo_name": "GitHub repository name",
            "branch_name": "Name of the new branch to create"
        }
    }
]
