#!/usr/bin/env python3
"""
Debug script to compare dataclass Config vs global config dict
"""

import sys
from pathlib import Path

# Add repo root to path
repo_root = Path(__file__).resolve().parents[2] 
sys.path.insert(0, str(repo_root))

def debug_config_differences():
    print("=== Config Debug ===")
    
    # Import both config sources
    from penguin.config import config as global_config, Config
    
    print(f"Global config type: {type(global_config)}")
    print(f"Global config keys: {list(global_config.keys())}")
    print(f"Memory section in global config: {global_config.get('memory', 'NOT FOUND')}")
    
    print(f"\n--- Dataclass Config ---")
    dataclass_config = Config.load_config()
    print(f"Dataclass config type: {type(dataclass_config)}")
    print(f"Dataclass config __dict__: {dataclass_config.__dict__.keys()}")
    
    # Try to convert dataclass to dict like core.py does
    config_dict = dataclass_config.__dict__ if hasattr(dataclass_config, '__dict__') else dataclass_config
    print(f"Config dict keys: {list(config_dict.keys())}")
    print(f"Memory section in config dict: {config_dict.get('memory', 'NOT FOUND')}")
    
    print(f"\n--- Comparison ---")
    print(f"Global config has memory: {'memory' in global_config}")
    print(f"Config dict has memory: {'memory' in config_dict}")
    
    if 'memory' in global_config:
        print(f"Global memory config: {global_config['memory']}")
    
    if 'memory' in config_dict:
        print(f"Config dict memory config: {config_dict['memory']}")

if __name__ == "__main__":
    debug_config_differences() 