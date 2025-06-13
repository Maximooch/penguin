"""
Standalone test script for the LanceDBMemoryProvider.
"""

import asyncio
import shutil
import tempfile
import time
from pathlib import Path

# Conditional import for lancedb
try:
    import lancedb
    from penguin.memory.providers.lance_provider import LanceMemoryProvider
    LANCEDB_AVAILABLE = True
except ImportError:
    LANCEDB_AVAILABLE = False


async def test_add_and_get_memory(provider):
    """Test adding a memory and then retrieving it."""
    print("Running: test_add_and_get_memory")
    content = "This is a LanceDB test memory."
    metadata = {"source": "lance_test", "id": 1}
    memory_id = await provider.add_memory(content, metadata)
    assert isinstance(memory_id, str)

    retrieved_memory = await provider.get_memory(memory_id)
    assert retrieved_memory is not None
    assert retrieved_memory["id"] == memory_id
    assert retrieved_memory["content"] == content
    assert retrieved_memory["metadata"]["source"] == "lance_test"
    print("... PASSED")


async def test_vector_search(provider):
    """Test vector search functionality."""
    print("Running: test_vector_search")
    await provider.add_memory("A beautiful sunny day at the beach.", {})
    await provider.add_memory("A delicious and warm cup of coffee.", {})

    search_results = await provider.search_memory("What is the weather like?")
    assert len(search_results) > 0
    assert "beach" in search_results[0]["content"]
    print("... PASSED")


async def test_delete_memory(provider):
    """Test deleting a memory."""
    print("Running: test_delete_memory")
    memory_id = await provider.add_memory("This record will be deleted from LanceDB.", {})
    assert await provider.get_memory(memory_id) is not None

    deleted = await provider.delete_memory(memory_id)
    assert deleted is True
    assert await provider.get_memory(memory_id) is None
    print("... PASSED")


async def test_update_memory(provider):
    """Test that updating a memory is handled gracefully."""
    print("Running: test_update_memory")
    memory_id = await provider.add_memory("Original LanceDB content.", {})
    
    updated = await provider.update_memory(
        memory_id, content="Updated LanceDB content.", metadata={"updated": True}
    )
    assert updated is True
    assert await provider.get_memory(memory_id) is None
    print("... PASSED")


async def main():
    """Main function to run all tests."""
    if not LANCEDB_AVAILABLE:
        print("--- Skipping LanceDBMemoryProvider tests: lancedb not installed ---")
        return

    temp_dir = tempfile.mkdtemp()
    print(f"\n--- Testing LanceDBMemoryProvider ---")
    print(f"Temporary directory: {temp_dir}")

    config = {
        "storage_path": temp_dir,
        "table_name": "test_lance_table",
    }
    provider = LanceMemoryProvider(config)
    await provider.initialize()

    try:
        await test_add_and_get_memory(provider)
        await test_vector_search(provider)
        await test_delete_memory(provider)
        await test_update_memory(provider)
        print("--- All LanceDBMemoryProvider tests passed! ---")
    except Exception as e:
        print(f"XXX Test failed: {e} XXX")
    finally:
        await provider.close()
        # Add a small delay for file handles to be released
        time.sleep(0.1)
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"Cleaned up temporary directory: {temp_dir}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    asyncio.run(main()) 