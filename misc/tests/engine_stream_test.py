import asyncio
import sys
from pathlib import Path

# Ensure project root on path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from penguin.core import PenguinCore  # type: ignore


async def main():
    core = await PenguinCore.create()

    print("=== Engine streaming demo ===")
    async for chunk in core.engine.stream("Write a limerick about penguins."):
        print(chunk, end="", flush=True)
    print("\n[done]\n")


if __name__ == "__main__":
    asyncio.run(main()) 