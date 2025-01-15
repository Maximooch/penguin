import os
from typing import Dict, Any
from pathlib import Path
from llm.model_config import ModelConfig
from llm.api_client import APIClient
from core import PenguinCore
from tools import ToolManager
from utils.log_error import log_error
import logging
import asyncio
import litellm

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
litellm_logger = logging.getLogger("litellm")
litellm_logger.setLevel(logging.INFO)

# Get the absolute path to the image
CURRENT_DIR = Path(__file__).parent
IMAGE_PATH = CURRENT_DIR / "IMG.jpg"

def debug_print_response(prefix: str, response: Any):
    """Helper to print response details safely"""
    print(f"\n=== {prefix} ===")
    if isinstance(response, dict):
        if 'assistant_response' in response:
            print(f"Assistant: {response['assistant_response']}")
        if 'action_results' in response and response['action_results']:
            print(f"Tool calls: {response['action_results']}")
    else:
        print(str(response))
    print("=" * (len(prefix) + 8))

async def test_text_only(core: PenguinCore):
    """Test basic text message interaction"""
    print("\n=== Starting Text-Only Message Test ===")
    message = "Hello, how are you?"
    print(f"Sending message: {message}")
    
    try:
        await core.process_input({"text": message})
        response, _ = await core.get_response()
        debug_print_response("Response", response)
        
    except Exception as e:
        print(f"API call failed: {str(e)}")
        raise

async def test_with_images(core: PenguinCore):
    """Test message interaction with images"""
    print("\n=== Starting Image Message Test ===")
    
    try:
        if not IMAGE_PATH.exists():
            raise FileNotFoundError(f"Image not found at: {IMAGE_PATH}")
            
        print(f"Using image at path: {IMAGE_PATH}")
        
        input_data = {
            "text": "What's in this image?",
            "image_path": str(IMAGE_PATH)
        }
        
        await core.process_input(input_data)
        response, _ = await core.get_response()
        debug_print_response("Response", response)
        
    except Exception as e:
        print(f"API call with image failed: {str(e)}")
        raise

async def run_all_tests():
    """Run all test cases"""
    print("\n=== Starting All Tests ===")
    try:
        model_config = ModelConfig(
            model="claude-3-5-sonnet-20240620",
            provider="anthropic"
        )
        print(f"Model Config: {model_config.get_config()}")
        
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment")
        print("ANTHROPIC_API_KEY: ✓")
        
        api_client = APIClient(model_config=model_config)
        tool_manager = ToolManager(log_error)
        core = PenguinCore(api_client=api_client, tool_manager=tool_manager)
        
        await test_text_only(core)
        await test_with_images(core)
        print("\n✅ All tests completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(run_all_tests())