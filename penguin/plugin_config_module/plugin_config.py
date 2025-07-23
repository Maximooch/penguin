"""
Plugin configuration management for Penguin.

This module provides configuration support for the plugin system,
including plugin-specific settings and global plugin management options.
"""

import os
import json
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class PluginSettings:
    """Settings for individual plugins"""
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)
    auto_load: bool = True
    priority: int = 0  # Loading priority (higher = loaded first)
    dependencies: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)


@dataclass
class PluginSystemConfig:
    """Configuration for the plugin system"""
    
    # Plugin discovery settings
    plugin_directories: List[str] = field(default_factory=lambda: [
        "~/.penguin/plugins",
        "./plugins",
        "{project_root}/plugins"
    ])
    
    # Auto-discovery settings
    auto_discover: bool = True
    discover_entry_points: bool = True
    entry_point_group: str = "penguin.plugins"
    
    # Loading settings
    parallel_loading: bool = True
    max_load_workers: int = 4
    load_timeout: int = 30  # seconds
    
    # Plugin management
    disabled_plugins: List[str] = field(default_factory=list)
    plugin_settings: Dict[str, PluginSettings] = field(default_factory=dict)
    
    # Security settings
    allow_system_plugins: bool = True
    allow_user_plugins: bool = True
    require_signatures: bool = False
    trusted_sources: List[str] = field(default_factory=list)
    
    # Development settings
    dev_mode: bool = False
    hot_reload: bool = False
    debug_plugins: bool = False
    
    # Cache settings
    cache_discovery: bool = True
    cache_duration: int = 3600  # seconds
    
    def get_plugin_setting(self, plugin_name: str) -> PluginSettings:
        """Get settings for a specific plugin"""
        return self.plugin_settings.get(plugin_name, PluginSettings())
    
    def set_plugin_setting(self, plugin_name: str, settings: PluginSettings) -> None:
        """Set settings for a specific plugin"""
        self.plugin_settings[plugin_name] = settings
    
    def is_plugin_enabled(self, plugin_name: str) -> bool:
        """Check if a plugin is enabled"""
        if plugin_name in self.disabled_plugins:
            return False
        
        plugin_settings = self.get_plugin_setting(plugin_name)
        return plugin_settings.enabled
    
    def disable_plugin(self, plugin_name: str) -> None:
        """Disable a plugin"""
        if plugin_name not in self.disabled_plugins:
            self.disabled_plugins.append(plugin_name)
    
    def enable_plugin(self, plugin_name: str) -> None:
        """Enable a plugin"""
        if plugin_name in self.disabled_plugins:
            self.disabled_plugins.remove(plugin_name)
        
        # Ensure plugin settings exist and are enabled
        if plugin_name not in self.plugin_settings:
            self.plugin_settings[plugin_name] = PluginSettings()
        self.plugin_settings[plugin_name].enabled = True
    
    def get_resolved_plugin_directories(self, project_root: Optional[Path] = None) -> List[Path]:
        """Get resolved plugin directory paths"""
        resolved = []
        
        for directory in self.plugin_directories:
            # Expand user home directory
            if directory.startswith("~/"):
                path = Path.home() / directory[2:]
            # Expand project root placeholder
            elif "{project_root}" in directory and project_root:
                path = Path(directory.replace("{project_root}", str(project_root)))
            # Relative path
            elif not os.path.isabs(directory):
                if project_root:
                    path = project_root / directory
                else:
                    path = Path(directory).resolve()
            # Absolute path
            else:
                path = Path(directory)
            
            resolved.append(path)
        
        return resolved


class PluginConfigManager:
    """Manages plugin configuration loading and saving"""
    
    def __init__(self, config_path: Optional[Union[str, Path]] = None):
        self.config_path = Path(config_path) if config_path else self._get_default_config_path()
        self.config = PluginSystemConfig()
        self._load_config()
    
    def _get_default_config_path(self) -> Path:
        """Get the default plugin config path"""
        if os.name == 'posix':  # Linux/macOS
            config_base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
            return config_base / "penguin" / "plugins.yml"
        else:  # Windows
            config_base = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
            return config_base / "penguin" / "plugins.yml"
    
    def _load_config(self) -> None:
        """Load plugin configuration from file"""
        if not self.config_path.exists():
            logger.info(f"Plugin config file not found at {self.config_path}, using defaults")
            return
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                if self.config_path.suffix.lower() in ['.yml', '.yaml']:
                    data = yaml.safe_load(f)
                elif self.config_path.suffix.lower() == '.json':
                    data = json.load(f)
                else:
                    logger.warning(f"Unsupported config file format: {self.config_path.suffix}")
                    return
            
            if data:
                self._update_config_from_dict(data)
                logger.info(f"Loaded plugin configuration from {self.config_path}")
        
        except Exception as e:
            logger.error(f"Error loading plugin config from {self.config_path}: {e}")
    
    def _update_config_from_dict(self, data: Dict[str, Any]) -> None:
        """Update configuration from dictionary"""
        # Update basic settings
        for key, value in data.items():
            if key == 'plugin_settings':
                # Handle plugin-specific settings
                for plugin_name, plugin_data in value.items():
                    settings = PluginSettings(
                        enabled=plugin_data.get('enabled', True),
                        config=plugin_data.get('config', {}),
                        auto_load=plugin_data.get('auto_load', True),
                        priority=plugin_data.get('priority', 0),
                        dependencies=plugin_data.get('dependencies', []),
                        permissions=plugin_data.get('permissions', [])
                    )
                    self.config.plugin_settings[plugin_name] = settings
            elif hasattr(self.config, key):
                setattr(self.config, key, value)
    
    def save_config(self) -> None:
        """Save plugin configuration to file"""
        try:
            # Ensure directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Convert config to dictionary
            config_dict = self._config_to_dict()
            
            # Save to file
            with open(self.config_path, 'w', encoding='utf-8') as f:
                if self.config_path.suffix.lower() in ['.yml', '.yaml']:
                    yaml.safe_dump(config_dict, f, default_flow_style=False, indent=2)
                elif self.config_path.suffix.lower() == '.json':
                    json.dump(config_dict, f, indent=2)
            
            logger.info(f"Saved plugin configuration to {self.config_path}")
        
        except Exception as e:
            logger.error(f"Error saving plugin config to {self.config_path}: {e}")
    
    def _config_to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary for serialization"""
        config_dict = {
            'plugin_directories': self.config.plugin_directories,
            'auto_discover': self.config.auto_discover,
            'discover_entry_points': self.config.discover_entry_points,
            'entry_point_group': self.config.entry_point_group,
            'parallel_loading': self.config.parallel_loading,
            'max_load_workers': self.config.max_load_workers,
            'load_timeout': self.config.load_timeout,
            'disabled_plugins': self.config.disabled_plugins,
            'allow_system_plugins': self.config.allow_system_plugins,
            'allow_user_plugins': self.config.allow_user_plugins,
            'require_signatures': self.config.require_signatures,
            'trusted_sources': self.config.trusted_sources,
            'dev_mode': self.config.dev_mode,
            'hot_reload': self.config.hot_reload,
            'debug_plugins': self.config.debug_plugins,
            'cache_discovery': self.config.cache_discovery,
            'cache_duration': self.config.cache_duration,
        }
        
        # Convert plugin settings
        if self.config.plugin_settings:
            plugin_settings_dict = {}
            for plugin_name, settings in self.config.plugin_settings.items():
                plugin_settings_dict[plugin_name] = {
                    'enabled': settings.enabled,
                    'config': settings.config,
                    'auto_load': settings.auto_load,
                    'priority': settings.priority,
                    'dependencies': settings.dependencies,
                    'permissions': settings.permissions
                }
            config_dict['plugin_settings'] = plugin_settings_dict
        
        return config_dict
    
    def get_plugin_config(self, plugin_name: str) -> Dict[str, Any]:
        """Get configuration for a specific plugin"""
        settings = self.config.get_plugin_setting(plugin_name)
        return settings.config
    
    def set_plugin_config(self, plugin_name: str, config: Dict[str, Any]) -> None:
        """Set configuration for a specific plugin"""
        if plugin_name not in self.config.plugin_settings:
            self.config.plugin_settings[plugin_name] = PluginSettings()
        
        self.config.plugin_settings[plugin_name].config = config
    
    def update_plugin_config(self, plugin_name: str, config: Dict[str, Any]) -> None:
        """Update configuration for a specific plugin (merge with existing)"""
        if plugin_name not in self.config.plugin_settings:
            self.config.plugin_settings[plugin_name] = PluginSettings()
        
        self.config.plugin_settings[plugin_name].config.update(config)
    
    def is_plugin_enabled(self, plugin_name: str) -> bool:
        """Check if a plugin is enabled"""
        return self.config.is_plugin_enabled(plugin_name)
    
    def enable_plugin(self, plugin_name: str, save: bool = True) -> None:
        """Enable a plugin"""
        self.config.enable_plugin(plugin_name)
        if save:
            self.save_config()
    
    def disable_plugin(self, plugin_name: str, save: bool = True) -> None:
        """Disable a plugin"""
        self.config.disable_plugin(plugin_name)
        if save:
            self.save_config()
    
    def get_config(self) -> PluginSystemConfig:
        """Get the current plugin system configuration"""
        return self.config
    
    def reload_config(self) -> None:
        """Reload configuration from file"""
        self._load_config()


# Global plugin configuration instance
_plugin_config_manager: Optional[PluginConfigManager] = None


def get_plugin_config_manager(config_path: Optional[Union[str, Path]] = None) -> PluginConfigManager:
    """Get the global plugin configuration manager"""
    global _plugin_config_manager
    
    if _plugin_config_manager is None:
        _plugin_config_manager = PluginConfigManager(config_path)
    
    return _plugin_config_manager


def get_plugin_config() -> PluginSystemConfig:
    """Get the current plugin system configuration"""
    return get_plugin_config_manager().get_config()


def create_default_plugin_config() -> None:
    """Create a default plugin configuration file"""
    config_manager = get_plugin_config_manager()
    
    # Set some sensible defaults for common plugins
    config_manager.config.plugin_settings.update({
        'core_tools': PluginSettings(
            enabled=True,
            auto_load=True,
            priority=100,  # Load first
            config={'max_command_timeout': 30}
        ),
        'browser_tools': PluginSettings(
            enabled=True,
            auto_load=True,
            priority=90,
            config={'headless': True, 'timeout': 30}
        ),
        'memory_tools': PluginSettings(
            enabled=True,
            auto_load=True,
            priority=80,
            config={'cache_size': 1000}
        )
    })
    
    config_manager.save_config()
    logger.info("Created default plugin configuration")