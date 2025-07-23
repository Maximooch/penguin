"""
Core tools plugin for Penguin.

This plugin contains the essential file system and basic tools that were
previously hard-coded in the ToolManager.
"""

import os
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from penguin.plugins import BasePlugin, PluginMetadata, register_tool
from penguin.tools.core.support import (
    create_folder, create_file, enhanced_write_to_file, enhanced_read_file,
    list_files_filtered, find_files_enhanced, encode_image_to_base64,
    enhanced_diff, analyze_project_structure, apply_diff_to_file, edit_file_with_pattern
)
from penguin.tools.core.lint_python import lint_python


class CoreToolsPlugin(BasePlugin):
    """Core tools plugin providing essential file system operations"""
    
    def initialize(self) -> bool:
        """Initialize the core tools plugin"""
        try:
            self.logger.info("Initializing Core Tools Plugin")
            
            # Register all core tools
            self._register_core_tools()
            
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize Core Tools Plugin: {e}")
            return False
    
    def cleanup(self) -> None:
        """Clean up core tools plugin"""
        self.logger.info("Cleaning up Core Tools Plugin")
    
    def _register_core_tools(self):
        """Register all core file system tools"""
        
        # File system tools
        self.register_tool(self._create_folder_tool())
        self.register_tool(self._create_file_tool())
        self.register_tool(self._write_to_file_tool())
        self.register_tool(self._read_file_tool())
        self.register_tool(self._list_files_tool())
        self.register_tool(self._find_file_tool())
        self.register_tool(self._encode_image_tool())
        
        # Enhanced file tools
        self.register_tool(self._enhanced_diff_tool())
        self.register_tool(self._analyze_project_tool())
        self.register_tool(self._apply_diff_tool())
        self.register_tool(self._edit_with_pattern_tool())
        
        # Development tools
        self.register_tool(self._lint_python_tool())
        self.register_tool(self._execute_command_tool())
    
    def _create_folder_tool(self):
        """Create folder tool definition"""
        from penguin.plugins import ToolDefinition, ParameterSchema
        
        return ToolDefinition(
            name="create_folder",
            description="Create a new folder/directory",
            parameters=[
                ParameterSchema(
                    name="path",
                    type="string",
                    description="Path to the folder to create",
                    required=True
                )
            ],
            handler=lambda path: create_folder(path),
            category="filesystem",
            tags=["file", "directory", "create"]
        )
    
    def _create_file_tool(self):
        """Create file tool definition"""
        from penguin.plugins import ToolDefinition, ParameterSchema
        
        return ToolDefinition(
            name="create_file",
            description="Create a new file with optional content",
            parameters=[
                ParameterSchema(
                    name="path",
                    type="string", 
                    description="Path to the file to create",
                    required=True
                ),
                ParameterSchema(
                    name="content",
                    type="string",
                    description="Initial content for the file",
                    required=False,
                    default=""
                )
            ],
            handler=lambda path, content="": create_file(path, content),
            category="filesystem",
            tags=["file", "create"]
        )
    
    def _write_to_file_tool(self):
        """Write to file tool definition"""
        from penguin.plugins import ToolDefinition, ParameterSchema
        
        return ToolDefinition(
            name="write_to_file",
            description="Write content to a file (overwrites existing content)",
            parameters=[
                ParameterSchema(
                    name="path",
                    type="string",
                    description="Path to the file to write to",
                    required=True
                ),
                ParameterSchema(
                    name="content",
                    type="string", 
                    description="Content to write to the file",
                    required=True
                )
            ],
            handler=lambda path, content: enhanced_write_to_file(path, content),
            category="filesystem",
            tags=["file", "write", "edit"]
        )
    
    def _read_file_tool(self):
        """Read file tool definition"""
        from penguin.plugins import ToolDefinition, ParameterSchema
        
        return ToolDefinition(
            name="read_file",
            description="Read the contents of a file",
            parameters=[
                ParameterSchema(
                    name="path",
                    type="string",
                    description="Path to the file to read",
                    required=True
                )
            ],
            handler=lambda path: enhanced_read_file(path),
            category="filesystem",
            tags=["file", "read"]
        )
    
    def _list_files_tool(self):
        """List files tool definition"""
        from penguin.plugins import ToolDefinition, ParameterSchema
        
        return ToolDefinition(
            name="list_files",
            description="List files in a directory with optional filtering",
            parameters=[
                ParameterSchema(
                    name="directory",
                    type="string",
                    description="Directory to list files from",
                    required=True
                ),
                ParameterSchema(
                    name="extensions",
                    type="array",
                    description="File extensions to filter by (e.g., ['.py', '.js'])",
                    required=False
                ),
                ParameterSchema(
                    name="recursive",
                    type="boolean",
                    description="Whether to list files recursively",
                    required=False,
                    default=False
                )
            ],
            handler=lambda directory, extensions=None, recursive=False: list_files_filtered(
                directory, extensions, recursive
            ),
            category="filesystem",
            tags=["file", "list", "directory"]
        )
    
    def _find_file_tool(self):
        """Find file tool definition"""
        from penguin.plugins import ToolDefinition, ParameterSchema
        
        return ToolDefinition(
            name="find_file",
            description="Find files by name pattern in a directory tree",
            parameters=[
                ParameterSchema(
                    name="pattern",
                    type="string",
                    description="File name pattern to search for",
                    required=True
                ),
                ParameterSchema(
                    name="directory",
                    type="string",
                    description="Directory to search in",
                    required=False,
                    default="."
                ),
                ParameterSchema(
                    name="case_sensitive",
                    type="boolean",
                    description="Whether the search should be case sensitive",
                    required=False,
                    default=False
                )
            ],
            handler=lambda pattern, directory=".", case_sensitive=False: find_files_enhanced(
                pattern, directory, case_sensitive
            ),
            category="filesystem",
            tags=["file", "search", "find"]
        )
    
    def _encode_image_tool(self):
        """Encode image tool definition"""
        from penguin.plugins import ToolDefinition, ParameterSchema
        
        return ToolDefinition(
            name="encode_image_to_base64",
            description="Encode an image file to base64 string",
            parameters=[
                ParameterSchema(
                    name="image_path",
                    type="string",
                    description="Path to the image file to encode",
                    required=True
                )
            ],
            handler=lambda image_path: encode_image_to_base64(image_path),
            category="media",
            tags=["image", "encode", "base64"]
        )
    
    def _enhanced_diff_tool(self):
        """Enhanced diff tool definition"""
        from penguin.plugins import ToolDefinition, ParameterSchema
        
        return ToolDefinition(
            name="enhanced_diff",
            description="Generate enhanced diff between files or content",
            parameters=[
                ParameterSchema(
                    name="original_file",
                    type="string",
                    description="Path to the original file",
                    required=False
                ),
                ParameterSchema(
                    name="modified_file",
                    type="string",
                    description="Path to the modified file", 
                    required=False
                ),
                ParameterSchema(
                    name="original_content",
                    type="string",
                    description="Original content as string",
                    required=False
                ),
                ParameterSchema(
                    name="modified_content",
                    type="string",
                    description="Modified content as string",
                    required=False
                )
            ],
            handler=lambda **kwargs: enhanced_diff(kwargs),
            category="development",
            tags=["diff", "compare", "git"]
        )
    
    def _analyze_project_tool(self):
        """Analyze project tool definition"""  
        from penguin.plugins import ToolDefinition, ParameterSchema
        
        return ToolDefinition(
            name="analyze_project",
            description="Analyze project structure and generate summary",
            parameters=[
                ParameterSchema(
                    name="directory",
                    type="string",
                    description="Directory to analyze",
                    required=False,
                    default="."
                ),
                ParameterSchema(
                    name="depth",
                    type="integer",
                    description="Maximum depth to analyze",
                    required=False,
                    default=3
                )
            ],
            handler=lambda directory=".", depth=3: analyze_project_structure({"directory": directory, "depth": depth}),
            category="development", 
            tags=["analysis", "project", "structure"]
        )
    
    def _apply_diff_tool(self):
        """Apply diff tool definition"""
        from penguin.plugins import ToolDefinition, ParameterSchema
        
        return ToolDefinition(
            name="apply_diff",
            description="Apply a diff patch to a file",
            parameters=[
                ParameterSchema(
                    name="file_path",
                    type="string",
                    description="Path to the file to apply diff to",
                    required=True
                ),
                ParameterSchema(
                    name="diff_content",
                    type="string",
                    description="Diff content to apply",
                    required=True
                )
            ],
            handler=lambda file_path, diff_content: apply_diff_to_file({"file_path": file_path, "diff_content": diff_content}),
            category="development",
            tags=["diff", "patch", "apply"]
        )
    
    def _edit_with_pattern_tool(self):
        """Edit with pattern tool definition"""
        from penguin.plugins import ToolDefinition, ParameterSchema
        
        return ToolDefinition(
            name="edit_with_pattern",
            description="Edit file using pattern matching and replacement",
            parameters=[
                ParameterSchema(
                    name="file_path",
                    type="string",
                    description="Path to the file to edit",
                    required=True
                ),
                ParameterSchema(
                    name="pattern",
                    type="string",
                    description="Pattern to search for",
                    required=True
                ),
                ParameterSchema(
                    name="replacement",
                    type="string",
                    description="Replacement text",
                    required=True
                ),
                ParameterSchema(
                    name="regex",
                    type="boolean",
                    description="Whether pattern is a regex",
                    required=False,
                    default=False
                )
            ],
            handler=lambda file_path, pattern, replacement, regex=False: edit_file_with_pattern({
                "file_path": file_path,
                "pattern": pattern,
                "replacement": replacement,
                "regex": regex
            }),
            category="development",
            tags=["edit", "pattern", "regex", "replace"]
        )
    
    def _lint_python_tool(self):
        """Python linting tool definition"""
        from penguin.plugins import ToolDefinition, ParameterSchema
        
        return ToolDefinition(
            name="lint_python",
            description="Lint Python code using flake8 or similar tools",
            parameters=[
                ParameterSchema(
                    name="target",
                    type="string",
                    description="File or directory to lint",
                    required=True
                ),
                ParameterSchema(
                    name="is_file",
                    type="boolean",
                    description="Whether target is a file (True) or directory (False)",
                    required=False,
                    default=True
                )
            ],
            handler=lambda target, is_file=True: lint_python(target, is_file),
            category="development",
            tags=["lint", "python", "code quality"]
        )
    
    def _execute_command_tool(self):
        """Execute command tool definition"""
        from penguin.plugins import ToolDefinition, ParameterSchema
        
        return ToolDefinition(
            name="execute_command",
            description="Execute a system command and return the output",
            parameters=[
                ParameterSchema(
                    name="command",
                    type="string",
                    description="Command to execute",
                    required=True
                ),
                ParameterSchema(
                    name="timeout",
                    type="integer",
                    description="Timeout in seconds",
                    required=False,
                    default=30
                ),
                ParameterSchema(
                    name="cwd",
                    type="string",
                    description="Working directory to execute command in",
                    required=False
                )
            ],
            handler=self._execute_command,
            category="system",
            tags=["command", "system", "execute"],
            permissions=["system.execute"]
        )
    
    def _execute_command(self, command: str, timeout: int = 30, cwd: Optional[str] = None) -> Dict[str, Any]:
        """Execute a system command safely"""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd
            )
            
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
                "command": command
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Command timed out after {timeout} seconds",
                "command": command
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "command": command
            }


# Plugin metadata
PLUGIN_METADATA = PluginMetadata(
    name="core_tools",
    version="1.0.0",
    description="Core file system and development tools for Penguin",
    author="Penguin Team",
    entry_point="core_tools:CoreToolsPlugin"
)


def create_plugin(config: Optional[Dict[str, Any]] = None) -> CoreToolsPlugin:
    """Factory function to create the core tools plugin"""
    return CoreToolsPlugin(PLUGIN_METADATA, config)