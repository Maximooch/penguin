#!/usr/bin/env python3
"""
Test memory provider configuration to debug why faiss isn't being used.
"""

import logging
import sys
from pathlib import Path

# Add repo root to path
repo_root = Path(__file__).resolve().parents[2] 
sys.path.insert(0, str(repo_root))

# Set up logging to see all messages
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')

from penguin.config import load_config
from penguin.memory.providers.factory import MemoryProviderFactory

def test_memory_provider_creation():
    print("=== Testing Memory Provider Creation ===")
    
    # Load config
    config = load_config()
    print(f"Raw config: {config}")
    
    memory_config = config.get('memory', {})
    print(f"Memory config section: {memory_config}")
    
    # Test with explicit faiss provider
    faiss_config = {
        'provider': 'faiss',
        'embedding_model': 'sentence-transformers/all-MiniLM-L6-v2',
        'storage_path': '/tmp/test_memory'
    }
    
    print(f"\n=== Testing explicit FAISS config ===")
    print(f"FAISS config: {faiss_config}")
    
    try:
        provider = MemoryProviderFactory.create_provider(faiss_config)
        print(f"Successfully created provider: {type(provider).__name__}")
    except Exception as e:
        print(f"Failed to create FAISS provider: {e}")
    
    # Test with config from file
    print(f"\n=== Testing config from file ===")
    if memory_config:
        try:
            provider = MemoryProviderFactory.create_provider(memory_config)
            print(f"Successfully created provider from config: {type(provider).__name__}")
        except Exception as e:
            print(f"Failed to create provider from config: {e}")
    else:
        print("No memory config found in file")
    
    # Show available providers
    print(f"\n=== Available providers ===")
    available = MemoryProviderFactory.get_available_providers()
    print(f"Available providers: {available}")
    
    for provider_name in available:
        info = MemoryProviderFactory.get_provider_info(provider_name)
        print(f"  {provider_name}: {info}")

if __name__ == "__main__":
    test_memory_provider_creation() 