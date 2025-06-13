import os
import pytest
import asyncio
from typing import List
from penguin.llm import APIClient
from penguin.llm.model_config import ModelConfig

# get the api key from the environment variable
api_key = os.getenv("ANTHROPIC_API_KEY")

@pytest.mark.asyncio
async def test_anthropic_streaming():
    """Test streaming response from Claude 3.5 Haiku"""
    # Setup configuration
    model_config = ModelConfig(
        model="claude-3-5-sonnet-20240620",
        provider="anthropic-native",
        max_tokens=500,
        temperature=0.7
    )
    
    # Initialize client
    client = APIClient(model_config)
    client.set_system_prompt("You are a helpful AI assistant")
    
    # Configure streaming callback
    stream_chunks: List[str] = []
    
    def stream_callback(chunk: str):
        """Collect streaming response chunks"""
        nonlocal stream_chunks
        stream_chunks.append(chunk)
        print(f"Received chunk: {chunk}")

    # Test messages
    messages = [
        {"role": "user", "content": "Explain quantum computing in 3 sentences"}
    ]
    
    try:
        # Make streaming request
        response = await client.create_message(
            messages=messages,
            stream_callback=stream_callback
        )
        
        # Process final response
        full_response, _ = client.process_response(response)
        combined_stream = "".join(stream_chunks)
        
        # Basic assertions
        assert len(stream_chunks) > 0, "No streaming chunks received"
        assert len(full_response) > 50, "Response too short"
        assert full_response == combined_stream, "Stream mismatch"
        print(f"\nFull response: {full_response}")
        
    except Exception as e:
        pytest.fail(f"API call failed: {str(e)}")

# Run with: pytest -s -v tests/test_anthropic_streaming.py 