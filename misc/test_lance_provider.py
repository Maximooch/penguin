"""
Test suite for LanceDB Memory Provider

This test suite verifies the functionality of the LanceDB memory provider,
including basic operations, search capabilities, and error handling.
"""

import asyncio
import os
import tempfile
import pytest
from pathlib import Path
from datetime import datetime

# Import the provider
try:
    from penguin.memory.providers.lance_provider import LanceMemoryProvider, LANCEDB_AVAILABLE
except ImportError:
    LANCEDB_AVAILABLE = False


@pytest.mark.skipif(not LANCEDB_AVAILABLE, reason="LanceDB not available")
class TestLanceMemoryProvider:
    """Test suite for LanceDB Memory Provider"""
    
    @pytest.fixture
    async def provider(self):
        """Create a test provider instance"""
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = LanceMemoryProvider(
                storage_path=temp_dir,
                embedding_model="sentence-transformers/all-MiniLM-L6-v2",
                table_name="test_memories"
            )
            yield provider
            provider.close()
    
    async def test_initialization(self):
        """Test provider initialization"""
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = LanceMemoryProvider(
                storage_path=temp_dir,
                embedding_model="sentence-transformers/all-MiniLM-L6-v2"
            )
            
            assert provider.storage_path == Path(temp_dir)
            assert provider.embedding_model == "sentence-transformers/all-MiniLM-L6-v2"
            assert provider.table_name == "memory_records"
            
            provider.close()
    
    async def test_add_memory(self, provider):
        """Test adding memory records"""
        # Add a simple memory
        memory_id = await provider.add_memory(
            content="This is a test memory about Python programming",
            metadata={
                "memory_type": "code",
                "source": "test",
                "file_path": "/test/file.py"
            },
            categories=["programming", "python"]
        )
        
        assert memory_id is not None
        assert memory_id.startswith("mem_")
        
        # Verify stats updated
        stats = await provider.get_memory_stats()
        assert stats["total_memories"] >= 1
    
    async def test_search_memory(self, provider):
        """Test memory search functionality"""
        # Add some test memories
        await provider.add_memory(
            content="Python is a programming language",
            metadata={"memory_type": "code", "source": "test1"},
            categories=["programming", "python"]
        )
        
        await provider.add_memory(
            content="JavaScript is used for web development",
            metadata={"memory_type": "code", "source": "test2"},
            categories=["programming", "javascript"]
        )
        
        await provider.add_memory(
            content="Machine learning with neural networks",
            metadata={"memory_type": "ai", "source": "test3"},
            categories=["ai", "ml"]
        )
        
        # Search for Python-related content
        results = await provider.search_memory("Python programming", max_results=5)
        
        assert len(results) > 0
        assert any("Python" in result["content"] for result in results)
        
        # Verify result structure
        for result in results:
            assert "memory_id" in result
            assert "content" in result
            assert "metadata" in result
            assert "score" in result
            assert "relevance" in result
    
    async def test_search_with_filters(self, provider):
        """Test memory search with filters"""
        # Add memories with different types
        await provider.add_memory(
            content="Python code example",
            metadata={"memory_type": "code", "source": "test"},
            categories=["programming"]
        )
        
        await provider.add_memory(
            content="AI research notes",
            metadata={"memory_type": "research", "source": "test"},
            categories=["ai"]
        )
        
        # Search with memory_type filter
        results = await provider.search_memory(
            "example",
            max_results=5,
            filters={"memory_type": "code"}
        )
        
        assert len(results) > 0
        for result in results:
            assert result["metadata"]["memory_type"] == "code"
        
        # Search with categories filter
        results = await provider.search_memory(
            "notes",
            max_results=5,
            filters={"categories": ["ai"]}
        )
        
        assert len(results) > 0
        for result in results:
            assert "ai" in result["metadata"]["categories"]
    
    async def test_delete_memory(self, provider):
        """Test memory deletion"""
        # Add a memory
        memory_id = await provider.add_memory(
            content="Memory to be deleted",
            metadata={"memory_type": "test"},
            categories=["test"]
        )
        
        # Delete the memory
        success = await provider.delete_memory(memory_id)
        assert success is True
        
        # Try to search for the deleted memory
        results = await provider.search_memory("Memory to be deleted")
        assert len(results) == 0 or not any(
            result["memory_id"] == memory_id for result in results
        )
    
    async def test_update_memory(self, provider):
        """Test memory update functionality"""
        # Add a memory
        memory_id = await provider.add_memory(
            content="Original content",
            metadata={"memory_type": "test", "version": 1},
            categories=["test"]
        )
        
        # Update the memory
        success = await provider.update_memory(
            memory_id,
            content="Updated content",
            metadata={"memory_type": "test", "version": 2, "categories": ["test", "updated"]}
        )
        
        assert success is True
        
        # Search for updated content
        results = await provider.search_memory("Updated content")
        assert len(results) > 0
        assert any("Updated content" in result["content"] for result in results)
    
    async def test_backup_and_restore(self, provider):
        """Test backup and restore functionality"""
        # Add some test data
        await provider.add_memory(
            content="Backup test memory 1",
            metadata={"memory_type": "backup_test"},
            categories=["backup"]
        )
        
        await provider.add_memory(
            content="Backup test memory 2",
            metadata={"memory_type": "backup_test"},
            categories=["backup"]
        )
        
        # Create backup
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as backup_file:
            backup_path = backup_file.name
        
        try:
            success = await provider.backup_memories(backup_path)
            assert success is True
            assert os.path.exists(backup_path)
            
            # Create new provider and restore
            with tempfile.TemporaryDirectory() as new_temp_dir:
                new_provider = LanceMemoryProvider(
                    storage_path=new_temp_dir,
                    table_name="restored_memories"
                )
                
                success = await new_provider.restore_memories(backup_path)
                assert success is True
                
                # Verify restored data
                results = await new_provider.search_memory("Backup test")
                assert len(results) >= 2
                
                new_provider.close()
        
        finally:
            if os.path.exists(backup_path):
                os.unlink(backup_path)
    
    async def test_health_check(self, provider):
        """Test health check functionality"""
        health = await provider.health_check()
        
        assert health["provider"] == "lancedb"
        assert health["status"] in ["healthy", "warning", "unhealthy"]
        assert "checks" in health
        assert "timestamp" in health
        
        # Check individual health checks
        checks = health["checks"]
        assert "database_connection" in checks
        assert "table_access" in checks
        assert "storage_path" in checks
    
    async def test_memory_stats(self, provider):
        """Test memory statistics"""
        # Add some memories
        for i in range(3):
            await provider.add_memory(
                content=f"Test memory {i}",
                metadata={"memory_type": "stats_test"},
                categories=["stats"]
            )
        
        stats = await provider.get_memory_stats()
        
        assert stats["provider"] == "lancedb"
        assert stats["total_memories"] >= 3
        assert "storage_path" in stats
        assert "table_name" in stats
        assert "embedding_model" in stats
        assert "search_count" in stats
    
    async def test_hybrid_search(self, provider):
        """Test hybrid search functionality"""
        # Add some test data
        await provider.add_memory(
            content="Python programming tutorial",
            metadata={"memory_type": "tutorial"},
            categories=["programming", "python"]
        )
        
        await provider.add_memory(
            content="Advanced Python concepts",
            metadata={"memory_type": "advanced"},
            categories=["programming", "python"]
        )
        
        # Perform hybrid search
        results = await provider.hybrid_search(
            "Python tutorial",
            max_results=5
        )
        
        assert len(results) > 0
        
        # Verify result structure
        for result in results:
            assert "memory_id" in result
            assert "content" in result
            assert "metadata" in result
            assert "score" in result
            assert "relevance" in result
    
    async def test_error_handling(self, provider):
        """Test error handling"""
        # Test search with invalid query
        results = await provider.search_memory("")
        assert isinstance(results, list)
        
        # Test delete non-existent memory
        success = await provider.delete_memory("non_existent_id")
        # Should handle gracefully (may return True or False depending on implementation)
        assert isinstance(success, bool)
        
        # Test backup to invalid path
        success = await provider.backup_memories("/invalid/path/backup.parquet")
        assert success is False
        
        # Test restore from non-existent file
        success = await provider.restore_memories("/non/existent/file.parquet")
        assert success is False


async def run_basic_test():
    """Run a basic test without pytest"""
    print("Testing LanceDB Memory Provider...")
    
    if not LANCEDB_AVAILABLE:
        print("❌ LanceDB not available. Install with: pip install lancedb")
        return
    
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            # Initialize provider
            provider = LanceMemoryProvider(
                storage_path=temp_dir,
                embedding_model="sentence-transformers/all-MiniLM-L6-v2"
            )
            print("✅ Provider initialized successfully")
            
            # Add a memory
            memory_id = await provider.add_memory(
                content="This is a test memory about LanceDB integration",
                metadata={"memory_type": "test", "source": "basic_test"},
                categories=["test", "lancedb"]
            )
            print(f"✅ Memory added with ID: {memory_id}")
            
            # Search for the memory
            results = await provider.search_memory("LanceDB integration")
            print(f"✅ Search returned {len(results)} results")
            
            if results:
                print(f"   First result: {results[0]['content'][:50]}...")
                print(f"   Relevance: {results[0]['relevance']:.2f}")
            
            # Get stats
            stats = await provider.get_memory_stats()
            print(f"✅ Stats: {stats['total_memories']} memories stored")
            
            # Health check
            health = await provider.health_check()
            print(f"✅ Health check: {health['status']}")
            
            provider.close()
            print("✅ All basic tests passed!")
            
        except Exception as e:
            print(f"❌ Test failed: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    # Run basic test
    asyncio.run(run_basic_test()) 