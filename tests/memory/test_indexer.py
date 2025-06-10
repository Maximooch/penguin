"""
Standalone integration test for the IncrementalIndexer.
"""

import asyncio
import shutil
import tempfile
from pathlib import Path

from penguin.memory.indexing.incremental import IncrementalIndexer
from penguin.memory.providers.file_provider import FileMemoryProvider


async def test_initial_sync(indexer: IncrementalIndexer):
    """Test that the initial sync indexes all files in the workspace."""
    print("Running: test_initial_sync")
    provider = indexer.provider
    assert provider._stats["total_memories"] == 0

    await indexer.sync_directory(indexer.workspace_path)
    await indexer._queue.join()

    assert provider._stats["total_memories"] == 4
    
    results = await provider.search_memory("import os")
    assert len(results) > 0
    assert "another.py" in results[0]["metadata"]["path"]
    print("... PASSED")


async def test_resync_no_changes(indexer: IncrementalIndexer):
    """Test that re-syncing with no changes doesn't re-index files."""
    print("Running: test_resync_no_changes")
    # The provider state is carried over from the previous test
    initial_count = indexer.provider._stats["total_memories"]
    assert initial_count > 0

    await indexer.sync_directory(indexer.workspace_path)
    await indexer._queue.join()
    
    # The count should not have changed
    assert indexer.provider._stats["total_memories"] == initial_count
    print("... PASSED")


async def test_modified_file_sync(indexer: IncrementalIndexer, workspace: Path):
    """Test that a modified file is re-indexed."""
    print("Running: test_modified_file_sync")
    readme_path = workspace / "README.md"
    await asyncio.sleep(0.1)
    readme_path.write_text("# My Awesome Project\n\nAn update.")
    
    await indexer.sync_directory(workspace)
    await indexer._queue.join()

    assert indexer.provider._stats["total_memories"] == 5
    results = await indexer.provider.search_memory("Awesome Project")
    assert len(results) > 0
    assert "README.md" in results[0]["metadata"]["path"]
    print("... PASSED")


async def test_new_file_sync(indexer: IncrementalIndexer, workspace: Path):
    """Test that a newly created file is indexed."""
    print("Running: test_new_file_sync")
    (workspace / "new_file.txt").write_text("This is brand new.")
    
    await indexer.sync_directory(workspace)
    await indexer._queue.join()

    assert indexer.provider._stats["total_memories"] == 6
    print("... PASSED")


async def test_deleted_file_sync(indexer: IncrementalIndexer, workspace: Path):
    """Test that deleting a file removes its metadata."""
    print("Running: test_deleted_file_sync")
    file_to_delete = workspace / "data.txt"
    file_to_delete.unlink()
    
    indexer.remove_from_index(str(file_to_delete))
    
    assert str(file_to_delete) not in indexer.metadata.data
    print("... PASSED")


def create_test_workspace():
    """Create a temporary workspace directory with sample files."""
    workspace_dir = tempfile.mkdtemp()
    workspace_path = Path(workspace_dir)
    (workspace_path / "test_script.py").write_text("def main():\n    print('hello')")
    (workspace_path / "README.md").write_text("# My Project\n\nThis is a test.")
    (workspace_path / "data.txt").write_text("some generic text data")
    (workspace_path / "subdir").mkdir()
    (workspace_path / "subdir" / "another.py").write_text("import os")
    return workspace_path


async def main():
    """Main function to run all tests."""
    workspace_path = create_test_workspace()
    print(f"\n--- Testing IncrementalIndexer ---")
    print(f"Temporary workspace: {workspace_path}")

    config = {
        "workspace_path": str(workspace_path),
        "storage_path": str(workspace_path / ".penguin_mem"),
    }
    provider = FileMemoryProvider(config)
    await provider.initialize()
    
    indexer = IncrementalIndexer(provider, config)
    await indexer.start_workers(num_workers=1)

    try:
        await test_initial_sync(indexer)
        await test_resync_no_changes(indexer)
        await test_modified_file_sync(indexer, workspace_path)
        await test_new_file_sync(indexer, workspace_path)
        await test_deleted_file_sync(indexer, workspace_path)
        print("--- All IncrementalIndexer tests passed! ---")
    except Exception as e:
        print(f"XXX Test failed: {e} XXX")
    finally:
        await indexer.stop_workers()
        shutil.rmtree(workspace_path)
        print(f"Cleaned up temporary directory: {workspace_path}")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    asyncio.run(main()) 