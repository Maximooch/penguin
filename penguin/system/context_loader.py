"""
SimpleContextLoader for Penguin AI Assistant.

Manages loading of user-defined context files from the context folder.
Uses a configuration file to determine which files should be loaded as core context.
"""

import logging
import os
from typing import Dict, List, Optional, Any
from pathlib import Path

from penguin.config import WORKSPACE_PATH

logger = logging.getLogger(__name__)


class SimpleContextLoader:
    """
    Minimal context folder loader with basic configuration.
    
    Loads files from a context folder based on user configuration.
    Users specify 'core_files' that should always be loaded.
    Additional files can be loaded on demand.
    """
    
    def __init__(
        self, 
        context_manager,
        context_folder: str = "context"
    ):
        """
        Initialize the SimpleContextLoader.
        
        Args:
            context_manager: The context manager instance to add content to
            context_folder: Path to the context folder within the workspace
        """
        self.context_manager = context_manager
        # Use the workspace path from config with the context subfolder
        self.context_folder = os.path.join(WORKSPACE_PATH, context_folder)
        self.config_file = os.path.join(self.context_folder, "context_config.yml")
        self.core_files: List[str] = []  # List of essential files to always load
        
        # Create context folder if it doesn't exist
        if not os.path.exists(self.context_folder):
            os.makedirs(self.context_folder)
            # Create a sample config file
            self._create_sample_config()
        
        self._load_config()
        
    def _create_sample_config(self):
        """Create a sample configuration file if none exists"""
        try:
            import yaml # type: ignore
            sample_config = {
                "core_files": [
                    # Example files that will be loaded at startup
                    # "project_overview.md",
                    # "api_reference.md"
                ],
                "notes": "Add paths to files that should always be loaded as context"
            }
            
            with open(self.config_file, 'w') as f:
                yaml.dump(sample_config, f, default_flow_style=False)
                
            logger.info(f"Created sample context configuration at {self.config_file}")
        except Exception as e:
            logger.warning(f"Failed to create sample config: {e}")
    
    def _load_config(self):
        """Load core file list from config if available"""
        if os.path.exists(self.config_file):
            try:
                import yaml # type: ignore
                with open(self.config_file, 'r') as f:
                    config = yaml.safe_load(f) or {}
                self.core_files = config.get('core_files', [])
                logger.info(f"Loaded context configuration with {len(self.core_files)} core files")
            except Exception as e:
                # Fall back to empty list if config can't be loaded
                logger.warning(f"Failed to load context configuration: {e}")
                self.core_files = []
    
    def load_core_context(self) -> List[str]:
        """
        Load core context files defined by the user.
        
        Returns:
            List of successfully loaded file paths
        """
        loaded = []
        
        for file_path in self.core_files:
            full_path = os.path.join(self.context_folder, file_path)
            if os.path.exists(full_path) and os.path.isfile(full_path):
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Add to context manager - use add_context instead of add_working_memory
                    if hasattr(self.context_manager, 'add_context'):
                        self.context_manager.add_context(
                            content=content,
                            source=f"context/{file_path}"
                        )
                    elif hasattr(self.context_manager, 'add_working_memory'):
                        self.context_manager.add_working_memory(
                            content=content,
                            source=f"context/{file_path}"
                        )
                    else:
                        logger.warning(f"Context manager doesn't have add_context or add_working_memory methods")
                        
                    loaded.append(file_path)
                    logger.debug(f"Loaded core context file: {file_path}")
                except Exception as e:
                    logger.warning(f"Failed to load core context file {file_path}: {e}")
            else:
                logger.warning(f"Core context file not found: {file_path}")
        
        return loaded
    
    def load_file(self, file_path: str) -> Optional[Any]:
        """
        Load a specific file from the context folder on demand.
        
        Args:
            file_path: Relative path to the file within the context folder
            
        Returns:
            Message object if loaded successfully, None otherwise
        """
        full_path = os.path.join(self.context_folder, file_path)
        if not os.path.exists(full_path) or not os.path.isfile(full_path):
            logger.warning(f"Context file not found: {file_path}")
            return None
            
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Add to context manager
            message = self.context_manager.add_working_memory(
                content=content,
                source=f"context/{file_path}"
            )
            logger.debug(f"Loaded context file on demand: {file_path}")
            return message
        except Exception as e:
            logger.warning(f"Failed to load context file {file_path}: {e}")
            return None
    
    def list_available_files(self) -> List[Dict[str, Any]]:
        """
        List all available files in the context folder.
        
        Returns:
            List of file information dictionaries with path and metadata
        """
        available_files = []
        
        if not os.path.exists(self.context_folder):
            return available_files
            
        for root, _, files in os.walk(self.context_folder):
            for file in files:
                # Skip config file and hidden files
                if file == os.path.basename(self.config_file) or file.startswith('.'):
                    continue
                    
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, self.context_folder)
                
                # Get basic file stats
                stats = os.stat(full_path)
                
                # Categorize by file type
                file_type = "text"
                if file.endswith(('.md', '.markdown')):
                    file_type = "markdown"
                elif file.endswith(('.yml', '.yaml')):
                    file_type = "yaml"
                elif file.endswith(('.txt')):
                    file_type = "text"
                
                available_files.append({
                    'path': rel_path,
                    'size': stats.st_size,
                    'modified': stats.st_mtime,
                    'is_core': rel_path in self.core_files,
                    'type': file_type
                })
        
        return available_files