# Tool registry systemfrom pathlib import Path
import yaml # type: ignore
from pathlib import Path
import importlib.util
from typing import Dict, List, Any, Optional, Callable

class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, Dict] = {}
        self.actions: Dict[str, Callable] = {}
        
    def register_tool(self, tool_config: Dict[str, Any], implementation=None):
        """Register a tool with its configuration and implementation"""
        name = tool_config.get('name')
        if not name:
            raise ValueError("Tool must have a name")
            
        self.tools[name] = {
            'config': tool_config,
            'implementation': implementation
        }
        
        # Register individual actions
        for action in tool_config.get('actions', []):
            action_name = action.get('name')
            if action_name:
                self.actions[f"{name}.{action_name}"] = self._create_action_handler(
                    name, action_name, implementation
                )
                
    def _create_action_handler(self, tool_name, action_name, implementation):
        """Create a function that handles the specific action"""
        def handler(**kwargs):
            return implementation.execute_action(action_name, **kwargs)
        return handler
                
    def discover_core_tools(self, core_dir: Path):
        """Discover and load core tools"""
        definitions_dir = core_dir / "definitions"
        
        for config_file in definitions_dir.glob("*.yml"):
            with open(config_file) as f:
                config = yaml.safe_load(f)
                
            # Load implementation module
            module_name = config_file.stem
            impl_path = core_dir / f"{module_name}.py"
            
            if impl_path.exists():
                # Import the implementation module
                spec = importlib.util.spec_from_file_location(module_name, impl_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                self.register_tool(config, module.ToolImplementation())