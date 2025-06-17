#!/usr/bin/env python3
"""
Test to verify memory provider selection after the config fix.
"""

import asyncio
import sys
from pathlib import Path

# Add repo root to path
repo_root = Path(__file__).resolve().parents[2] 
sys.path.insert(0, str(repo_root))

async def test_memory_provider_selection():
    print("=== Testing Memory Provider Selection ===")
    
    from penguin.agent import PenguinAgentAsync
    
    # Create agent which will trigger memory provider initialization
    agent = await PenguinAgentAsync.create()
    
    # Try to access the tool manager to see memory provider
    try:
        core = agent._core
        tool_manager = core.tool_manager
        
        # Force memory provider initialization
        memory_provider = await tool_manager.ensure_memory_provider()
        
        if memory_provider:
            print(f"✅ Memory provider type: {type(memory_provider).__name__}")
            print(f"✅ Memory provider class: {memory_provider.__class__.__module__}.{memory_provider.__class__.__name__}")
            
            # Try to get provider stats
            try:
                stats = await memory_provider.get_memory_stats()
                provider_name = stats.get('provider', 'unknown')
                print(f"✅ Provider name from stats: {provider_name}")
            except Exception as e:
                print(f"⚠️ Could not get provider stats: {e}")
        else:
            print("❌ No memory provider found")
        
        # Also check the config that was passed
        config_dict = tool_manager.config
        memory_config = config_dict.get('memory', {})
        print(f"✅ Memory config provider setting: {memory_config.get('provider', 'not specified')}")
        
    except Exception as e:
        print(f"❌ Error accessing memory provider: {e}")
        
    print("\n=== Test Complete ===")

if __name__ == "__main__":
    asyncio.run(test_memory_provider_selection()) 