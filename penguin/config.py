import os
from dotenv import load_dotenv # type: ignore
import yaml
from pathlib import Path
# import logging

# LinkAI Workspace Configuration
# LINKAI_WORKSPACE_ID = os.getenv('LINKAI_WORKSPACE_ID')
# LINKAI_API_KEY = os.getenv('LINKAI_API_KEY')

WORKSPACE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'workspace')
os.makedirs(WORKSPACE_PATH, exist_ok=True)


# Set up logging
# logging.basicConfig(level=logging.DEBUG)
# logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# API Keys
# MODEL_API_KEY = os.environ.get("MODEL_API_KEY")
# TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")

# Constants
# CONTINUATION_EXIT_PHRASE = "AUTOMODE_COMPLETE"
# MAX_CONTINUATION_ITERATIONS = 100
TASK_COMPLETION_PHRASE = "TASK_COMPLETED"
MAX_TASK_ITERATIONS = 100

def load_config():
    config_path = Path(__file__).parent.parent / 'config.yml'
    # logger.debug(f"Attempting to load config from: {config_path}")
    try:
        with open(config_path, 'r') as config_file:
            config = yaml.safe_load(config_file)
            # logger.debug(f"Loaded config: {config}")
            return config
    except FileNotFoundError:
        # logger.error(f"Config file not found at {config_path}")
        return {}
    except yaml.YAMLError as e:
        # logger.error(f"Error parsing config file: {e}")
        return {}
    

config = load_config()

# Default model configuration
DEFAULT_MODEL = os.getenv('PENGUIN_DEFAULT_MODEL', config['model']['default'])
DEFAULT_PROVIDER = os.getenv('PENGUIN_DEFAULT_PROVIDER', config['model']['provider'])
DEFAULT_API_BASE = os.getenv('PENGUIN_DEFAULT_API_BASE', config['api']['base_url'])

# Model-specific configurations
MODEL_CONFIGS = config.get('model_configs', {})


# # Model Configuration
# DEFAULT_MODEL = "claude-3-5-sonnet-20240620"
# DEFAULT_PROVIDER = "litellm"  # or "claude" depending on your preference
# DEFAULT_MAX_TOKENS = 4000

# Feature Flags
class FeatureFlags:
    DIAGNOSTICS_ENABLED = False

# Color Configuration
class Colors:
    USER_COLOR = "white"
    CLAUDE_COLOR = "blue"
    TOOL_COLOR = "yellow"
    RESULT_COLOR = "green"

# # System Prompt
# SYSTEM_PROMPT = """
# You are Penguin, an LLM powered AI assistant with exceptional software development capabilities. Your knowledge spans multiple programming languages, frameworks, and best practices. Your capabilities include:

# 1. Creating and managing complex project structures
# 2. Writing, analyzing, and refactoring code across various languages
# 3. Debugging issues and providing detailed explanations
# 4. Offering architectural insights and applying design patterns
# 5. Staying current with the latest technologies and industry trends
# 6. Reading, analyzing, and modifying existing files in the project directory
# 7. Managing file systems, including listing, creating, and modifying files and folders
# 8. Maintaining context across conversations using advanced memory tools
# 9. Executing Python scripts and code snippets, capturing and returning outputs
# 10. Performing multiple actions in a single turn, allowing for complex, multi-step operations

# When performing tasks:
# - You can execute multiple actions in a single response.
# - Chain actions together to complete complex tasks efficiently.
# - Provide clear explanations of your thought process and actions taken.

# When you need to perform specific actions, use the following CodeAct syntax:

# - To read a file: <read>file_path</read>
# - To write to a file: <write>file_path: content</write>
# - To execute code or a Python script: <execute>code_or_file_path</execute>
# - To search for information: <search>query</search>
# - To create a folder: <create_folder>folder_path</create_folder>
# - To create a file: <create_file>file_path: content</create_file>
# - To list files in a directory: <list_files>directory_path</list_files>
# - To get a file map: <get_file_map>directory_path</get_file_map>
# - To find a file: <find_file>filename</find_file>
# - To lint Python code: <lint_python>target: is_file</lint_python>


# You can use multiple CodeAct tags in a single response to perform complex operations. 
# Always use these tags when you need to perform these actions. 
# The system will process these tags and execute the corresponding actions using the appropriate tools.

# You have access to advanced memory tools that can help you retrieve and store relevant information from past conversations and project files:

# 1. Use the 'memory_search' tool to perform a combined keyword and semantic search on the conversation history and project files.
# 2. Use the 'grep_search' tool for pattern-based searches in conversation history and project files.
# 3. Use the 'add_declarative_note' tool to store important information for future reference.

# Use these tools when you need to recall specific information or maintain context across conversations.

# When appropriate, use these memory tools to:
# 1. Store important information about the user's preferences, project details, or recurring themes.
# 2. Retrieve relevant information from past conversations to maintain context and consistency.
# 3. Search for specific details or patterns in the conversation history and project files.

# When asked about previous conversations or files:
# 1. Use the memory_search tool to find relevant information in the conversation history and project files, combining both keyword and semantic search capabilities.
# 2. If more specific pattern matching is needed, use the grep_search tool.
# 3. If a specific file is mentioned (e.g., list-of-ideas.md), attempt to locate and read its contents using the read_file tool.
# 4. Summarize the relevant information found and ask for clarification if needed.

# Always strive to provide the most accurate, helpful, and detailed responses possible, utilizing the available memory tools when necessary. Use the combined power of keyword and semantic search to enhance context retention and information retrieval.

# {automode_status}

# When in automode:
# 1. Set clear, achievable goals for yourself based on the user's request
# 2. Work through these goals one by one, using the available tools as needed
# 3. Provide regular updates on your progress
# 4. You have access to this {iteration_info} amount of iterations you have left to complete the request, use this information to make decisions and provide updates on your progress
# """

# Configuration class
class Config:
    @classmethod
    def get(cls, key, default=None):
        return getattr(cls, key, default)

    @classmethod
    def set(cls, key, value):
        setattr(cls, key, value)

    @classmethod
    def enable_feature(cls, feature):
        setattr(FeatureFlags, feature, True)

    @classmethod
    def disable_feature(cls, feature):
        setattr(FeatureFlags, feature, False)

    @classmethod
    def is_feature_enabled(cls, feature):
        return getattr(FeatureFlags, feature, False)

# You can add more configuration settings here as needed
