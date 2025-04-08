# test_openrouter_gateway.py
import asyncio
import os
import sys
from pathlib import Path
import logging
from typing import Optional

# --- Configuration ---

# Set the model you want to test with OpenRouter
# OpenRouter models are typically prefixed with provider, e.g., "openai/gpt-4o", "anthropic/claude-3-opus"
TEST_MODEL_ID = "openrouter/quasar-alpha"
TEST_PROVIDER = "openrouter"  # Provider is always 'openrouter'
EXPECTED_API_KEY_ENV = "OPENROUTER_API_KEY"
VISION_ENABLED = True  # gpt-4o supports vision

# Optional: OpenRouter site identification for leaderboards
SITE_URL = "https://linkai.chat"  # Replace with your site URL if desired
SITE_TITLE = "Penguin"  # Replace with your app name if desired

# Alternative models:
# TEST_MODEL_ID = "anthropic/claude-3-5-sonnet-20240620"  # Claude model via OpenRouter
# TEST_MODEL_ID = "google/gemini-1.5-pro"  # Gemini model via OpenRouter
# TEST_MODEL_ID = "meta-llama/llama-3-70b-instruct"  # Llama model via OpenRouter

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
    from penguin.llm.openrouter_gateway import OpenRouterGateway
    from penguin.llm.model_config import ModelConfig
except ImportError as e:
    logger.error(f"ImportError: {e}. Make sure this script is in the project root directory and necessary modules exist.")
    sys.exit(1)

# --- Test Functions ---

async def run_text_completion(gateway: OpenRouterGateway):
    """Tests basic text completion (non-streaming)."""
    logger.info("--- Running Non-Streaming Text Test ---")
    messages = [{"role": "user", "content": "Explain the concept of asynchronous programming in Python briefly."}]
    try:
        response = await gateway.get_response(messages, stream=False)
        logger.info("Non-Streaming Response Received:")
        print(response)
    except Exception as e:
        logger.error(f"Non-streaming test failed: {e}", exc_info=True)
    logger.info("--- Non-Streaming Text Test Complete ---")
    print("-" * 30)

async def run_streaming_completion(gateway: OpenRouterGateway):
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

async def run_vision_completion(gateway: OpenRouterGateway, image_path: Optional[str], image_url: Optional[str]):
    """Tests vision completion using either a local path or a URL."""
    
    image_source = None
    source_type = None # 'path' or 'url'
    content_parts = [{"type": "text", "text": "Describe this image briefly."}]

    # Prioritize local path if available and valid
    if image_path and Path(image_path).is_file():
        image_source = image_path
        source_type = 'path'
        # For local images, we'll use the base64 encoding method from the gateway
        # The OpenRouter gateway will handle the encoding internally
        try:
            with open(image_path, "rb") as img_file:
                import base64
                from PIL import Image
                import io
                
                # Read and resize the image
                img = Image.open(image_path)
                max_size = (1024, 1024)
                img.thumbnail(max_size, Image.LANCZOS)
                
                # Convert to JPEG and encode
                buffer = io.BytesIO()
                if img.mode != "RGB":
                    img = img.convert("RGB")
                img.save(buffer, format="JPEG")
                base64_image = base64.b64encode(buffer.getvalue()).decode("utf-8")
                
                # Create proper image part with base64 data
                image_part = {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                }
                content_parts.append(image_part)
                logger.info(f"Using local image path for vision test: {image_path} (encoded as base64)")
        except Exception as e:
            logger.error(f"Failed to encode local image: {e}")
            return
    elif image_url and image_url.startswith(('http://', 'https://')):
        image_source = image_url
        source_type = 'url'
        # OpenRouter expects the OpenAI-compatible format for URLs
        image_part = {
            "type": "image_url", 
            "image_url": {
                "url": image_url
            }
        }
        content_parts.append(image_part)
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
            "content": content_parts
        }
    ]
    try:
        response = await gateway.get_response(messages, stream=False)
        logger.info("Vision Response Received:")
        print(response)
    except Exception as e:
        logger.error(f"Vision test failed: {e}", exc_info=True)
    logger.info("--- Vision Test Complete ---")
    print("-" * 30)

async def run_system_message_test(gateway: OpenRouterGateway):
    """Tests the use of system messages."""
    logger.info("--- Running System Message Test ---")
    messages = [
        {"role": "system", "content": "You are a pirate who only speaks in pirate language."},
        {"role": "user", "content": "Tell me about neural networks."}
    ]
    try:
        response = await gateway.get_response(messages, stream=False)
        logger.info("System Message Response Received:")
        print(response)
    except Exception as e:
        logger.error(f"System message test failed: {e}", exc_info=True)
    logger.info("--- System Message Test Complete ---")
    print("-" * 30)

async def run_available_models_test(gateway: OpenRouterGateway):
    """Tests fetching available models from OpenRouter."""
    logger.info("--- Running Available Models Test ---")
    try:
        models = await gateway.get_available_models()
        logger.info(f"Retrieved {len(models)} models from OpenRouter")
        if models:
            logger.info("Sample of available models:")
            for model in models[:10]:  # Show first 10 models only
                print(f"- {model}")
            if len(models) > 10:
                print(f"...and {len(models) - 10} more")
    except Exception as e:
        logger.error(f"Available models test failed: {e}", exc_info=True)
    logger.info("--- Available Models Test Complete ---")
    print("-" * 30)

async def main():
    """Main function to set up and run tests."""
    logger.info("Starting OpenRouter Gateway Test Script...")

    # 1. Check for API Key
    api_key = os.getenv(EXPECTED_API_KEY_ENV)
    if not api_key:
        logger.error(f"Error: Required environment variable '{EXPECTED_API_KEY_ENV}' is not set.")
        logger.error("Please set the OpenRouter API key and try again.")
        sys.exit(1)
    logger.info(f"API Key found in environment variable '{EXPECTED_API_KEY_ENV}'.")

    # 2. Create ModelConfig
    try:
        model_conf = ModelConfig(
            model=TEST_MODEL_ID,
            provider=TEST_PROVIDER,
            client_preference="openrouter",  # Ensure this is set to "openrouter"
            api_key=api_key,
            max_tokens=500,  # Keep tests short
            temperature=0.5,
            vision_enabled=VISION_ENABLED,
            streaming_enabled=True  # Default streaming preference (can be overridden in call)
        )
        logger.info(f"ModelConfig created for: {model_conf.model} (Provider: {model_conf.provider}, Vision: {model_conf.vision_enabled})")
    except Exception as e:
        logger.error(f"Failed to create ModelConfig: {e}", exc_info=True)
        sys.exit(1)

    # 3. Instantiate Gateway
    try:
        gateway = OpenRouterGateway(model_conf, site_url=SITE_URL, site_title=SITE_TITLE)
        logger.info("OpenRouterGateway instantiated successfully.")
        logger.info(f"Using site URL: {SITE_URL}, site title: {SITE_TITLE}")
    except Exception as e:
        logger.error(f"Failed to instantiate OpenRouterGateway: {e}", exc_info=True)
        sys.exit(1)

    print("-" * 30)

    # 4. Run Tests
    await run_text_completion(gateway)
    await run_streaming_completion(gateway)
    await run_system_message_test(gateway)
    await run_available_models_test(gateway)
    # Pass both path and url config options to the vision test function
    await run_vision_completion(gateway, TEST_IMAGE_PATH, TEST_IMAGE_URL)

    logger.info("All tests finished.")


if __name__ == "__main__":
    print("=============================================")
    print("      OpenRouter Gateway Standalone Test")
    print("=============================================")
    print(f"Testing Model: {TEST_MODEL_ID}")
    print(f"Ensure '{EXPECTED_API_KEY_ENV}' environment variable is set.")
    print(f"OpenRouter Site URL: {SITE_URL}")
    print(f"OpenRouter Site Title: {SITE_TITLE}")

    # Update startup message based on image config
    if TEST_IMAGE_PATH and Path(TEST_IMAGE_PATH).is_file():
        print(f"Vision test will use LOCAL IMAGE: {TEST_IMAGE_PATH}")
    elif TEST_IMAGE_URL:
        print(f"Vision test will use IMAGE URL: {TEST_IMAGE_URL}")
    else:
        print("Vision test will be skipped (no image path or URL configured).")

    print("---------------------------------------------")

    asyncio.run(main()) 