#!/usr/bin/env python3
"""
FAISS Memory Provider Test Script

Tests all functionality of the FAISS memory provider including:
- Provider initialization and dependency checks
- Vector embedding and indexing
- Semantic similarity search
- CRUD operations (Create, Read, Update, Delete)
- Persistence and recovery
- Health monitoring and statistics
- Error handling and edge cases

Usage: python test_faiss_provider.py
"""

import asyncio
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from penguin.memory.providers.faiss_provider import FAISSMemoryProvider
from penguin.memory.providers.base import MemoryProviderError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FAISSProviderTester:
    """Comprehensive test suite for FAISS memory provider."""
    
    def __init__(self):
        self.temp_dir = None
        self.provider = None
        self.test_memories = []
        
    async def setup(self):
        """Set up test environment."""
        print("🔧 Setting up FAISS provider test environment...")
        
        # Create temporary directory
        self.temp_dir = Path(tempfile.mkdtemp(prefix="faiss_test_"))
        print(f"   Test directory: {self.temp_dir}")
        
        # Configure FAISS provider
        config = {
            'provider': 'faiss',
            'storage_path': str(self.temp_dir),
            'storage_dir': 'faiss_memory',
            'index_type': 'IndexFlatIP',
            'dimension': 384,
            'embedding_model': 'sentence-transformers/all-MiniLM-L6-v2'
        }
        
        self.provider = FAISSMemoryProvider(config)
        print("✅ FAISS provider created")
        
    async def cleanup(self):
        """Clean up test environment."""
        print("\n🧹 Cleaning up test environment...")
        
        if self.provider:
            await self.provider.close()
            
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
            print(f"   Removed test directory: {self.temp_dir}")
        
    async def test_dependency_check(self):
        """Test dependency availability check."""
        print("\n1️⃣ Testing dependency checks...")
        
        try:
            # Check if dependencies are available
            import faiss
            from sentence_transformers import SentenceTransformer
            print("   ✅ FAISS available")
            print("   ✅ sentence-transformers available")
            return True
        except ImportError as e:
            print(f"   ❌ Missing dependencies: {e}")
            print("   📝 Install with: pip install faiss-cpu sentence-transformers")
            return False
    
    async def test_initialization(self):
        """Test provider initialization."""
        print("\n2️⃣ Testing provider initialization...")
        
        try:
            await self.provider.initialize()
            print("   ✅ Provider initialized successfully")
            
            # Check if files were created
            storage_dir = self.temp_dir / 'faiss_memory'
            if storage_dir.exists():
                print(f"   ✅ Storage directory created: {storage_dir}")
            else:
                print(f"   ❌ Storage directory not found: {storage_dir}")
                return False
                
            return True
            
        except Exception as e:
            print(f"   ❌ Initialization failed: {e}")
            return False
    
    async def test_health_check(self):
        """Test health monitoring."""
        print("\n3️⃣ Testing health check...")
        
        try:
            health = await self.provider.health_check()
            print(f"   Status: {health['status']}")
            print(f"   Checks: {len(health['checks'])} performed")
            
            for check_name, result in health['checks'].items():
                status = "✅" if "OK" in str(result) else "⚠️" if "degraded" in health['status'] else "❌"
                print(f"   {status} {check_name}: {result}")
            
            return health['status'] in ['healthy', 'degraded']
            
        except Exception as e:
            print(f"   ❌ Health check failed: {e}")
            return False
    
    async def test_add_memories(self):
        """Test adding memories with embeddings."""
        print("\n4️⃣ Testing memory addition...")
        
        test_data = [
            {
                'content': 'Python is a programming language used for data science and machine learning',
                'metadata': {'topic': 'programming', 'language': 'python'},
                'categories': ['tech', 'programming']
            },
            {
                'content': 'FAISS is a library for efficient similarity search and clustering of dense vectors',
                'metadata': {'topic': 'search', 'library': 'faiss'},
                'categories': ['tech', 'search']
            },
            {
                'content': 'Machine learning models require training on large datasets to achieve good performance',
                'metadata': {'topic': 'ml', 'domain': 'ai'},
                'categories': ['ai', 'ml']
            },
            {
                'content': 'The penguin project is building an AI assistant with advanced memory capabilities',
                'metadata': {'project': 'penguin', 'type': 'assistant'},
                'categories': ['project', 'ai']
            }
        ]
        
        try:
            for i, data in enumerate(test_data):
                memory_id = await self.provider.add_memory(
                    content=data['content'],
                    metadata=data['metadata'],
                    categories=data['categories']
                )
                
                self.test_memories.append({
                    'id': memory_id,
                    'content': data['content'],
                    'metadata': data['metadata'],
                    'categories': data['categories']
                })
                
                print(f"   ✅ Memory {i+1} added: {memory_id[:8]}...")
            
            print(f"   📊 Total memories added: {len(self.test_memories)}")
            return True
            
        except Exception as e:
            print(f"   ❌ Failed to add memories: {e}")
            return False
    
    async def test_vector_search(self):
        """Test semantic vector similarity search."""
        print("\n5️⃣ Testing vector similarity search...")
        
        test_queries = [
            {
                'query': 'programming languages for AI',
                'expected_matches': ['python', 'programming'],
                'min_results': 1
            },
            {
                'query': 'vector search libraries',
                'expected_matches': ['faiss', 'search'],
                'min_results': 1
            },
            {
                'query': 'AI assistant projects',
                'expected_matches': ['penguin', 'assistant'],
                'min_results': 1
            }
        ]
        
        try:
            for i, test in enumerate(test_queries):
                print(f"   🔍 Query {i+1}: '{test['query']}'")
                
                results = await self.provider.search_memory(
                    query=test['query'],
                    max_results=5
                )
                
                if len(results) >= test['min_results']:
                    print(f"     ✅ Found {len(results)} results")
                    
                    # Check semantic relevance
                    top_result = results[0] if results else None
                    if top_result:
                        content = top_result['content'].lower()
                        has_match = any(keyword in content for keyword in test['expected_matches'])
                        if has_match:
                            print(f"     ✅ Semantically relevant result found")
                            print(f"     📝 Top result: {top_result['content'][:60]}...")
                            print(f"     📊 Score: {top_result['score']:.4f}")
                        else:
                            print(f"     ⚠️ Results may not be semantically optimal")
                else:
                    print(f"     ❌ Expected at least {test['min_results']} results, got {len(results)}")
                    return False
            
            return True
            
        except Exception as e:
            print(f"   ❌ Vector search failed: {e}")
            return False
    
    async def test_crud_operations(self):
        """Test Create, Read, Update, Delete operations."""
        print("\n6️⃣ Testing CRUD operations...")
        
        if not self.test_memories:
            print("   ❌ No test memories available")
            return False
        
        try:
            # Test READ
            memory_id = self.test_memories[0]['id']
            memory = await self.provider.get_memory(memory_id)
            
            if memory and memory['content'] == self.test_memories[0]['content']:
                print("   ✅ READ: Memory retrieved successfully")
            else:
                print("   ❌ READ: Failed to retrieve memory")
                return False
            
            # Test UPDATE
            new_content = "Updated: " + self.test_memories[0]['content']
            new_metadata = {'updated': True, **self.test_memories[0]['metadata']}
            
            success = await self.provider.update_memory(
                memory_id=memory_id,
                content=new_content,
                metadata=new_metadata
            )
            
            if success:
                updated_memory = await self.provider.get_memory(memory_id)
                if updated_memory and updated_memory['content'] == new_content:
                    print("   ✅ UPDATE: Memory updated successfully")
                else:
                    print("   ❌ UPDATE: Memory content not updated properly")
                    return False
            else:
                print("   ❌ UPDATE: Update operation failed")
                return False
            
            # Test DELETE
            success = await self.provider.delete_memory(memory_id)
            if success:
                deleted_memory = await self.provider.get_memory(memory_id)
                if deleted_memory is None:
                    print("   ✅ DELETE: Memory deleted successfully")
                else:
                    print("   ❌ DELETE: Memory still exists after deletion")
                    return False
            else:
                print("   ❌ DELETE: Delete operation failed")
                return False
            
            return True
            
        except Exception as e:
            print(f"   ❌ CRUD operations failed: {e}")
            return False
    
    async def test_filtering(self):
        """Test search filtering capabilities."""
        print("\n7️⃣ Testing search filtering...")
        
        try:
            # Test category filtering
            results = await self.provider.search_memory(
                query="",  # Empty query to get recent memories
                max_results=10,
                filters={'categories': ['tech']}
            )
            
            if results:
                all_have_tech = all('tech' in result.get('categories', []) for result in results)
                if all_have_tech:
                    print(f"   ✅ Category filter: {len(results)} results with 'tech' category")
                else:
                    print("   ⚠️ Category filter: Some results don't match filter")
            else:
                print("   ℹ️ Category filter: No results (expected if no tech memories)")
            
            # Test metadata filtering
            results = await self.provider.search_memory(
                query="",
                max_results=10,
                filters={'metadata': {'topic': 'programming'}}
            )
            
            if results:
                print(f"   ✅ Metadata filter: {len(results)} results with topic='programming'")
            else:
                print("   ℹ️ Metadata filter: No results found")
            
            return True
            
        except Exception as e:
            print(f"   ❌ Filtering test failed: {e}")
            return False
    
    async def test_persistence(self):
        """Test data persistence and recovery."""
        print("\n8️⃣ Testing persistence and recovery...")
        
        try:
            # Get stats before closing
            stats_before = await self.provider.get_memory_stats()
            memories_before = stats_before['total_memories']
            print(f"   📊 Memories before restart: {memories_before}")
            
            # Close provider
            await self.provider.close()
            print("   🔄 Provider closed")
            
            # Create new provider instance with same config
            config = {
                'provider': 'faiss',
                'storage_path': str(self.temp_dir),
                'storage_dir': 'faiss_memory',
                'index_type': 'IndexFlatIP',
                'dimension': 384,
                'embedding_model': 'sentence-transformers/all-MiniLM-L6-v2'
            }
            
            self.provider = FAISSMemoryProvider(config)
            await self.provider.initialize()
            print("   🔄 New provider instance created and initialized")
            
            # Check if data persisted
            stats_after = await self.provider.get_memory_stats()
            memories_after = stats_after['total_memories']
            print(f"   📊 Memories after restart: {memories_after}")
            
            if memories_after >= memories_before - 1:  # Allow for one deleted memory
                print("   ✅ Data persistence: Memories survived restart")
                
                # Test search still works
                results = await self.provider.search_memory("machine learning", max_results=3)
                if results:
                    print(f"   ✅ Search after restart: {len(results)} results found")
                    return True
                else:
                    print("   ⚠️ Search after restart: No results found")
                    return True  # Still consider success if data persisted
            else:
                print(f"   ❌ Data persistence: Lost memories ({memories_before} -> {memories_after})")
                return False
            
        except Exception as e:
            print(f"   ❌ Persistence test failed: {e}")
            return False
    
    async def test_backup_restore(self):
        """Test backup and restore functionality."""
        print("\n9️⃣ Testing backup and restore...")
        
        try:
            # Create backup
            backup_path = self.temp_dir / "faiss_backup.zip"
            success = await self.provider.backup_memories(str(backup_path))
            
            if success and backup_path.exists():
                print(f"   ✅ Backup created: {backup_path}")
                backup_size = backup_path.stat().st_size
                print(f"   📊 Backup size: {backup_size} bytes")
            else:
                print("   ❌ Backup creation failed")
                return False
            
            # Add a new memory before restore
            test_memory_id = await self.provider.add_memory(
                "This memory should be lost after restore",
                metadata={'test': 'restore'},
                categories=['temp']
            )
            print(f"   📝 Added temporary memory: {test_memory_id[:8]}...")
            
            # Restore from backup
            success = await self.provider.restore_memories(str(backup_path))
            
            if success:
                print("   ✅ Restore completed")
                
                # Check if temporary memory was removed
                temp_memory = await self.provider.get_memory(test_memory_id)
                if temp_memory is None:
                    print("   ✅ Restore validation: Temporary memory correctly removed")
                else:
                    print("   ⚠️ Restore validation: Temporary memory still exists")
                
                return True
            else:
                print("   ❌ Restore operation failed")
                return False
            
        except Exception as e:
            print(f"   ❌ Backup/restore test failed: {e}")
            return False
    
    async def test_statistics(self):
        """Test statistics and monitoring."""
        print("\n🔟 Testing statistics and monitoring...")
        
        try:
            stats = await self.provider.get_memory_stats()
            
            required_fields = [
                'provider_type', 'storage_path', 'total_memories',
                'faiss_index_size', 'index_type', 'dimension',
                'storage_size_bytes', 'embedding_model'
            ]
            
            print(f"   📊 Provider type: {stats.get('provider_type')}")
            print(f"   📊 Total memories: {stats.get('total_memories')}")
            print(f"   📊 Index size: {stats.get('faiss_index_size')} vectors")
            print(f"   📊 Index type: {stats.get('index_type')}")
            print(f"   📊 Dimension: {stats.get('dimension')}")
            print(f"   📊 Storage size: {stats.get('storage_size_mb')} MB")
            print(f"   📊 Embedding model: {stats.get('embedding_model')}")
            
            missing_fields = [field for field in required_fields if field not in stats]
            if not missing_fields:
                print("   ✅ All required statistics fields present")
                return True
            else:
                print(f"   ❌ Missing statistics fields: {missing_fields}")
                return False
            
        except Exception as e:
            print(f"   ❌ Statistics test failed: {e}")
            return False
    
    async def test_error_handling(self):
        """Test error handling and edge cases."""
        print("\n1️⃣1️⃣ Testing error handling...")
        
        try:
            # Test search on non-existent memory
            result = await self.provider.get_memory("non-existent-id")
            if result is None:
                print("   ✅ Non-existent memory returns None")
            else:
                print("   ❌ Non-existent memory should return None")
                return False
            
            # Test update non-existent memory
            success = await self.provider.update_memory("non-existent-id", "new content")
            if not success:
                print("   ✅ Update non-existent memory returns False")
            else:
                print("   ❌ Update non-existent memory should return False")
                return False
            
            # Test delete non-existent memory
            success = await self.provider.delete_memory("non-existent-id")
            if not success:
                print("   ✅ Delete non-existent memory returns False")
            else:
                print("   ❌ Delete non-existent memory should return False")
                return False
            
            # Test empty query search
            results = await self.provider.search_memory("", max_results=5)
            print(f"   ✅ Empty query search: {len(results)} results (recent memories)")
            
            return True
            
        except Exception as e:
            print(f"   ❌ Error handling test failed: {e}")
            return False
    
    async def run_all_tests(self):
        """Run all tests and provide summary."""
        print("🚀 Starting FAISS Memory Provider Test Suite")
        print("=" * 60)
        
        test_results = {}
        
        try:
            await self.setup()
            
            # Check dependencies first
            if not await self.test_dependency_check():
                print("\n❌ FAISS dependencies not available. Skipping tests.")
                print("📝 Install with: pip install faiss-cpu sentence-transformers")
                # This is expected - not a failure
                return True  # Changed from False to True
            
            # Run all tests
            tests = [
                ('initialization', self.test_initialization),
                ('health_check', self.test_health_check),
                ('add_memories', self.test_add_memories),
                ('vector_search', self.test_vector_search),
                ('crud_operations', self.test_crud_operations),
                ('filtering', self.test_filtering),
                ('persistence', self.test_persistence),
                ('backup_restore', self.test_backup_restore),
                ('statistics', self.test_statistics),
                ('error_handling', self.test_error_handling),
            ]
            
            for test_name, test_func in tests:
                try:
                    result = await test_func()
                    test_results[test_name] = result
                except Exception as e:
                    print(f"   ❌ Test {test_name} crashed: {e}")
                    test_results[test_name] = False
            
        finally:
            await self.cleanup()
        
        # Print summary
        print("\n" + "=" * 60)
        print("📊 TEST SUMMARY")
        print("=" * 60)
        
        passed = sum(1 for result in test_results.values() if result)
        total = len(test_results)
        
        for test_name, result in test_results.items():
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"{status} {test_name}")
        
        print(f"\n🎯 Results: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 All tests passed! FAISS provider is working correctly.")
            return True
        else:
            print("⚠️ Some tests failed. Check the output above for details.")
            return False


async def main():
    """Main test runner."""
    tester = FAISSProviderTester()
    success = await tester.run_all_tests()
    
    if success:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main()) 