# test_litellm_gateway.py
import asyncio
import os
import sys
from pathlib import Path
import logging
from typing import Optional  # Added Optional

# --- Configuration ---

# Set the model you want to test with LiteLLM
# Ensure this is the full LiteLLM model string (e.g., 'openai/gpt-3.5-turbo', 'anthropic/claude-3-haiku-20240307')
# TEST_MODEL_ID = "openai/gpt-3.5-turbo"
# TEST_PROVIDER = "openai"
# EXPECTED_API_KEY_ENV = "OPENAI_API_KEY"
# VISION_ENABLED = False # gpt-3.5-turbo doesn't support vision

# Or use Anthropic Haiku (often cheaper/faster for testing)
TEST_MODEL_ID = "anthropic/claude-3-5-haiku-20241022"
TEST_PROVIDER = "anthropic"
EXPECTED_API_KEY_ENV = "ANTHROPIC_API_KEY"
VISION_ENABLED = True

# Or use Claude Sonnet 3.5
# TEST_MODEL_ID = "anthropic/claude-3-5-sonnet-20240620"
# TEST_PROVIDER = "anthropic"
# EXPECTED_API_KEY_ENV = "ANTHROPIC_API_KEY"
# VISION_ENABLED = True

# Optional: Set API Base for local models (e.g., Ollama)
# TEST_MODEL_ID = "ollama/llama3"
# TEST_PROVIDER = "ollama"
# TEST_API_BASE = "http://localhost:11434"
# EXPECTED_API_KEY_ENV = None # No key needed for local Ollama usually
# VISION_ENABLED = False # Or True if using a vision model like llava

# --- Image Configuration ---
# Provide EITHER a local path OR a URL for vision testing.
# If both are provided, the local path will be used.

# Optional: Provide a path to a local image file for vision testing
# Make sure the file exists! Example:
# TEST_IMAGE_PATH = "/path/to/your/local/image.jpg"
TEST_IMAGE_PATH: Optional[str] = "penguin.png"

# Optional: Provide a URL to an image for vision testing
# Use the RAW image URL, not a webpage displaying the image. Example:
# TEST_IMAGE_URL = "https://raw.githubusercontent.com/Maximooch/penguin/main/penguin/IMG.jpg"
TEST_IMAGE_URL: Optional[str] = "https://raw.githubusercontent.com/Maximooch/penguin/main/penguin/IMG.jpg"

# --- Setup ---

# Add the project root to the Python path to allow imports from 'penguin'
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    from penguin.llm.litellm_gateway import LiteLLMGateway
    from penguin.llm.model_config import ModelConfig
except ImportError as e:
    logger.error(f"ImportError: {e}. Make sure this script is in the project root directory and necessary modules exist.")
    sys.exit(1)

# --- Test Functions ---

async def run_text_completion(gateway: LiteLLMGateway):
    """Tests basic text completion (non-streaming)."""
    logger.info("--- Running Non-Streaming Text Test ---")
    messages = [{"role": "user", "content": "Explain the concept of asynchronous programming in Python briefly."}]
    try:
        response = await gateway.get_response(messages)
        logger.info("Non-Streaming Response Received:")
        print(response)
    except Exception as e:
        logger.error(f"Non-streaming test failed: {e}", exc_info=True)
    logger.info("--- Non-Streaming Text Test Complete ---")
    print("-" * 30)

async def run_streaming_completion(gateway: LiteLLMGateway):
    """Tests streaming text completion."""
    logger.info("--- Running Streaming Text Test ---")
    messages = [{"role": "user", "content": "Write a short haiku about a penguin."}]
    accumulated_chunks = []

    def stream_callback(chunk: str):
        print(chunk, end="", flush=True)
        accumulated_chunks.append(chunk)

    try:
        final_response = await gateway.get_response(messages, stream=True, stream_callback=stream_callback)
        print("\n--- End of Stream ---") # Add newline after stream ends
        logger.info("Streaming Complete. Final accumulated response length: %d", len(final_response))
        # Verify accumulated content matches final return value (optional check)
        if "".join(accumulated_chunks) != final_response:
             logger.warning("Mismatch between accumulated chunks and final response!")
             logger.debug(f"Accumulated: {''.join(accumulated_chunks)}")
             logger.debug(f"Final Return: {final_response}")

    except Exception as e:
        logger.error(f"Streaming test failed: {e}", exc_info=True)
    logger.info("--- Streaming Text Test Complete ---")
    print("-" * 30)

async def run_vision_completion(gateway: LiteLLMGateway, image_path: Optional[str], image_url: Optional[str]):
    """Tests vision completion using either a local path or a URL."""

    image_source = None
    source_type = None # 'path' or 'url'
    payload_part = None

    # Prioritize local path if available and valid
    if image_path and Path(image_path).is_file():
        image_source = image_path
        source_type = 'path'
        # The gateway's _format_image_part expects 'image_path' key for local files
        payload_part = {"type": "image_url", "image_path": image_path}
        logger.info(f"Using local image path for vision test: {image_path}")
    elif image_url and image_url.startswith(('http://', 'https://')):
        image_source = image_url
        source_type = 'url'
        # The gateway's _format_image_part expects 'image_url': {'url': ...} for URLs
        payload_part = {"type": "image_url", "image_url": {"url": image_url}}
        logger.info(f"Using image URL for vision test: {image_url}")
    else:
        logger.info("--- Skipping Vision Test (No valid image path or URL provided in config) ---")
        return

    if not gateway.model_config.vision_enabled:
        logger.warning(f"--- Skipping Vision Test (Vision not enabled in ModelConfig for {gateway.model_config.model}) ---")
        return

    logger.info(f"--- Running Vision Test (Source Type: {source_type}) ---")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this image briefly."},
                payload_part # Use the determined payload part
            ]
        }
    ]
    try:
        response = await gateway.get_response(messages)
        logger.info("Vision Response Received:")
        print(response)
    except Exception as e:
        logger.error(f"Vision test failed: {e}", exc_info=True)
    logger.info("--- Vision Test Complete ---")
    print("-" * 30)


async def main():
    """Main function to set up and run tests."""
    logger.info("Starting LiteLLM Gateway Test Script...")

    # 1. Check for API Key
    api_key = None
    if EXPECTED_API_KEY_ENV:
        api_key = os.getenv(EXPECTED_API_KEY_ENV)
        if not api_key:
            logger.error(f"Error: Required environment variable '{EXPECTED_API_KEY_ENV}' is not set.")
            logger.error("Please set the API key for the selected provider and try again.")
            sys.exit(1)
        logger.info(f"API Key found in environment variable '{EXPECTED_API_KEY_ENV}'.")

    # 2. Create ModelConfig
    try:
        model_conf = ModelConfig(
            model=TEST_MODEL_ID,
            provider=TEST_PROVIDER,
            api_key=api_key, # Pass key explicitly if found
            api_base=getattr(sys.modules[__name__], 'TEST_API_BASE', None), # Get api_base if defined
            max_tokens=500, # Keep tests short
            temperature=0.5,
            vision_enabled=VISION_ENABLED,
            streaming_enabled=True # Default streaming preference (can be overridden in call)
        )
        logger.info(f"ModelConfig created for: {model_conf.model} (Provider: {model_conf.provider}, Vision: {model_conf.vision_enabled})")
    except Exception as e:
        logger.error(f"Failed to create ModelConfig: {e}", exc_info=True)
        sys.exit(1)

    # 3. Instantiate Gateway
    try:
        gateway = LiteLLMGateway(model_conf)
        logger.info("LiteLLMGateway instantiated successfully.")
    except Exception as e:
        logger.error(f"Failed to instantiate LiteLLMGateway: {e}", exc_info=True)
        sys.exit(1)

    print("-" * 30)

    # 4. Run Tests
    await run_text_completion(gateway)
    await run_streaming_completion(gateway)
    # Pass both path and url config options to the vision test function
    await run_vision_completion(gateway, TEST_IMAGE_PATH, TEST_IMAGE_URL)

    logger.info("All tests finished.")


if __name__ == "__main__":
    print("=============================================")
    print("      LiteLLM Gateway Standalone Test")
    print("=============================================")
    print(f"Testing Model: {TEST_MODEL_ID}")
    if EXPECTED_API_KEY_ENV:
        print(f"Ensure '{EXPECTED_API_KEY_ENV}' environment variable is set.")

    # Update startup message based on image config
    if TEST_IMAGE_PATH and Path(TEST_IMAGE_PATH).is_file():
        print(f"Vision test will use LOCAL IMAGE: {TEST_IMAGE_PATH}")
    elif TEST_IMAGE_URL:
        print(f"Vision test will use IMAGE URL: {TEST_IMAGE_URL}")
    else:
        print("Vision test will be skipped (no image path or URL configured).")

    print("---------------------------------------------")

    asyncio.run(main())