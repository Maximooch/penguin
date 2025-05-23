from pathlib import Path
import yaml # type: ignore

# OPTIONAL. Only necessary if you are using MCP
from mcp_sdk import ModelContextProtocol # type: ignore 


from penguin.tools.registry import ToolRegistry

class MCPAdapter:
    def __init__(self, tool_registry: ToolRegistry):
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