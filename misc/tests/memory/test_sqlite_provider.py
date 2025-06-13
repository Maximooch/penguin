"""
Standalone test script for the SQLiteMemoryProvider.
"""

import asyncio
import shutil
import tempfile
from pathlib import Path

from penguin.memory.providers.sqlite_provider import SQLiteMemoryProvider

async def test_add_and_get_memory(provider):
    print("Running: test_add_and_get_memory")
    content = "This is an SQLite test memory."
    metadata = {"source": "sqlite_test"}
    memory_id = await provider.add_memory(content, metadata)
    assert isinstance(memory_id, str)

    retrieved_memory = await provider.get_memory(memory_id)
    assert retrieved_memory is not None
    assert retrieved_memory["id"] == memory_id
    assert retrieved_memory["content"] == content
    assert retrieved_memory["metadata"]["source"] == "sqlite_test"
    print("... PASSED")

async def test_fts_search(provider):
    print("Running: test_fts_search")
    await provider.add_memory("The quick brown fox jumps over the lazy dog.", {})
    await provider.add_memory("A fast brown dog jumps over a sleeping fox.", {})
    
    search_results = await provider.search_memory("quick", filters={"search_mode": "fts"})
    assert len(search_results) == 1
    assert "quick brown fox" in search_results[0]["content"]
    print("... PASSED")

async def test_vector_search(provider):
    print("Running: test_vector_search")
    await provider.add_memory("The ocean is vast and deep blue.", {})
    await provider.add_memory("The desert is arid and sandy.", {})

    search_results = await provider.search_memory("large body of water", filters={"search_mode": "vector"})
    assert len(search_results) > 0
    assert "ocean" in search_results[0]["content"]
    print("... PASSED")

async def test_delete_memory(provider):
    print("Running: test_delete_memory")
    memory_id = await provider.add_memory("This record will be deleted.", {})
    assert await provider.get_memory(memory_id) is not None

    deleted = await provider.delete_memory(memory_id)
    assert deleted is True
    assert await provider.get_memory(memory_id) is None
    print("... PASSED")

async def test_update_memory(provider):
    print("Running: test_update_memory")
    memory_id = await provider.add_memory("Original SQLite content.", {})
    
    updated = await provider.update_memory(
        memory_id, content="Updated SQLite content.", metadata={"updated": True}
    )
    assert updated is True

    retrieved = await provider.get_memory(memory_id)
    assert retrieved is not None
    assert retrieved["content"] == "Updated SQLite content."
    assert retrieved["metadata"]["updated"] is True
    print("... PASSED")

async def main():
    """Main function to run all tests."""
    temp_dir = tempfile.mkdtemp()
    print(f"\n--- Testing SQLiteMemoryProvider ---")
    print(f"Temporary directory: {temp_dir}")

    config = {
        "storage_path": temp_dir,
        "database_file": "test_memory.db",
        "enable_embeddings": True,
        "enable_fts": True,
    }
    provider = SQLiteMemoryProvider(config)
    await provider.initialize()

    try:
        await test_add_and_get_memory(provider)
        await test_fts_search(provider)
        await test_vector_search(provider)
        await test_delete_memory(provider)
        await test_update_memory(provider)
        print("--- All SQLiteMemoryProvider tests passed! ---")
    except Exception as e:
        print(f"XXX Test failed: {e} XXX")
    finally:
        await provider.close()
        shutil.rmtree(temp_dir)
        print(f"Cleaned up temporary directory: {temp_dir}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    asyncio.run(main()) 