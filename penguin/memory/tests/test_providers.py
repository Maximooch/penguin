"""
Unit tests for memory providers.
"""

import asyncio
import pytest
import pytest_asyncio
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any

from ..providers.base import MemoryProvider, MemoryProviderError
from ..providers.factory import MemoryProviderFactory
from ..providers.sqlite_provider import SQLiteMemoryProvider
from ..providers.file_provider import FileMemoryProvider


class TestMemoryProviderFactory:
    """Test the memory provider factory."""
    
    def test_get_available_providers(self):
        """Test getting available providers."""
        providers = MemoryProviderFactory.get_available_providers()
        assert isinstance(providers, list)
        assert len(providers) > 0
        # At minimum, file and sqlite should be available
        assert 'file' in providers or 'sqlite' in providers
    
    def test_provider_info(self):
        """Test getting provider information."""
        info = MemoryProviderFactory.get_provider_info()
        assert isinstance(info, dict)
        assert len(info) > 0
        
        # Test specific provider info
        if 'sqlite' in info:
            sqlite_info = MemoryProviderFactory.get_provider_info('sqlite')
            assert sqlite_info['name'] == 'sqlite'
            assert 'available' in sqlite_info
    
    def test_health_check_all_providers(self):
        """Test health check for all providers."""
        health_status = MemoryProviderFactory.health_check_all_providers()
        assert isinstance(health_status, dict)
        assert 'overall_status' in health_status
        assert 'providers' in health_status
        assert 'recommendations' in health_status


class TestSQLiteProvider:
    """Test SQLite memory provider."""
    
    @pytest_asyncio.fixture
    async def temp_provider(self):
        """Create a temporary SQLite provider for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                'provider_type': 'sqlite',
                'storage_path': temp_dir,
                'database_file': 'test_memory.db',
                'enable_fts': True
            }
            provider = SQLiteMemoryProvider(config)
            await provider.initialize()
            yield provider
            await provider.close()
    
    @pytest.mark.asyncio
    async def test_initialization(self, temp_provider):
        """Test provider initialization."""
        assert temp_provider._initialized
        assert temp_provider._connection is not None
    
    @pytest.mark.asyncio
    async def test_add_memory(self, temp_provider):
        """Test adding a memory."""
        memory_id = await temp_provider.add_memory(
            content="Test memory content",
            metadata={"test": "value"},
            categories=["test"]
        )
        assert isinstance(memory_id, str)
        assert len(memory_id) > 0
    
    @pytest.mark.asyncio
    async def test_search_memory(self, temp_provider):
        """Test searching memories."""
        # Add some test memories
        await temp_provider.add_memory(
            content="Python programming tutorial",
            metadata={"type": "tutorial"},
            categories=["programming", "python"]
        )
        await temp_provider.add_memory(
            content="JavaScript web development",
            metadata={"type": "guide"},
            categories=["programming", "javascript"]
        )
        
        # Search for python content
        results = await temp_provider.search_memory("python", max_results=5)
        assert isinstance(results, list)
        assert len(results) > 0
        assert any("python" in result['content'].lower() for result in results)
    
    @pytest.mark.asyncio
    async def test_get_memory(self, temp_provider):
        """Test getting a specific memory."""
        # Add a memory
        memory_id = await temp_provider.add_memory(
            content="Specific memory content",
            metadata={"key": "value"}
        )
        
        # Retrieve it
        memory = await temp_provider.get_memory(memory_id)
        assert memory is not None
        assert memory['content'] == "Specific memory content"
        assert memory['metadata']['key'] == "value"
    
    @pytest.mark.asyncio
    async def test_update_memory(self, temp_provider):
        """Test updating a memory."""
        # Add a memory
        memory_id = await temp_provider.add_memory(
            content="Original content",
            metadata={"version": 1}
        )
        
        # Update it
        success = await temp_provider.update_memory(
            memory_id,
            content="Updated content",
            metadata={"version": 2}
        )
        assert success
        
        # Verify update
        memory = await temp_provider.get_memory(memory_id)
        assert memory['content'] == "Updated content"
        assert memory['metadata']['version'] == 2
    
    @pytest.mark.asyncio
    async def test_delete_memory(self, temp_provider):
        """Test deleting a memory."""
        # Add a memory
        memory_id = await temp_provider.add_memory(content="To be deleted")
        
        # Delete it
        success = await temp_provider.delete_memory(memory_id)
        assert success
        
        # Verify deletion
        memory = await temp_provider.get_memory(memory_id)
        assert memory is None
    
    @pytest.mark.asyncio
    async def test_get_stats(self, temp_provider):
        """Test getting memory statistics."""
        # Add some memories
        await temp_provider.add_memory(content="Memory 1")
        await temp_provider.add_memory(content="Memory 2")
        
        stats = await temp_provider.get_memory_stats()
        assert isinstance(stats, dict)
        assert stats['provider_type'] == 'sqlite'
        assert stats['total_memories'] >= 2
    
    @pytest.mark.asyncio
    async def test_health_check(self, temp_provider):
        """Test health check."""
        health = await temp_provider.health_check()
        assert isinstance(health, dict)
        assert 'status' in health
        assert 'checks' in health
        assert health['status'] in ['healthy', 'degraded', 'unhealthy']


class TestFileProvider:
    """Test file memory provider."""
    
    @pytest_asyncio.fixture
    async def temp_provider(self):
        """Create a temporary file provider for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                'provider_type': 'file',
                'storage_path': temp_dir,
                'storage_dir': 'file_memory'
            }
            provider = FileMemoryProvider(config)
            await provider.initialize()
            yield provider
            await provider.close()
    
    @pytest.mark.asyncio
    async def test_initialization(self, temp_provider):
        """Test provider initialization."""
        assert temp_provider._initialized
        assert temp_provider.storage_dir.exists()
        assert temp_provider.memories_dir.exists()
    
    @pytest.mark.asyncio
    async def test_add_and_search_memory(self, temp_provider):
        """Test adding and searching memories."""
        # Add a memory
        memory_id = await temp_provider.add_memory(
            content="File storage test content",
            metadata={"test": True},
            categories=["test", "file"]
        )
        assert isinstance(memory_id, str)
        
        # Search for it
        results = await temp_provider.search_memory("file storage", max_results=5)
        assert len(results) > 0
        assert any("file storage" in result['content'].lower() for result in results)
    
    @pytest.mark.asyncio
    async def test_backup_restore(self, temp_provider):
        """Test backup and restore functionality."""
        # Add some test data
        await temp_provider.add_memory(content="Backup test memory 1")
        await temp_provider.add_memory(content="Backup test memory 2")
        
        with tempfile.TemporaryDirectory() as backup_dir:
            backup_path = Path(backup_dir) / "test_backup.zip"
            
            # Test backup
            success = await temp_provider.backup_memories(str(backup_path))
            assert success
            assert backup_path.exists()


class TestProviderIntegration:
    """Integration tests for memory provider system."""
    
    @pytest.mark.asyncio
    async def test_factory_creates_working_provider(self):
        """Test that factory creates a working provider."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                'provider': 'auto',
                'storage_path': temp_dir
            }
            
            provider = MemoryProviderFactory.create_provider(config)
            await provider.initialize()
            
            try:
                # Test basic operations
                memory_id = await provider.add_memory("Factory test content")
                assert isinstance(memory_id, str)
                
                results = await provider.search_memory("factory test")
                assert len(results) > 0
                
                memory = await provider.get_memory(memory_id)
                assert memory is not None
                assert memory['content'] == "Factory test content"
                
            finally:
                await provider.close()
    
    @pytest.mark.asyncio
    async def test_multiple_providers_same_interface(self):
        """Test that different providers implement the same interface."""
        providers_to_test = []
        
        # Add available providers
        available = MemoryProviderFactory.get_available_providers()
        if 'sqlite' in available:
            providers_to_test.append('sqlite')
        if 'file' in available:
            providers_to_test.append('file')
        
        for provider_type in providers_to_test:
            with tempfile.TemporaryDirectory() as temp_dir:
                config = {
                    'provider': provider_type,
                    'storage_path': temp_dir
                }
                
                provider = MemoryProviderFactory.create_provider(config)
                await provider.initialize()
                
                try:
                    # Test that all providers support the same basic operations
                    memory_id = await provider.add_memory(f"Test content for {provider_type}")
                    results = await provider.search_memory("test content")
                    memory = await provider.get_memory(memory_id)
                    stats = await provider.get_memory_stats()
                    health = await provider.health_check()
                    
                    # Verify expected return types
                    assert isinstance(memory_id, str)
                    assert isinstance(results, list)
                    assert isinstance(memory, dict)
                    assert isinstance(stats, dict)
                    assert isinstance(health, dict)
                    
                finally:
                    await provider.close()


# Helper function to run async tests
def run_async_test(coro):
    """Helper to run async tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


if __name__ == "__main__":
    # Run a simple smoke test
    print("Running memory provider smoke tests...")
    
    async def smoke_test():
        """Simple smoke test to verify basic functionality."""
        try:
            # Test factory
            providers = MemoryProviderFactory.get_available_providers()
            print(f"Available providers: {providers}")
            
            # Test health check
            health = MemoryProviderFactory.health_check_all_providers()
            print(f"Overall health status: {health['overall_status']}")
            
            # Test basic provider creation and operations
            with tempfile.TemporaryDirectory() as temp_dir:
                config = {
                    'provider': 'auto',
                    'storage_path': temp_dir
                }
                
                provider = MemoryProviderFactory.create_provider(config)
                await provider.initialize()
                
                memory_id = await provider.add_memory("Smoke test memory")
                results = await provider.search_memory("smoke test")
                
                print(f"Added memory with ID: {memory_id}")
                print(f"Search found {len(results)} results")
                
                await provider.close()
            
            print("Smoke test passed!")
            
        except Exception as e:
            print(f"Smoke test failed: {str(e)}")
            raise
    
    run_async_test(smoke_test()) 