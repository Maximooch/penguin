"""
Repository Manager for working with any GitHub repository.

This module provides a high-level interface for Penguin to interact with
GitHub repositories, including the main Penguin repository.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass

from .git_manager import GitManager
from .manager import ProjectManager
from .models import Task, TaskStatus

logger = logging.getLogger(__name__)

@dataclass
class RepositoryConfig:
    """Configuration for a repository."""
    name: str
    owner: str
    local_path: Path
    default_branch: str = "main"
    
    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"
    
    @property
    def url(self) -> str:
        return f"https://github.com/{self.full_name}"

class RepositoryManager:
    """High-level manager for repository operations."""
    
    def __init__(self, config: RepositoryConfig):
        self.config = config
        self.local_path = Path(config.local_path)
        
        # Initialize project manager for this repository
        self.project_manager = ProjectManager(workspace_path=self.local_path)
        
        # Initialize git manager
        self.git_manager = GitManager(
            workspace_path=self.local_path,
            project_manager=self.project_manager,
            repo_owner_and_name=config.full_name
        )
    
    async def create_improvement_pr(
        self, 
        title: str, 
        description: str, 
        file_changes: List[str],
        branch_prefix: str = "feature/penguin-improvement"
    ) -> Dict[str, Any]:
        """
        Create a PR for repository improvements.
        
        Args:
            title: PR title
            description: PR description  
            file_changes: List of files that were changed
            branch_prefix: Prefix for branch name
            
        Returns:
            Dict with PR creation result
        """
        
        # Create a task object for this improvement
        task_id = f"improvement-{int(time.time())}"
        now = datetime.now(timezone.utc).isoformat()
        task = Task(
            id=task_id,
            title=title,
            description=description,
            status=TaskStatus.COMPLETED,  # Mark as completed since changes are already made
            created_at=now,
            updated_at=now,
            project_id="repository-improvements"
        )
        
        # Create validation results
        validation_results = {
            "validated": True,
            "summary": "Repository improvement validated",
            "details": f"Modified files: {', '.join(file_changes)}"
        }
        
        # Create PR using GitManager
        result = await self.git_manager.create_pr_for_task(task, validation_results)
        
        # Add additional context to result
        result["repository"] = self.config.full_name
        result["file_changes"] = file_changes
        result["improvement_type"] = "automated"
        
        return result
    
    async def create_feature_pr(
        self,
        feature_name: str,
        feature_description: str,
        implementation_notes: str = "",
        files_modified: List[str] = None
    ) -> Dict[str, Any]:
        """
        Create a PR for a new feature.
        
        Args:
            feature_name: Name of the feature
            feature_description: Description of what the feature does
            implementation_notes: Additional implementation details
            files_modified: List of files that were modified
            
        Returns:
            Dict with PR creation result
        """
        
        task_id = f"feature-{int(time.time())}"
        
        # Create detailed description
        full_description = f"""
## Feature: {feature_name}

{feature_description}

### Implementation Notes
{implementation_notes}

### Files Modified
{chr(10).join(f"- {file}" for file in (files_modified or []))}

---
*This PR was created automatically by Penguin Agent.*
"""
        
        now = datetime.now(timezone.utc).isoformat()
        task = Task(
            id=task_id,
            title=f"Add {feature_name} feature",
            description=full_description,
            status=TaskStatus.COMPLETED,
            created_at=now,
            updated_at=now,
            project_id="feature-development"
        )
        
        validation_results = {
            "validated": True,
            "summary": "Feature implementation completed",
            "details": f"Feature: {feature_name}\nFiles: {len(files_modified or [])}"
        }
        
        result = await self.git_manager.create_pr_for_task(task, validation_results)
        result["feature_name"] = feature_name
        result["repository"] = self.config.full_name
        
        return result
    
    async def create_bugfix_pr(
        self,
        bug_description: str,
        fix_description: str,
        files_fixed: List[str] = None
    ) -> Dict[str, Any]:
        """
        Create a PR for a bug fix.
        
        Args:
            bug_description: Description of the bug
            fix_description: Description of the fix
            files_fixed: List of files that were fixed
            
        Returns:
            Dict with PR creation result
        """
        
        task_id = f"bugfix-{int(time.time())}"
        
        full_description = f"""
## Bug Fix

**Bug Description:**
{bug_description}

**Fix Description:**
{fix_description}

### Files Fixed
{chr(10).join(f"- {file}" for file in (files_fixed or []))}

---
*This PR was created automatically by Penguin Agent.*
"""
        
        now = datetime.now(timezone.utc).isoformat()
        task = Task(
            id=task_id,
            title=f"Fix: {bug_description[:50]}...",
            description=full_description,
            status=TaskStatus.COMPLETED,
            created_at=now,
            updated_at=now,
            project_id="bug-fixes"
        )
        
        validation_results = {
            "validated": True,
            "summary": "Bug fix implemented",
            "details": f"Fixed: {bug_description[:100]}"
        }
        
        result = await self.git_manager.create_pr_for_task(task, validation_results)
        result["bug_type"] = "fix"
        result["repository"] = self.config.full_name
        
        return result
    
    def get_repository_status(self) -> Dict[str, Any]:
        """Get current repository status."""
        try:
            # Get git status
            changed_files = self.git_manager.git_integration.get_changed_files()
            current_branch = self.git_manager.git_integration.get_current_branch()
            
            return {
                "repository": self.config.full_name,
                "local_path": str(self.local_path),
                "current_branch": current_branch,
                "changed_files": changed_files,
                "has_changes": len(changed_files) > 0,
                "github_configured": self.git_manager.github is not None
            }
        except Exception as e:
            logger.error(f"Error getting repository status: {e}")
            return {
                "repository": self.config.full_name,
                "error": str(e)
            }

# Pre-configured repository managers
PENGUIN_REPO_CONFIG = RepositoryConfig(
    name="penguin",
    owner="Maximooch", 
    local_path=Path("/Users/maximusputnam/Documents/code/Penguin/penguin"),
    default_branch="main"
)

def get_penguin_repository_manager() -> RepositoryManager:
    """Get a repository manager for the main Penguin repository."""
    return RepositoryManager(PENGUIN_REPO_CONFIG)

def get_test_repository_manager() -> RepositoryManager:
    """Get a repository manager for the test repository."""
    test_config = RepositoryConfig(
        name="penguin-test-repo",
        owner="Maximooch",
        local_path=Path("/tmp/penguin-test-repo"),  # Would need to be cloned
        default_branch="main"
    )
    return RepositoryManager(test_config)