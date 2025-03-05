from pathlib import Path
import yaml # type: ignore

# Try to import MCP components, but make them optional
try:
    from mcp import ModelContextProtocol  # May not exist in current mcp version
    HAS_MCP = True
except ImportError:
    # Create a placeholder class for type checking
    class ModelContextProtocol:
        """Placeholder for ModelContextProtocol when MCP is not available."""
        pass
    HAS_MCP = False

from penguin.tools.registry import ToolRegistry

class MCPAdapter:
    def __init__(self, tool_registry: ToolRegistry):
        if not HAS_MCP:
            raise ImportError("MCP package is not properly installed or doesn't have required components")
        
        self.mcp = ModelContextProtocol()
        self.tool_registry = tool_registry
        self.config = self._load_config()
        
    def _load_config(self):
        config_path = Path(__file__).parent / "config.yml"
        with open(config_path) as f:
            return yaml.safe_load(f)
            
    def setup(self):
        """Set up bidirectional integration between Penguin and MCP"""
        self._register_penguin_tools_with_mcp()
        self._register_mcp_tools_with_penguin()
        
    def _register_penguin_tools_with_mcp(self):
        """Register Penguin tools with MCP"""
        for tool_name, tool_data in self.tool_registry.tools.items():
            config = tool_data['config']
            
            # Skip tools that shouldn't be exposed to MCP
            if config.get('mcp_expose', True) is False:
                continue
                
            for action in config.get('actions', []):
                self.mcp.register_tool(
                    name=f"{tool_name}.{action['name']}",
                    description=action['description'],
                    parameters={
                        param['name']: param['type'] 
                        for param in action.get('parameters', [])
                    },
                    callback=self.tool_registry.actions[f"{tool_name}.{action['name']}"]
                )
                
    def _register_mcp_tools_with_penguin(self):
        """Register MCP tools with Penguin"""
        mcp_tools = self.mcp.list_available_tools()
        
        for tool_mapping in self.config.get('tools', []):
            external_name = tool_mapping['external_name']
            if external_name in mcp_tools:
                # Create a wrapper for this MCP tool
                self.tool_registry.register_tool({
                    'name': tool_mapping['internal_name'],
                    'description': f"MCP tool: {external_name}",
                    'actions': [{
                        'name': 'execute',
                        'description': f"Execute the {external_name} MCP tool"
                    }]
                }, MCPToolImplementation(self.mcp, external_name, tool_mapping)) # type: ignore

class MCPPromptImplementation:
    """Wrapper class for MCP prompts to make them usable within Penguin."""
    
    def __init__(self, mcp, external_name: str, prompt_mapping: dict):
        """
        Initialize an MCP prompt implementation.
        
        Args:
            mcp: The ModelContextProtocol instance
            external_name: The name of the prompt in MCP
            prompt_mapping: Configuration mapping between MCP and Penguin
        """
        self.mcp = mcp
        self.external_name = external_name
        self.prompt_mapping = prompt_mapping
        
    async def render(self, **kwargs):
        """
        Render the MCP prompt with the provided parameters.
        
        Args:
            **kwargs: Parameters to pass to the MCP prompt
            
        Returns:
            The rendered prompt text
        """
        # Map parameter names if specified in the prompt mapping
        mapped_params = {}
        param_mapping = self.prompt_mapping.get('parameter_mapping', {})
        
        for param_name, param_value in kwargs.items():
            # If there's a mapping for this parameter, use the mapped name
            if param_name in param_mapping:
                mapped_params[param_mapping[param_name]] = param_value
            else:
                # Otherwise use the parameter as-is
                mapped_params[param_name] = param_value
        
        # Execute the MCP prompt and return the result
        result = await self.mcp.execute_prompt(self.external_name, **mapped_params)
        return result