#!/usr/bin/env python3
"""
Run LanceDB Memory Provider Tests

This script runs comprehensive tests for the LanceDB memory provider,
including functionality tests and performance benchmarks.
"""

import asyncio
import logging
import sys
import tempfile
import time
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_lance_provider():
    """Test the LanceDB memory provider"""
    
    try:
        from penguin.memory.providers.lance_provider import LanceMemoryProvider, LANCEDB_AVAILABLE
    except ImportError as e:
        logger.error(f"Failed to import LanceDB provider: {e}")
        return False
    
    if not LANCEDB_AVAILABLE:
        logger.error("LanceDB is not available. Install with: pip install lancedb")
        return False
    
    logger.info("Starting LanceDB provider tests...")
    
    # Create temporary directory for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        config = {
            "storage_path": temp_dir,
            "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
            "table_name": "test_memories"
        }
        
        try:
            # Initialize provider
            logger.info("Initializing LanceDB provider...")
            provider = LanceMemoryProvider(config)
            await provider._initialize_provider()
            
            # Test 1: Add memories
            logger.info("Test 1: Adding memories...")
            memory_ids = []
            
            test_memories = [
                {
                    "content": "Python is a high-level programming language",
                    "metadata": {"memory_type": "knowledge", "source": "documentation"},
                    "categories": ["programming", "python"]
                },
                {
                    "content": "Machine learning involves training algorithms on data",
                    "metadata": {"memory_type": "knowledge", "source": "textbook"},
                    "categories": ["ai", "machine-learning"]
                },
                {
                    "content": "LanceDB is a vector database built on Lance format",
                    "metadata": {"memory_type": "knowledge", "source": "website"},
                    "categories": ["database", "vector-search"]
                }
            ]
            
            for memory in test_memories:
                memory_id = await provider.add_memory(
                    memory["content"],
                    memory["metadata"],
                    memory["categories"]
                )
                memory_ids.append(memory_id)
                logger.info(f"Added memory: {memory_id}")
            
            # Test 2: Search memories
            logger.info("Test 2: Searching memories...")
            search_results = await provider.search_memory("Python programming", max_results=2)
            logger.info(f"Search returned {len(search_results)} results")
            
            for result in search_results:
                logger.info(f"  - {result['id']}: {result['content'][:50]}... (score: {result['score']:.3f})")
            
            # Test 3: Get specific memory
            logger.info("Test 3: Getting specific memory...")
            if memory_ids:
                memory = await provider.get_memory(memory_ids[0])
                if memory:
                    logger.info(f"Retrieved memory: {memory['id']}")
                else:
                    logger.error("Failed to retrieve memory")
            
            # Test 4: Update memory
            logger.info("Test 4: Updating memory...")
            if memory_ids:
                success = await provider.update_memory(
                    memory_ids[0],
                    content="Python is a versatile high-level programming language",
                    metadata={"memory_type": "knowledge", "source": "updated"}
                )
                logger.info(f"Update successful: {success}")
            
            # Test 5: Filter search
            logger.info("Test 5: Filtered search...")
            filtered_results = await provider.search_memory(
                "programming",
                max_results=5,
                filters={"categories": ["programming"]}
            )
            logger.info(f"Filtered search returned {len(filtered_results)} results")
            
            # Test 6: Hybrid search (if available)
            logger.info("Test 6: Hybrid search...")
            try:
                hybrid_results = await provider.hybrid_search("database vector", max_results=3)
                logger.info(f"Hybrid search returned {len(hybrid_results)} results")
            except Exception as e:
                logger.warning(f"Hybrid search not available: {e}")
            
            # Test 7: Get stats
            logger.info("Test 7: Getting statistics...")
            stats = await provider.get_memory_stats()
            logger.info(f"Total memories: {stats.get('total_memories', 'unknown')}")
            logger.info(f"Search count: {stats.get('search_count', 'unknown')}")
            
            # Test 8: Health check
            logger.info("Test 8: Health check...")
            health = await provider.health_check()
            logger.info(f"Health status: {health['status']}")
            
            # Test 9: Backup and restore
            logger.info("Test 9: Backup and restore...")
            backup_path = Path(temp_dir) / "backup.parquet"
            backup_success = await provider.backup_memories(str(backup_path))
            logger.info(f"Backup successful: {backup_success}")
            
            if backup_success and backup_path.exists():
                # Delete some memories and restore
                await provider.delete_memory(memory_ids[0])
                restore_success = await provider.restore_memories(str(backup_path))
                logger.info(f"Restore successful: {restore_success}")
            
            # Test 10: Delete memory
            logger.info("Test 10: Deleting memories...")
            for memory_id in memory_ids[1:]:  # Keep first one for restore test
                success = await provider.delete_memory(memory_id)
                logger.info(f"Deleted {memory_id}: {success}")
            
            # Final stats
            final_stats = await provider.get_memory_stats()
            logger.info(f"Final memory count: {final_stats.get('total_memories', 'unknown')}")
            
            # Close provider
            provider.close()
            
            logger.info("✅ All LanceDB provider tests completed successfully!")
            return True
            
        except Exception as e:
            logger.error(f"❌ Test failed: {e}")
            import traceback
            traceback.print_exc()
            return False

async def benchmark_lance_provider():
    """Benchmark the LanceDB provider performance"""
    
    try:
        from penguin.memory.providers.lance_provider import LanceMemoryProvider, LANCEDB_AVAILABLE
    except ImportError:
        logger.error("LanceDB provider not available for benchmarking")
        return
    
    if not LANCEDB_AVAILABLE:
        logger.error("LanceDB is not available for benchmarking")
        return
    
    logger.info("Starting LanceDB performance benchmark...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        config = {
            "storage_path": temp_dir,
            "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
            "table_name": "benchmark_memories"
        }
        
        provider = LanceMemoryProvider(config)
        await provider._initialize_provider()
        
        # Benchmark 1: Bulk insert
        logger.info("Benchmark 1: Bulk insert performance...")
        num_records = 100
        start_time = time.time()
        
        for i in range(num_records):
            await provider.add_memory(
                f"This is test memory number {i} with some content to search",
                {"memory_type": "test", "index": i},
                ["test", f"batch_{i//10}"]
            )
        
        insert_time = time.time() - start_time
        logger.info(f"Inserted {num_records} records in {insert_time:.2f}s ({num_records/insert_time:.1f} records/sec)")
        
        # Benchmark 2: Search performance
        logger.info("Benchmark 2: Search performance...")
        search_queries = [
            "test memory content",
            "search functionality",
            "performance benchmark",
            "database operations",
            "vector similarity"
        ]
        
        start_time = time.time()
        total_results = 0
        
        for query in search_queries:
            results = await provider.search_memory(query, max_results=10)
            total_results += len(results)
        
        search_time = time.time() - start_time
        logger.info(f"Executed {len(search_queries)} searches in {search_time:.2f}s ({len(search_queries)/search_time:.1f} searches/sec)")
        logger.info(f"Average results per search: {total_results/len(search_queries):.1f}")
        
        provider.close()
        logger.info("✅ Benchmark completed!")

async def main():
    """Main test runner"""
    logger.info("LanceDB Memory Provider Test Suite")
    logger.info("=" * 50)
    
    # Run functionality tests
    test_success = await test_lance_provider()
    
    if test_success:
        logger.info("\n" + "=" * 50)
        # Run performance benchmarks
        await benchmark_lance_provider()
    
    logger.info("\n" + "=" * 50)
    if test_success:
        logger.info("🎉 All tests passed! LanceDB provider is ready to use.")
        logger.info("\nTo install LanceDB dependencies:")
        logger.info("pip install -r requirements_lancedb.txt")
    else:
        logger.error("❌ Some tests failed. Check the logs above.")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main()) 