"""
Plugin discovery system for Penguin.

Handles automatic discovery of plugins from directories, Python packages,
and entry points.
"""

import os
import sys
import yaml
import json
import importlib
import importlib.util
from pathlib import Path
from typing import Dict, List, Optional, Set, Union, Any
import logging
import pkg_resources

from .base_plugin import BasePlugin, PluginMetadata, ToolDefinition, ActionDefinition
from .decorators import get_tools_from_module, get_actions_from_module

logger = logging.getLogger(__name__)


class PluginDiscovery:
    """
    Handles discovery of plugins from various sources.
    """
    
    def __init__(self, 
                 plugin_dirs: Optional[List[Union[str, Path]]] = None,
                 entry_point_group: str = "penguin.plugins"):
        """
        Initialize plugin discovery.
        
        Args:
            plugin_dirs: List of directories to search for plugins
            entry_point_group: Entry point group name for setuptools plugins
        """
        self.plugin_dirs = plugin_dirs or []
        self.entry_point_group = entry_point_group
        self.discovered_plugins: Dict[str, Dict[str, Any]] = {}
        
    def discover_all(self) -> Dict[str, Dict[str, Any]]:
        """
        Discover plugins from all configured sources.
        
        Returns:
            Dictionary mapping plugin names to plugin information
        """
        self.discovered_plugins.clear()
        
        # Discover from directories
        for plugin_dir in self.plugin_dirs:
            self._discover_from_directory(plugin_dir)
        
        # Discover from entry points
        self._discover_from_entry_points()
        
        # Discover from current Python path
        self._discover_from_python_path()
        
        logger.info(f"Discovered {len(self.discovered_plugins)} plugins")
        return self.discovered_plugins.copy()
    
    def _discover_from_directory(self, plugin_dir: Union[str, Path]) -> None:
        """Discover plugins from a directory"""
        plugin_path = Path(plugin_dir)
        
        if not plugin_path.exists() or not plugin_path.is_dir():
            logger.warning(f"Plugin directory does not exist: {plugin_path}")
            return
        
        logger.debug(f"Scanning plugin directory: {plugin_path}")
        
        for item in plugin_path.iterdir():
            if item.is_dir():
                self._scan_plugin_directory(item)
            elif item.suffix in ['.py']:
                self._scan_plugin_file(item)
    
    def _scan_plugin_directory(self, plugin_dir: Path) -> None:
        """Scan a single plugin directory"""
        # Look for plugin manifest files
        manifest_files = [
            plugin_dir / "plugin.yml",
            plugin_dir / "plugin.yaml", 
            plugin_dir / "plugin.json",
            plugin_dir / "pyproject.toml"
        ]
        
        manifest_file = None
        for manifest in manifest_files:
            if manifest.exists():
                manifest_file = manifest
                break
        
        if not manifest_file:
            logger.debug(f"No manifest found in {plugin_dir}, skipping")
            return
        
        try:
            plugin_info = self._parse_manifest(manifest_file)
            plugin_info['source_type'] = 'directory'
            plugin_info['source_path'] = str(plugin_dir)
            
            # Look for entry point module
            entry_point = plugin_info.get('entry_point', 'main')
            if ':' in entry_point:
                module_name, class_name = entry_point.split(':', 1)
            else:
                module_name = entry_point
                class_name = None
            
            # Try to find the module file
            module_file = plugin_dir / f"{module_name}.py"
            if module_file.exists():
                plugin_info['module_file'] = str(module_file)
                plugin_info['module_name'] = module_name
                plugin_info['class_name'] = class_name
                
                plugin_name = plugin_info.get('name')
                if plugin_name:
                    self.discovered_plugins[plugin_name] = plugin_info
                    logger.debug(f"Discovered directory plugin: {plugin_name}")
            else:
                logger.warning(f"Entry point module not found: {module_file}")
                
        except Exception as e:
            logger.error(f"Error scanning plugin directory {plugin_dir}: {e}")
    
    def _scan_plugin_file(self, plugin_file: Path) -> None:
        """Scan a single Python plugin file"""
        try:
            # Import the module to check for plugin classes or decorators
            spec = importlib.util.spec_from_file_location(plugin_file.stem, plugin_file)
            if not spec or not spec.loader:
                return
            
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Look for classes inheriting from BasePlugin
            plugin_classes = []
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and 
                    issubclass(attr, BasePlugin) and 
                    attr != BasePlugin):
                    plugin_classes.append(attr)
            
            # Look for decorated functions
            tools = get_tools_from_module(module.__name__)
            actions = get_actions_from_module(module.__name__)
            
            if plugin_classes or tools or actions:
                plugin_info = {
                    'name': plugin_file.stem,
                    'source_type': 'file',
                    'source_path': str(plugin_file),
                    'module_file': str(plugin_file),
                    'module_name': plugin_file.stem,
                    'plugin_classes': plugin_classes,
                    'tools': tools,
                    'actions': actions
                }
                
                self.discovered_plugins[plugin_file.stem] = plugin_info
                logger.debug(f"Discovered file plugin: {plugin_file.stem}")
                
        except Exception as e:
            logger.error(f"Error scanning plugin file {plugin_file}: {e}")
    
    def _discover_from_entry_points(self) -> None:
        """Discover plugins from setuptools entry points"""
        try:
            for entry_point in pkg_resources.iter_entry_points(self.entry_point_group):
                try:
                    plugin_info = {
                        'name': entry_point.name,
                        'source_type': 'entry_point',
                        'entry_point': entry_point,
                        'module_name': entry_point.module_name,
                        'class_name': getattr(entry_point, 'attrs', [None])[0] if hasattr(entry_point, 'attrs') else None
                    }
                    
                    self.discovered_plugins[entry_point.name] = plugin_info
                    logger.debug(f"Discovered entry point plugin: {entry_point.name}")
                    
                except Exception as e:
                    logger.error(f"Error processing entry point {entry_point.name}: {e}")
                    
        except Exception as e:
            logger.error(f"Error discovering entry point plugins: {e}")
    
    def _discover_from_python_path(self) -> None:
        """Discover plugins from modules in Python path with penguin_plugin attribute"""
        # This is a more advanced feature that could scan installed packages
        # for modules that declare themselves as penguin plugins
        pass
    
    def _parse_manifest(self, manifest_file: Path) -> Dict[str, Any]:
        """Parse a plugin manifest file"""
        try:
            if manifest_file.suffix in ['.yml', '.yaml']:
                with open(manifest_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
            elif manifest_file.suffix == '.json':
                with open(manifest_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            elif manifest_file.suffix == '.toml':
                try:
                    import tomli
                    with open(manifest_file, 'rb') as f:
                        toml_data = tomli.load(f)
                        data = toml_data.get('tool', {}).get('penguin', {}).get('plugin', {})
                except ImportError:
                    logger.warning("tomli not available, skipping TOML manifest")
                    return {}
            else:
                logger.warning(f"Unsupported manifest format: {manifest_file}")
                return {}
            
            return data or {}
            
        except Exception as e:
            logger.error(f"Error parsing manifest {manifest_file}: {e}")
            return {}
    
    def get_plugin_info(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific discovered plugin"""
        return self.discovered_plugins.get(plugin_name)
    
    def list_plugins(self) -> List[str]:
        """List all discovered plugin names"""
        return list(self.discovered_plugins.keys())
    
    def filter_plugins(self, 
                      source_type: Optional[str] = None,
                      has_tools: bool = False,
                      has_actions: bool = False) -> Dict[str, Dict[str, Any]]:
        """
        Filter discovered plugins by criteria.
        
        Args:
            source_type: Filter by source type ('directory', 'file', 'entry_point')
            has_tools: Only include plugins with tools
            has_actions: Only include plugins with actions
            
        Returns:
            Filtered dictionary of plugins
        """
        filtered = {}
        
        for name, info in self.discovered_plugins.items():
            # Filter by source type
            if source_type and info.get('source_type') != source_type:
                continue
            
            # Filter by tools
            if has_tools and not info.get('tools'):
                continue
                
            # Filter by actions
            if has_actions and not info.get('actions'):
                continue
            
            filtered[name] = info
        
        return filtered
    
    def create_metadata_from_info(self, plugin_info: Dict[str, Any]) -> PluginMetadata:
        """Create PluginMetadata from discovered plugin info"""
        return PluginMetadata(
            name=plugin_info.get('name', ''),
            version=plugin_info.get('version', '1.0.0'),
            description=plugin_info.get('description', ''),
            author=plugin_info.get('author', ''),
            homepage=plugin_info.get('homepage', ''),
            entry_point=plugin_info.get('entry_point', ''),
            dependencies=plugin_info.get('dependencies', []),
            permissions=plugin_info.get('permissions', []),
            config_schema=plugin_info.get('config_schema', {}),
            min_penguin_version=plugin_info.get('min_penguin_version', ''),
            max_penguin_version=plugin_info.get('max_penguin_version', '')
        )