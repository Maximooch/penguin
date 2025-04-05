#!/usr/bin/env python3
"""
Penguin Textual CLI Launcher
Run this script to start the Penguin AI assistant with the Textual UI.
"""

import asyncio
import sys
from pathlib import Path

# Add the project root to path if needed
root_dir = Path(__file__).parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

# Import the Textual CLI main function
from penguin.chat.textual_cli import main

if __name__ == "__main__":
    try:
        # Run the Textual CLI
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting Penguin AI...")
    except Exception as e:
        print(f"Error starting Penguin: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1) 