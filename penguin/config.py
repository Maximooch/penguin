import os

# API Keys
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
# Constants
CONTINUATION_EXIT_PHRASE = "AUTOMODE_COMPLETE"
MAX_CONTINUATION_ITERATIONS = 100

# Model Configuration
DEFAULT_MODEL = "claude-3-5-sonnet-20240620"
DEFAULT_MAX_TOKENS = 4000

# Color Configuration
USER_COLOR = "white"
CLAUDE_COLOR = "blue"
TOOL_COLOR = "yellow"
RESULT_COLOR = "green"

# You can add more configuration settings here as needed