import yaml # type: ignore
import json
from pathlib import Path

class ToolLoader:
    def __init__(self):
        self.tools_dir = Path(__file__).parent / "tools"
        self.core_tools = []
        self.third_party_tools = []
        
    def load_tools(self):
        # Load core tools
        core_path = self.tools_dir / "core"
        self.core_tools = self._load_from_dir(core_path)
        
        # Load third-party tools
        third_party_path = self.tools_dir / "third_party"
        self.third_party_tools = self._load_from_dir(third_party_path)
        
        # Load MCP tools if SDK installed
        try:
            from mcp_sdk import ModelContextProtocol # type: ignore
            self._load_mcp_tools(ModelContextProtocol())
        except ImportError:
            pass

    def _load_from_dir(self, path: Path):
        tools = []
        for config_file in path.glob("**/*.{yml,yaml,json}"):
            with open(config_file) as f:
                if config_file.suffix in (".yml", ".yaml"):
                    tool_config = yaml.safe_load(f)
                else:
                    tool_config = json.load(f)
                    
                if self._validate_tool(tool_config):
                    tools.append(tool_config)
                    self._register_action(tool_config)
        return tools

    def _validate_tool(self, config: dict) -> bool:
        required_fields = {'name', 'description', 'parameters'}
        return required_fields.issubset(config.keys()) 