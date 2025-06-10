"""
Standalone test script for the FileMemoryProvider.
To run: `python -m penguin.tests.memory.test_file_provider`
"""

import asyncio
import shutil
import tempfile
from pathlib import Path

from penguin.memory.providers.file_provider import FileMemoryProvider

async def test_add_and_get_memory(provider):
    """Test adding a memory and then retrieving it."""
    print("Running: test_add_and_get_memory")
    content = "This is a test memory."
    metadata = {"source": "test"}
    memory_id = await provider.add_memory(content, metadata)
    assert isinstance(memory_id, str)

    retrieved_memory = await provider.get_memory(memory_id)
    assert retrieved_memory is not None
    assert retrieved_memory["id"] == memory_id
    assert retrieved_memory["content"] == content
    assert retrieved_memory["metadata"]["source"] == "test"
    assert "embedding" in retrieved_memory and retrieved_memory["embedding"] is not None
    print("... PASSED")


async def test_vector_search(provider):
    """Test vector search functionality."""
    print("Running: test_vector_search")
    await provider.add_memory("The sky is blue.", {"topic": "colors"})
    await provider.add_memory("The grass is green.", {"topic": "colors"})
    await provider.add_memory("Penguins live in Antarctica.", {"topic": "animals"})

    search_results = await provider.search_memory("What color is the sky?")
    assert len(search_results) > 0
    assert "The sky is blue" in search_results[0]["content"]
    print("... PASSED")


async def test_delete_memory(provider):
    """Test deleting a memory."""
    print("Running: test_delete_memory")
    memory_id = await provider.add_memory("This will be deleted.", {})
    assert await provider.get_memory(memory_id) is not None

    deleted = await provider.delete_memory(memory_id)
    assert deleted is True
    assert await provider.get_memory(memory_id) is None
    print("... PASSED")


async def test_update_memory(provider):
    """Test updating a memory."""
    print("Running: test_update_memory")
    memory_id = await provider.add_memory("Original content.", {})
    
    updated = await provider.update_memory(
        memory_id, content="Updated content.", metadata={"updated": True}
    )
    assert updated is True

    retrieved = await provider.get_memory(memory_id)
    assert retrieved is not None
    assert retrieved["content"] == "Updated content."
    assert retrieved["metadata"]["updated"] is True
    print("... PASSED")


async def main():
    """Main function to run all tests."""
    temp_dir = tempfile.mkdtemp()
    print(f"--- Testing FileMemoryProvider ---")
    print(f"Temporary directory: {temp_dir}")

    config = {
        "storage_path": temp_dir,
        "enable_embeddings": True,
    }
    provider = FileMemoryProvider(config)
    await provider.initialize()

    try:
        await test_add_and_get_memory(provider)
        await test_vector_search(provider)
        await test_delete_memory(provider)
        await test_update_memory(provider)
        print("--- All FileMemoryProvider tests passed! ---")
    except Exception as e:
        print(f"XXX Test failed: {e} XXX")
    finally:
        shutil.rmtree(temp_dir)
        print(f"Cleaned up temporary directory: {temp_dir}")


if __name__ == "__main__":
    # Add project root to path to allow running as script
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    asyncio.run(main()) 