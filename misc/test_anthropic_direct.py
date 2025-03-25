import os
import asyncio
from dotenv import load_dotenv
from anthropic import AsyncAnthropic

# Load environment variables
load_dotenv()
api_key = os.getenv("ANTHROPIC_API_KEY")

async def test_direct_streaming():
    # Create a client
    client = AsyncAnthropic(api_key=api_key)
    
    print("Starting direct Anthropic streaming test...")
    
    # Define our message
    messages = [
        {"role": "user", "content": "Write a short poem about penguins."}
    ]
    
    # Create the streaming response
    stream = await client.messages.create(
        model="claude-3-sonnet-20240229",
        max_tokens=1024,
        messages=messages,
        stream=True
    )
    
    # Process the stream
    accumulated = []
    
    async for chunk in stream:
        # Print chunk type for debugging
        print(f"Chunk type: {chunk.type}")
        
        # Handle different event types
        if chunk.type == 'content_block_delta' and hasattr(chunk, 'delta'):
            if chunk.delta.type == 'text_delta' and hasattr(chunk.delta, 'text'):
                content = chunk.delta.text
                print(content, end="", flush=True)
                accumulated.append(content)
                
        elif chunk.type == 'content_block_start' and hasattr(chunk, 'content_block'):
            if chunk.content_block.type == 'text' and hasattr(chunk.content_block, 'text'):
                content = chunk.content_block.text
                print(content, end="", flush=True)
                accumulated.append(content)
    
    print("\n\nComplete response:")
    print(''.join(accumulated))

if __name__ == "__main__":
    asyncio.run(test_direct_streaming()) 