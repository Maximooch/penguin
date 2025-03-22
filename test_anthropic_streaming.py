import asyncio
import os
import sys
import logging
from dotenv import load_dotenv # type: ignore

# Configure logging to see what's happening
logging.basicConfig(level=logging.WARNING, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("anthropic_test")

# Add the Penguin module to the path
sys.path.append("/Users/maximusputnam/Documents/code/Penguin")

# Import the required modules
from penguin.llm.adapters.anthropic import AnthropicAdapter
from penguin.llm.model_config import ModelConfig

# Simple streaming callback function with more information
def stream_callback(text):
    if text:
        logger.info(f"Received stream content: '{text}'")
        print(text, end="", flush=True)
    else:
        logger.warning("Received empty content in callback")

async def test_anthropic_streaming():
    logger.info("Testing Anthropic Streaming...")
    
    # Load environment variables and check for API key
    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY environment variable not found!")
        return
    
    # Create model configuration
    model_config = ModelConfig(
        model="claude-3-sonnet-20240229",
        provider="anthropic",
        use_native_adapter=True,
        streaming_enabled=True,
        api_key=api_key  # Make sure to pass the API key explicitly
    )
    
    try:
        # Initialize adapter
        adapter = AnthropicAdapter(model_config)
        logger.info("Initialized Anthropic adapter")
        
        # Test messages
        messages = [
            {"role": "system", "content": "You are a helpful, friendly assistant."},
            {"role": "user", "content": "Write a short poem about penguins."}
        ]
        
        logger.info("Starting streaming request...")
        print("\nStarting streaming response:")
        print("\n---\n")
        
        # Stream the response
        full_response = await adapter.create_completion(
            messages=messages,
            max_tokens=1024,
            temperature=0.7,
            stream=True,
            stream_callback=stream_callback
        )
        
        print("\n\n---\n")
        print("\nFull accumulated response:")
        print(f"\n{full_response}")
        logger.info(f"Accumulated response length: {len(full_response)}")
        
    except Exception as e:
        logger.error(f"Error during test: {str(e)}", exc_info=True)
    
    logger.info("Streaming test complete!")

if __name__ == "__main__":
    asyncio.run(test_anthropic_streaming()) 