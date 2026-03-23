"""Convenience for running this file directly during local development.
If the `penguin` package hasn't been installed into the active Python
environment (e.g. via `pip install -e .`), the import below will fail when
executing the file *as a script* (``python penguin/misc/test1.py``) because
only the current directory – ``penguin/misc`` – is on ``sys.path``.

To make local tinkering painless we dynamically add the repository root to
``sys.path`` **before** importing from ``penguin.*``.  When the package *is*
installed this block is a harmless no-op.
"""

from __future__ import annotations

import pathlib
import sys


# Detect repository root (two levels above this file's parent directory)
# This file is at penguin/misc/test1.py, so we need to go up 2 levels to get to the root
_repo_root = pathlib.Path(__file__).resolve().parents[2]

# Add to import search path if needed
if ( _repo_root / "penguin" ).is_dir() and str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

# scripts/stream_debug.py
import asyncio
from penguin.agent import PenguinAgentAsync

PROMPT = (
    "/run --247 To test: go to this url and describe to me the image you see: "
    "https://imgur.com/a/tn8MIFb (this is just a test, keep it simple, no scratchpad needed)"
)

async def main():
    agent = await PenguinAgentAsync.create()          # uses PenguinCore under the hood
    
    # Add some debug logging to see memory configuration
    import logging
    logging.basicConfig(level=logging.INFO)
    
    # Try to access the core and see memory config
    try:
        core = agent._core  # Assuming this is how to access the core
        if hasattr(core, 'config'):
            memory_config = core.config.get("memory", {})
            print(f"DEBUG: Memory config in core: {memory_config}")
    except Exception as e:
        print(f"DEBUG: Could not access core config: {e}")
    
    print("=== STREAM START ===")
    async for chunk in agent.stream(PROMPT):
        print(repr(chunk))                            # repr() lets you see whitespace/new-line repeats
    print("\n=== STREAM END ===")

if __name__ == "__main__":
    asyncio.run(main())