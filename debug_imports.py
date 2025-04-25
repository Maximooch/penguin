#!/usr/bin/env python
"""
Debug script to check Python paths and module availability.
Run with: python debug_imports.py
"""

import sys
import os

def main():
    print("Python Import Path Debugging Information")
    print("----------------------------------------")
    print(f"Python executable: {sys.executable}")
    print(f"Python version: {sys.version}")
    print("\nCurrent working directory:")
    print(os.getcwd())
    
    print("\nModule search paths:")
    for i, path in enumerate(sys.path):
        print(f"{i+1}. {path}")
    
    print("\nChecking for key module files:")
    potential_paths = [
        "penguin/utils/events.py",
        "penguin/system/state.py",
        "penguin/penguin/utils/events.py",
        "penguin/penguin/system/state.py",
        "utils/events.py",
        "system/state.py"
    ]
    
    for path in potential_paths:
        exists = os.path.exists(path)
        print(f"{path}: {'EXISTS' if exists else 'NOT FOUND'}")
    
    print("\nTrying imports:")
    modules_to_try = [
        "import penguin",
        "import penguin.utils.events",
        "import penguin.system.state",
        "import penguin.penguin.utils.events",
        "import penguin.penguin.system.state",
    ]
    
    for module_import in modules_to_try:
        try:
            exec(module_import)
            print(f"{module_import}: SUCCESS")
            # Try to get the module's file location
            module_name = module_import.split("import ")[1]
            try:
                module = eval(module_name)
                print(f"  - Location: {getattr(module, '__file__', 'Unknown')}")
            except:
                pass
        except ImportError as e:
            print(f"{module_import}: FAILED - {str(e)}")
        except Exception as e:
            print(f"{module_import}: ERROR - {str(e)}")

if __name__ == "__main__":
    main() 