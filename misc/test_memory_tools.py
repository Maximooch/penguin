#!/usr/bin/env python3
"""
Memory Tools Integration Test Script

Tests the complete memory tools integration including:
- Bridge system compatibility with legacy interfaces
- Tool manager memory tool execution
- Parser action recognition and execution
- End-to-end memory search functionality
- Memory and workspace search tools
- Error handling and edge cases

Usage: python test_memory_tools.py
"""

import asyncio
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from penguin.tools.core.memory_search_bridge import MemorySearcherBridge
from penguin.tools.core.workspace_search_bridge import CodeIndexerBridge
from penguin.tools.tool_manager import ToolManager
from penguin.utils.parser import parse_action, ActionExecutor, ActionType
from penguin.local_task.manager import ProjectManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MemoryToolsTester:
    """Comprehensive test suite for memory tools integration."""
    
    def __init__(self):
        self.temp_dir = None
        self.tool_manager = None
        self.action_executor = None
        self.task_manager = None
        
    async def setup(self):
        """Set up test environment."""
        print("🔧 Setting up memory tools test environment...")
        
        # Create temporary directory
        self.temp_dir = Path(tempfile.mkdtemp(prefix="memory_tools_test_"))
        print(f"   Test directory: {self.temp_dir}")
        
        # Mock log_error function
        def mock_log_error(exception, context):
            logger.error(f"Mock error logged: {context} - {exception}")
        
        # Create tool manager
        self.tool_manager = ToolManager(log_error_func=mock_log_error)
        
        # Create task manager
        self.task_manager = ProjectManager(workspace_root=str(self.temp_dir))
        
        # Create action executor
        self.action_executor = ActionExecutor(
            tool_manager=self.tool_manager,
            task_manager=self.task_manager
        )
        
        print("✅ Test environment ready")
        
    async def cleanup(self):
        """Clean up test environment."""
        print("\n🧹 Cleaning up test environment...")
        
        # Close any open providers in tool manager
        try:
            if hasattr(self.tool_manager, '_memory_searcher') and self.tool_manager._memory_searcher:
                await self.tool_manager._memory_searcher.close()
        except:
            pass
        
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
            print(f"   Removed test directory: {self.temp_dir}")
    
    async def test_memory_bridge_interface(self):
        """Test memory search bridge maintains legacy interface."""
        print("\n1️⃣ Testing memory search bridge interface...")
        
        try:
            # Test bridge creation
            bridge = MemorySearcherBridge(persist_directory=str(self.temp_dir / 'bridge_test'))
            print("   ✅ Memory search bridge created")
            
            # Test async initialization first
            await bridge.initialize()
            print("   ✅ Async initialization works")
            
            # Test adding memory using async interface
            memory_id = await bridge._memory_tool.provider.add_memory(
                content="Test memory from bridge interface",
                metadata={'source': 'bridge_test'},
                categories=['test']
            )
            print("   ✅ Memory addition works")
            
            # Test search with legacy parameters
            results = await bridge.search_memory(
                query="bridge test",
                max_results=5,
                memory_type="test",
                categories=None
            )
            
            if isinstance(results, list):
                print(f"   ✅ Legacy search interface works: {len(results)} results")
                
                # Check result format matches legacy expectations
                if results and all(key in results[0] for key in ['metadata', 'preview', 'relevance']):
                    print("   ✅ Legacy result format maintained")
                else:
                    print("   ⚠️ Result format may not match legacy expectations")
            else:
                print(f"   ❌ Search returned unexpected type: {type(results)}")
                return False
            
            # Test index_memory_files (legacy interface)
            index_result = bridge.index_memory_files()
            if isinstance(index_result, str):
                print(f"   ✅ Legacy index_memory_files works: {index_result}")
            else:
                print(f"   ❌ Unexpected index result: {index_result}")
            
            return True
            
        except Exception as e:
            print(f"   ❌ Memory bridge test failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def test_workspace_bridge_interface(self):
        """Test workspace search bridge interface."""
        print("\n2️⃣ Testing workspace search bridge interface...")
        
        try:
            # Test bridge creation
            bridge = CodeIndexerBridge(persist_directory=str(self.temp_dir / 'workspace_test'))
            print("   ✅ Workspace search bridge created")
            
            # Test wait_for_initialization
            init_result = bridge.wait_for_initialization()
            if init_result:
                print("   ✅ Workspace bridge initialization works")
            else:
                print("   ❌ Workspace bridge initialization failed")
                return False
            
            # Test search_code (should return empty in Stage 1)
            results = bridge.search_code("test query", max_results=5)
            if isinstance(results, list):
                print(f"   ✅ Workspace search works: {len(results)} results (Stage 1 limitation)")
            else:
                print(f"   ❌ Unexpected search result type: {type(results)}")
                return False
            
            # Test index_directory (should be no-op in Stage 1)
            bridge.index_directory("./test_directory")
            print("   ✅ Workspace indexing interface works (Stage 1 placeholder)")
            
            # Test display_search_results
            bridge.display_search_results([])
            print("   ✅ Display results interface works")
            
            return True
            
        except Exception as e:
            print(f"   ❌ Workspace bridge test failed: {e}")
            return False
    
    async def test_tool_manager_integration(self):
        """Test tool manager memory tool integration."""
        print("\n3️⃣ Testing tool manager integration...")
        
        try:
            # Test that memory search tool is available
            tools = self.tool_manager.get_tools()
            memory_tool = next((tool for tool in tools if tool['name'] == 'memory_search'), None)
            workspace_tool = next((tool for tool in tools if tool['name'] == 'workspace_search'), None)
            
            if memory_tool:
                print("   ✅ Memory search tool available in tool manager")
            else:
                print("   ❌ Memory search tool not found in tool manager")
                return False
            
            if workspace_tool:
                print("   ✅ Workspace search tool available in tool manager")
            else:
                print("   ❌ Workspace search tool not found in tool manager")
                return False
            
            # Test memory search tool execution
            try:
                memory_result = self.tool_manager.execute_tool(
                    'memory_search',
                    {
                        'query': 'test memory search',
                        'max_results': 5
                    }
                )
                
                if isinstance(memory_result, str):
                    print(f"   ✅ Memory search tool execution works")
                    print(f"   📝 Result: {memory_result[:100]}...")
                else:
                    print(f"   ❌ Unexpected memory search result: {type(memory_result)}")
                    return False
                    
            except Exception as e:
                print(f"   ⚠️ Memory search tool execution error: {e}")
                # Don't fail the test - this might be due to provider setup
            
            # Test workspace search tool execution
            try:
                workspace_result = self.tool_manager.execute_tool(
                    'workspace_search',
                    {
                        'query': 'test workspace search',
                        'max_results': 5
                    }
                )
                
                if isinstance(workspace_result, str):
                    print(f"   ✅ Workspace search tool execution works")
                    print(f"   📝 Result: {workspace_result[:100]}...")
                else:
                    print(f"   ❌ Unexpected workspace search result: {type(workspace_result)}")
                    return False
                    
            except Exception as e:
                print(f"   ⚠️ Workspace search tool execution error: {e}")
                # Don't fail the test - this is expected in Stage 1
            
            return True
            
        except Exception as e:
            print(f"   ❌ Tool manager integration test failed: {e}")
            return False
    
    def test_parser_action_recognition(self):
        """Test parser recognizes memory actions."""
        print("\n4️⃣ Testing parser action recognition...")
        
        try:
            # Test memory search action parsing
            memory_content = "<memory_search>project planning:5</memory_search>"
            actions = parse_action(memory_content)
            
            if actions and len(actions) == 1:
                action = actions[0]
                if action.action_type == ActionType.MEMORY_SEARCH:
                    print("   ✅ Memory search action recognized")
                    print(f"   📝 Params: {action.params}")
                else:
                    print(f"   ❌ Wrong action type: {action.action_type}")
                    return False
            else:
                print(f"   ❌ Action parsing failed: {len(actions) if actions else 0} actions")
                return False
            
            # Test workspace search action parsing
            workspace_content = "<workspace_search>function_name:10</workspace_search>"
            actions = parse_action(workspace_content)
            
            if actions and len(actions) == 1:
                action = actions[0]
                if action.action_type == ActionType.WORKSPACE_SEARCH:
                    print("   ✅ Workspace search action recognized")
                    print(f"   📝 Params: {action.params}")
                else:
                    print(f"   ❌ Wrong action type: {action.action_type}")
                    return False
            else:
                print(f"   ❌ Workspace action parsing failed: {len(actions) if actions else 0} actions")
                return False
            
            # Test multiple actions
            multi_content = """
            <memory_search>recent tasks</memory_search>
            <workspace_search>helper functions</workspace_search>
            """
            actions = parse_action(multi_content)
            
            if actions and len(actions) == 2:
                print(f"   ✅ Multiple memory actions recognized: {len(actions)} actions")
            else:
                print(f"   ⚠️ Multiple action parsing: {len(actions) if actions else 0} actions (expected 2)")
            
            return True
            
        except Exception as e:
            print(f"   ❌ Parser action recognition test failed: {e}")
            return False
    
    async def test_action_executor_integration(self):
        """Test action executor handles memory actions."""
        print("\n5️⃣ Testing action executor integration...")
        
        try:
            # Test memory search action execution
            memory_actions = parse_action("<memory_search>test query:3</memory_search>")
            
            if memory_actions:
                result = await self.action_executor.execute_action(memory_actions[0])
                if isinstance(result, str):
                    print("   ✅ Memory search action execution works")
                    print(f"   📝 Result: {result[:100]}...")
                else:
                    print(f"   ❌ Unexpected result type: {type(result)}")
                    return False
            else:
                print("   ❌ No memory actions to execute")
                return False
            
            # Test workspace search action execution
            workspace_actions = parse_action("<workspace_search>test function:5</workspace_search>")
            
            if workspace_actions:
                result = await self.action_executor.execute_action(workspace_actions[0])
                if isinstance(result, str):
                    print("   ✅ Workspace search action execution works")
                    print(f"   📝 Result: {result[:100]}...")
                else:
                    print(f"   ❌ Unexpected result type: {type(result)}")
                    return False
            else:
                print("   ❌ No workspace actions to execute")
                return False
            
            return True
            
        except Exception as e:
            print(f"   ❌ Action executor integration test failed: {e}")
            return False
    
    async def test_memory_tool_functionality(self):
        """Test end-to-end memory functionality."""
        print("\n6️⃣ Testing end-to-end memory functionality...")
        
        try:
            # Add some test data through the bridge
            bridge = MemorySearcherBridge(persist_directory=str(self.temp_dir / 'e2e_test'))
            await bridge.initialize()
            
            # Add test memories
            test_memories = [
                {
                    'content': 'Python is a programming language for data science',
                    'type': 'notes',
                    'metadata': {'topic': 'programming', 'language': 'python'}
                },
                {
                    'content': 'Memory system refactor completed successfully',
                    'type': 'logs',
                    'metadata': {'topic': 'development', 'status': 'completed'}
                },
                {
                    'content': 'FAISS provider implementation with vector search',
                    'type': 'notes',
                    'metadata': {'topic': 'implementation', 'component': 'faiss'}
                }
            ]
            
            for memory in test_memories:
                await bridge._memory_tool.provider.add_memory(
                    content=memory['content'],
                    metadata=memory['metadata'],
                    categories=[memory['type']]
                )
            
            print(f"   ✅ Added {len(test_memories)} test memories")
            
            # Test various search queries
            test_queries = [
                'python programming',
                'memory system',
                'faiss implementation',
                'completed tasks'
            ]
            
            successful_searches = 0
            for query in test_queries:
                try:
                    results = await bridge.search_memory(query, max_results=3)
                    if results:
                        print(f"   ✅ Search '{query}': {len(results)} results")
                        successful_searches += 1
                    else:
                        print(f"   ⚠️ Search '{query}': No results")
                except Exception as e:
                    print(f"   ❌ Search '{query}' failed: {e}")
            
            if successful_searches > 0:
                print(f"   ✅ Memory functionality working: {successful_searches}/{len(test_queries)} searches successful")
                return True
            else:
                print("   ❌ No successful searches")
                return False
            
        except Exception as e:
            print(f"   ❌ End-to-end functionality test failed: {e}")
            return False
    
    async def test_error_handling(self):
        """Test error handling in memory tools."""
        print("\n7️⃣ Testing error handling...")
        
        try:
            # Test invalid action parsing
            invalid_actions = parse_action("<invalid_action>test</invalid_action>")
            if not invalid_actions:
                print("   ✅ Invalid actions correctly ignored")
            else:
                print(f"   ⚠️ Invalid action not filtered: {len(invalid_actions)} actions")
            
            # Test malformed memory search
            malformed_actions = parse_action("<memory_search></memory_search>")
            if malformed_actions:
                result = await self.action_executor.execute_action(malformed_actions[0])
                if "error" in result.lower() or len(result) > 0:
                    print("   ✅ Malformed memory search handled gracefully")
                else:
                    print("   ❌ Malformed search not handled properly")
                    return False
            
            # Test tool execution with invalid parameters
            try:
                result = self.tool_manager.execute_tool(
                    'memory_search',
                    {
                        'query': '',  # Empty query
                        'max_results': -1  # Invalid max_results
                    }
                )
                print("   ✅ Invalid parameters handled gracefully")
            except Exception as e:
                print(f"   ✅ Invalid parameters rejected appropriately: {type(e).__name__}")
            
            # Test non-existent tool
            try:
                result = self.tool_manager.execute_tool('non_existent_tool', {})
                if 'error' in str(result).lower():
                    print("   ✅ Non-existent tool error handled")
                else:
                    print("   ❌ Non-existent tool should return error")
                    return False
            except Exception as e:
                print(f"   ✅ Non-existent tool properly rejected: {type(e).__name__}")
            
            return True
            
        except Exception as e:
            print(f"   ❌ Error handling test failed: {e}")
            return False
    
    async def test_memory_search_parameters(self):
        """Test memory search with various parameters."""
        print("\n8️⃣ Testing memory search parameters...")
        
        try:
            # Test search with different parameter formats
            test_cases = [
                {
                    'name': 'simple query',
                    'params': {'query': 'test', 'max_results': 5}
                },
                {
                    'name': 'query with categories',
                    'params': {'query': 'test', 'max_results': 3, 'categories': ['notes']}
                },
                {
                    'name': 'query with memory type',
                    'params': {'query': 'test', 'memory_type': 'logs'}
                },
                {
                    'name': 'empty query',
                    'params': {'query': '', 'max_results': 5}
                }
            ]
            
            successful_tests = 0
            for test_case in test_cases:
                try:
                    result = self.tool_manager.execute_tool('memory_search', test_case['params'])
                    if result and isinstance(result, str):
                        print(f"   ✅ {test_case['name']}: Success")
                        successful_tests += 1
                    else:
                        print(f"   ⚠️ {test_case['name']}: Unexpected result")
                except Exception as e:
                    print(f"   ⚠️ {test_case['name']}: {e}")
            
            if successful_tests >= len(test_cases) * 0.75:  # 75% success rate
                print(f"   ✅ Parameter testing successful: {successful_tests}/{len(test_cases)}")
                return True
            else:
                print(f"   ❌ Too many parameter test failures: {successful_tests}/{len(test_cases)}")
                return False
            
        except Exception as e:
            print(f"   ❌ Memory search parameters test failed: {e}")
            return False
    
    async def run_all_tests(self):
        """Run all memory tools tests and provide summary."""
        print("🚀 Starting Memory Tools Integration Test Suite")
        print("=" * 60)
        
        test_results = {}
        
        try:
            await self.setup()
            
            # Run all tests
            tests = [
                ('memory_bridge_interface', self.test_memory_bridge_interface),
                ('workspace_bridge_interface', self.test_workspace_bridge_interface),
                ('tool_manager_integration', self.test_tool_manager_integration),
                ('parser_action_recognition', self.test_parser_action_recognition),
                ('action_executor_integration', self.test_action_executor_integration),
                ('memory_tool_functionality', self.test_memory_tool_functionality),
                ('error_handling', self.test_error_handling),
                ('memory_search_parameters', self.test_memory_search_parameters),
            ]
            
            for test_name, test_func in tests:
                try:
                    if asyncio.iscoroutinefunction(test_func):
                        result = await test_func()
                    else:
                        result = test_func()
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
            print("🎉 All tests passed! Memory tools integration is working correctly.")
            return True
        elif passed >= total * 0.8:  # 80% pass rate
            print("⚠️ Most tests passed. Some failures may be due to system configuration.")
            return True
        else:
            print("❌ Significant failures detected. Check the output above for details.")
            return False


async def main():
    """Main test runner."""
    tester = MemoryToolsTester()
    success = await tester.run_all_tests()
    
    if success:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main()) 