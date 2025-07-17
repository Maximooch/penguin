"""Low-level Git Integration using GitPython.

This module provides a thin wrapper around the GitPython library for basic,
reusable Git operations. It is not aware of high-level concepts like
tasks or projects.
"""

import logging
from pathlib import Path
from typing import List, Optional, Union

from git import Repo, GitCommandError # type: ignore
from penguin.config import GITHUB_APP_ID

logger = logging.getLogger(__name__)


class GitIntegration:
    """A wrapper for core GitPython operations."""
    
    def __init__(self, workspace_path: Union[str, Path]):
        """
        Initialize the Git integration.
        
        Args:
            workspace_path: The file path to the repository's working directory.
        """
        self.workspace_path = str(workspace_path)
        self.repo = None
        
        try:
            # Try to open existing repository
            self.repo = Repo(self.workspace_path)
            logger.info(f"Opened existing Git repository at {self.workspace_path}")
        except Exception as e:
            logger.warning(f"No existing Git repo found at {workspace_path}: {e}")
            try:
                # Try to initialize a new repository
                self.repo = Repo.init(self.workspace_path)
                logger.info(f"Initialized new Git repository at {self.workspace_path}")
            except Exception as init_error:
                logger.error(f"Failed to initialize Git repo at {workspace_path}: {init_error}")
                # Don't raise - let GitManager handle the None repo
                self.repo = None

    def initialize_repo(self) -> None:
        """Initializes a new Git repository if it doesn't exist."""
        if self.repo:
            logger.info("Git repository already initialized")
            return
    
    def _configure_github_app_identity(self) -> None:
        """Configure git user identity to match GitHub App if available."""
        if not self.repo:
            return
            
        try:
            # Use GitHub App identity if configured
            if GITHUB_APP_ID:
                # Use a more explicit noreply email format for GitHub Apps
                app_email = f"penguin-agent[bot]@users.noreply.github.com"
                
                # Configure git user to match GitHub App
                config = self.repo.config_writer()
                config.set_value("user", "name", "Penguin Agent")
                config.set_value("user", "email", app_email)
                config.release()
                
                logger.info(f"Configured git identity for GitHub App: Penguin Agent <{app_email}>")
            else:
                logger.debug("No GitHub App ID configured, using existing git identity")
        except Exception as e:
            logger.warning(f"Failed to configure GitHub App identity: {e}")
            
        try:
            self.repo = Repo.init(self.workspace_path)
            logger.info(f"Initialized new Git repository at {self.workspace_path}")
        except Exception as e:
            logger.error(f"Failed to initialize Git repository: {e}")

    def get_changed_files(self) -> List[str]:
        """
        Gets a list of new or modified files.
            
        Returns:
            A list of file paths for changed files.
        """
        if not self.repo:
            logger.warning("Git repository not available - cannot get changed files")
            return []
            
        try:
            # Untracked files (new files)
            untracked_files = self.repo.untracked_files

            # Modified files (already tracked)
            modified_files = [item.a_path for item in self.repo.index.diff(None)]
            
            changed_files = list(set(untracked_files + modified_files))
            logger.debug(f"Found changed files: {changed_files}")
            return changed_files
        except Exception as e:
            logger.error(f"Error getting changed files: {e}")
            return []

    def create_branch(self, branch_name: str, start_point: str = "HEAD") -> bool:
        """
        Creates and checks out a new branch.
        
        Args:
            branch_name: The name for the new branch.
            start_point: The commit/branch to start from. Defaults to HEAD.
            
        Returns:
            True if the branch was created successfully, False otherwise.
        """
        if not self.repo:
            logger.warning("Git repository not available - cannot create branch")
            return False
            
        try:
            new_branch = self.repo.create_head(branch_name, start_point)
            new_branch.checkout()
            logger.info(f"Created and checked out new branch: {branch_name}")
            return True
        except GitCommandError as e:
            logger.error(f"Failed to create branch '{branch_name}': {e}")
            # If branch already exists, just check it out
            if "already exists" in str(e):
                try:
                    self.repo.git.checkout(branch_name)
                    logger.warning(f"Branch '{branch_name}' already existed. Checked it out.")
                    return True
                except GitCommandError as checkout_e:
                    logger.error(f"Failed to checkout existing branch '{branch_name}': {checkout_e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error creating branch '{branch_name}': {e}")
            return False

    def commit(self, message: str, add_all: bool = True) -> Optional[str]:
        """
        Commits changes to the current branch.
        
        Args:
            message: The commit message.
            add_all: If True, adds all changed files before committing.
            
        Returns:
            The commit hash if successful, otherwise None.
        """
        if not self.repo:
            logger.warning("Git repository not available - cannot commit")
            return None
            
        try:
            # Configure GitHub App identity before committing
            self._configure_github_app_identity()
            
            if add_all:
                changed_files = self.get_changed_files()
                if not changed_files:
                    logger.info("No changes to commit.")
                    return None
                self.repo.index.add(changed_files)
            
            commit = self.repo.index.commit(message)
            logger.info(f"Committed changes with message: '{message}'")
            return commit.hexsha
        except Exception as e:
            logger.error(f"Failed to commit: {e}")
            return None

    def push_branch(self, branch_name: str, remote_name: str = "origin") -> bool:
        """
        Pushes a branch to the specified remote.
        
        Args:
            branch_name: The name of the branch to push.
            remote_name: The name of the remote. Defaults to 'origin'.
            
        Returns:
            True if the push was successful, False otherwise.
        """
        if not self.repo:
            logger.warning("Git repository not available - cannot push")
            return False
            
        try:
            origin = self.repo.remote(name=remote_name)
            push_info = origin.push(refspec=f"{branch_name}:{branch_name}")
            
            # Check for errors in push info
            for info in push_info:
                if info.flags & (info.ERROR | info.REJECTED):
                    logger.error(f"Failed to push branch '{branch_name}': {info.summary}")
                    return False
            
            logger.info(f"Successfully pushed branch '{branch_name}' to '{remote_name}'.")
            return True
        except GitCommandError as e:
            logger.error(f"Failed to push branch '{branch_name}': {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error pushing branch '{branch_name}': {e}")
            return False
    
    def get_current_branch(self) -> str:
        """
        Gets the name of the current active branch.

        Returns:
            The name of the current branch.
        """
        if not self.repo:
            logger.warning("Git repository not available - cannot get current branch")
            return "unknown"
            
        try:
            return self.repo.active_branch.name
        except TypeError:
            # This happens in a detached HEAD state
            return "DETACHED"
        except Exception as e:
            logger.error(f"Could not get current branch: {e}")
            return "unknown" 