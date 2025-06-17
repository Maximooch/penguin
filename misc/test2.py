#!/usr/bin/env python3
"""
Test runmode streaming to debug duplicate chunk issues.
This tests streaming at the core level to see if duplication is in CLI UI or deeper.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import time
from typing import Optional

# Detect repository root (two levels above this file's parent directory)
# This file is at penguin/misc/test2.py, so we need to go up 2 levels to get to the root
_repo_root = pathlib.Path(__file__).resolve().parents[2]

# Add to import search path if needed
if (_repo_root / "penguin").is_dir() and str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from penguin.core import PenguinCore

PROMPT = (
    "To test: go to this url and describe to me the image you see: "
    "https://imgur.com/a/tn8MIFb (this is just a test, keep it simple, no scratchpad needed)"
)

class StreamingDebugger:
    """Debug helper to track streaming chunks and detect duplicates."""
    
    def __init__(self):
        self.chunks = []
        self.chunk_hashes = set()
        self.duplicate_count = 0
        self.start_time = None
        self.last_chunk_time = None
        
    async def stream_callback(self, chunk: str) -> None:
        """Callback to capture and analyze streaming chunks."""
        current_time = time.time()
        
        if self.start_time is None:
            self.start_time = current_time
            print("=== RUNMODE STREAM START ===")
        
        # Track timing
        time_since_start = current_time - self.start_time
        time_since_last = current_time - self.last_chunk_time if self.last_chunk_time else 0
        self.last_chunk_time = current_time
        
        # Check for duplicates
        chunk_hash = hash(chunk)
        is_duplicate = chunk_hash in self.chunk_hashes
        
        if is_duplicate:
            self.duplicate_count += 1
            duplicate_marker = " [DUPLICATE!]"
        else:
            self.chunk_hashes.add(chunk_hash)
            duplicate_marker = ""
        
        # Store chunk info
        chunk_info = {
            "index": len(self.chunks),
            "content": chunk,
            "hash": chunk_hash,
            "is_duplicate": is_duplicate,
            "time_since_start": time_since_start,
            "time_since_last": time_since_last,
            "length": len(chunk)
        }
        self.chunks.append(chunk_info)
        
        # Print chunk with debug info
        print(f"[{len(self.chunks):3d}] +{time_since_last:.3f}s {repr(chunk)}{duplicate_marker}")
        
    def print_summary(self):
        """Print summary of streaming analysis."""
        print("\n=== RUNMODE STREAM END ===")
        print(f"Total chunks: {len(self.chunks)}")
        print(f"Unique chunks: {len(self.chunk_hashes)}")
        print(f"Duplicate chunks: {self.duplicate_count}")
        print(f"Total duration: {self.last_chunk_time - self.start_time:.3f}s")
        
        if self.duplicate_count > 0:
            print(f"\n⚠️  FOUND {self.duplicate_count} DUPLICATE CHUNKS!")
            print("Duplicate chunk details:")
            for chunk_info in self.chunks:
                if chunk_info["is_duplicate"]:
                    print(f"  Chunk {chunk_info['index']}: {repr(chunk_info['content'])}")
        else:
            print("✅ No duplicate chunks detected")
            
        # Show full reconstructed response
        full_response = "".join(chunk["content"] for chunk in self.chunks)
        print(f"\nFull reconstructed response ({len(full_response)} chars):")
        print(f"'{full_response}'")

async def test_runmode_streaming():
    """Test runmode with streaming to detect duplicate chunks."""
    print("=== Testing Runmode Streaming ===")
    print(f"Prompt: {PROMPT}")
    
    # Create core instance
    core = await PenguinCore.create(enable_cli=False)
    
    # Set up streaming debugger
    debugger = StreamingDebugger()
    
    try:
        # Start runmode with streaming callback
        print("\n🚀 Starting runmode with streaming...")
        await core.start_run_mode(
            name="stream_test", 
            description="Test streaming in runmode",
            context={"test_mode": True},
            continuous=False,
            time_limit=60,  # 1 minute limit
            stream_callback_for_cli=debugger.stream_callback
        )
        
        # Process the test prompt
        print("\n📝 Processing prompt...")
        result = await core.process(
            input_data=PROMPT,
            streaming=True,
            stream_callback=debugger.stream_callback
        )
        
        print(f"\n📋 Final result type: {type(result)}")
        print(f"📋 Final result keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}")
        
        if isinstance(result, dict) and "assistant_response" in result:
            response = result["assistant_response"]
            print(f"📋 Assistant response length: {len(response)} chars")
            print(f"📋 Assistant response preview: {repr(response[:100])}...")
            
    except Exception as e:
        print(f"❌ Error during runmode test: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Print streaming analysis
        debugger.print_summary()

async def main():
    """Main test function."""
    print("=" * 60)
    print("RUNMODE STREAMING DUPLICATE DETECTION TEST")
    print("=" * 60)
    
    try:
        await test_runmode_streaming()
    except KeyboardInterrupt:
        print("\n🛑 Test interrupted by user")
    except Exception as e:
        print(f"\n💥 Test failed with error: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
