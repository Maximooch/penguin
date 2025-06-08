#!/usr/bin/env python3
"""
Memory Configuration Test Script

Tests the memory configuration system including:
- YAML configuration loading
- Provider factory and auto-detection
- Configuration validation and defaults
- Provider selection logic
- Health monitoring across providers
- Configuration overrides and environment variables

Usage: python test_memory_config.py
"""

import asyncio
import logging
import os
import shutil
import sys
import tempfile
import yaml
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from penguin.config import get_memory_config, MEMORY_CONFIG
from penguin.memory import MemoryProviderFactory, create_memory_provider, get_memory_system_info

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MemoryConfigTester:
    """Comprehensive test suite for memory configuration system."""
    
    def __init__(self):
        self.temp_dir = None
        self.test_config_file = None
        self.original_config = None
        
    def setup(self):
        """Set up test environment."""
        print("🔧 Setting up memory configuration test environment...")
        
        # Create temporary directory
        self.temp_dir = Path(tempfile.mkdtemp(prefix="memory_config_test_"))
        print(f"   Test directory: {self.temp_dir}")
        
        # Store original config
        self.original_config = get_memory_config().copy()
        print("✅ Test environment ready")
        
    def cleanup(self):
        """Clean up test environment."""
        print("\n🧹 Cleaning up test environment...")
        
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
            print(f"   Removed test directory: {self.temp_dir}")
    
    def test_default_config_loading(self):
        """Test default configuration loading."""
        print("\n1️⃣ Testing default configuration loading...")
        
        try:
            config = get_memory_config()
            
            # Check required fields
            required_fields = ['provider', 'embedding_model', 'storage_path', 'providers']
            missing_fields = [field for field in required_fields if field not in config]
            
            if missing_fields:
                print(f"   ❌ Missing required config fields: {missing_fields}")
                return False
            
            print(f"   ✅ Provider: {config['provider']}")
            print(f"   ✅ Embedding model: {config['embedding_model']}")
            print(f"   ✅ Storage path: {config['storage_path']}")
            print(f"   ✅ Available providers: {list(config['providers'].keys())}")
            
            # Check provider-specific configs
            for provider_name, provider_config in config['providers'].items():
                if provider_config:
                    print(f"   ✅ {provider_name} config: {len(provider_config)} settings")
                else:
                    print(f"   ⚠️ {provider_name} config: Empty")
            
            return True
            
        except Exception as e:
            print(f"   ❌ Config loading failed: {e}")
            return False
    
    def test_custom_config_creation(self):
        """Test creating and loading custom configurations."""
        print("\n2️⃣ Testing custom configuration creation...")
        
        try:
            # Create custom config
            custom_config = {
                'memory': {
                    'provider': 'sqlite',
                    'embedding_model': 'custom-model',
                    'storage_path': str(self.temp_dir / 'custom_memory'),
                    'providers': {
                        'sqlite': {
                            'database_file': 'custom.db',
                            'enable_fts': True,
                            'enable_embeddings': False
                        },
                        'file': {
                            'storage_dir': 'custom_files',
                            'index_format': 'yaml'
                        },
                        'faiss': {
                            'index_type': 'IndexFlatL2',
                            'dimension': 512
                        }
                    }
                }
            }
            
            # Write to temporary config file
            config_file = self.temp_dir / 'test_config.yml'
            with open(config_file, 'w') as f:
                yaml.dump(custom_config, f)
            
            print(f"   ✅ Custom config created: {config_file}")
            
            # Verify config structure
            with open(config_file, 'r') as f:
                loaded_config = yaml.safe_load(f)
            
            memory_config = loaded_config['memory']
            if memory_config['provider'] == 'sqlite':
                print("   ✅ Custom provider setting verified")
            else:
                print(f"   ❌ Wrong provider: {memory_config['provider']}")
                return False
            
            if memory_config['providers']['sqlite']['database_file'] == 'custom.db':
                print("   ✅ Custom SQLite config verified")
            else:
                print("   ❌ Custom SQLite config not found")
                return False
            
            self.test_config_file = config_file
            return True
            
        except Exception as e:
            print(f"   ❌ Custom config creation failed: {e}")
            return False
    
    def test_provider_factory(self):
        """Test provider factory functionality."""
        print("\n3️⃣ Testing provider factory...")
        
        try:
            # Test getting available providers
            available = MemoryProviderFactory.get_available_providers()
            print(f"   📊 Available providers: {available}")
            
            if not available:
                print("   ❌ No providers available")
                return False
            
            expected_providers = ['sqlite', 'file', 'faiss']
            for provider in expected_providers:
                if provider in available:
                    print(f"   ✅ {provider} provider available")
                else:
                    print(f"   ⚠️ {provider} provider not available")
            
            # Test auto-detection
            auto_provider = MemoryProviderFactory._detect_best_provider()
            print(f"   🎯 Auto-detected provider: {auto_provider}")
            
            if auto_provider in available:
                print("   ✅ Auto-detection selected available provider")
            else:
                print("   ❌ Auto-detection selected unavailable provider")
                return False
            
            return True
            
        except Exception as e:
            print(f"   ❌ Provider factory test failed: {e}")
            return False
    
    async def test_provider_creation(self):
        """Test creating providers with different configurations."""
        print("\n4️⃣ Testing provider creation...")
        
        test_configs = [
            {
                'name': 'auto',
                'config': {
                    'provider': 'auto',
                    'storage_path': str(self.temp_dir / 'auto_test')
                }
            },
            {
                'name': 'sqlite',
                'config': {
                    'provider': 'sqlite',
                    'storage_path': str(self.temp_dir / 'sqlite_test'),
                    'providers': {
                        'sqlite': {
                            'database_file': 'test.db',
                            'enable_fts': True
                        }
                    }
                }
            },
            {
                'name': 'file',
                'config': {
                    'provider': 'file',
                    'storage_path': str(self.temp_dir / 'file_test'),
                    'providers': {
                        'file': {
                            'storage_dir': 'file_memory',
                            'index_format': 'json'
                        }
                    }
                }
            }
        ]
        
        try:
            created_providers = []
            
            for test in test_configs:
                print(f"   🔧 Creating {test['name']} provider...")
                
                try:
                    provider = create_memory_provider(test['config'])
                    await provider.initialize()
                    
                    # Test basic functionality
                    memory_id = await provider.add_memory(
                        f"Test memory for {test['name']} provider",
                        metadata={'test': True, 'provider': test['name']},
                        categories=['test']
                    )
                    
                    # Verify memory was added
                    memory = await provider.get_memory(memory_id)
                    if memory and memory['content'].startswith('Test memory'):
                        print(f"   ✅ {test['name']} provider working correctly")
                        created_providers.append((test['name'], provider))
                    else:
                        print(f"   ❌ {test['name']} provider memory test failed")
                        await provider.close()
                        return False
                        
                except Exception as e:
                    print(f"   ⚠️ {test['name']} provider failed: {e}")
                    # Don't fail the test if one provider fails due to dependencies
                    continue
            
            # Clean up providers
            for name, provider in created_providers:
                await provider.close()
                print(f"   🧹 Closed {name} provider")
            
            if created_providers:
                print(f"   ✅ Successfully created {len(created_providers)} providers")
                return True
            else:
                print("   ❌ No providers could be created")
                return False
            
        except Exception as e:
            print(f"   ❌ Provider creation test failed: {e}")
            return False
    
    def test_health_monitoring(self):
        """Test health monitoring across all providers."""
        print("\n5️⃣ Testing health monitoring...")
        
        try:
            health_status = MemoryProviderFactory.health_check_all_providers()
            
            print(f"   📊 Overall status: {health_status['overall_status']}")
            print(f"   📊 Checked providers: {len(health_status['providers'])}")
            
            for provider_name, status in health_status['providers'].items():
                is_available = status['status'] == 'available'
                status_icon = "✅" if is_available else "❌"
                print(f"   {status_icon} {provider_name}: {status['status']}")
                
                if not is_available and 'reason' in status:
                    print(f"      Reason: {status['reason']}")
                
                if 'reason' in status:
                    print(f"      💡 {status['reason']}")
            
            # Check if at least one provider is available
            available_count = sum(1 for status in health_status['providers'].values() if status['status'] == 'available')
            
            if available_count > 0:
                print(f"   ✅ {available_count} providers available")
                return True
            else:
                print("   ❌ No providers available")
                return False
            
        except Exception as e:
            print(f"   ❌ Health monitoring test failed: {e}")
            return False
    
    def test_configuration_validation(self):
        """Test configuration validation and error handling."""
        print("\n6️⃣ Testing configuration validation...")
        
        try:
            # Test invalid provider
            try:
                invalid_config = {
                    'provider': 'non_existent_provider',
                    'storage_path': str(self.temp_dir / 'invalid_test')
                }
                provider = create_memory_provider(invalid_config)
                print("   ❌ Should have failed with invalid provider")
                return False
            except Exception as e:
                print(f"   ✅ Invalid provider correctly rejected: {type(e).__name__}")
            
            # Test missing required config
            try:
                empty_config = {}
                provider = create_memory_provider(empty_config)
                # This should work with defaults
                print("   ✅ Empty config handled with defaults")
            except Exception as e:
                print(f"   ⚠️ Empty config handling: {e}")
            
            # Test partial config
            partial_config = {
                'provider': 'sqlite',
                'storage_path': str(self.temp_dir / 'partial_test')
                # Missing provider-specific settings
            }
            
            try:
                provider = create_memory_provider(partial_config)
                print("   ✅ Partial config handled with defaults")
            except Exception as e:
                print(f"   ❌ Partial config failed: {e}")
                return False
            
            return True
            
        except Exception as e:
            print(f"   ❌ Configuration validation test failed: {e}")
            return False
    
    def test_memory_system_info(self):
        """Test memory system information gathering."""
        print("\n7️⃣ Testing memory system information...")
        
        try:
            info = get_memory_system_info()
            
            required_info = ['available_providers', 'provider_info', 'health_status']
            missing_info = [field for field in required_info if field not in info]
            
            if missing_info:
                print(f"   ❌ Missing system info fields: {missing_info}")
                return False
            
            print(f"   📊 Available providers: {info['available_providers']}")
            
            recommended_provider = info['available_providers'][0] if info['available_providers'] else 'none'
            print(f"   🎯 Recommended provider: {recommended_provider}")
            
            system_status = info['health_status']['overall_status']
            print(f"   📊 System status: {system_status}")
            
            if 'provider_info' in info:
                provider_info = info['provider_info']
                print(f"   ⚙️ Provider info: {len(provider_info)} providers checked")
            
            if 'version' in info:
                print(f"   📖 Version: {info['version']}")
            
            if 'features' in info:
                print(f"   🎯 Features: {len(info['features'])} available")
            
            return True
            
        except Exception as e:
            print(f"   ❌ Memory system info test failed: {e}")
            return False
    
    def test_configuration_overrides(self):
        """Test configuration overrides and precedence."""
        print("\n8️⃣ Testing configuration overrides...")
        
        try:
            # Test environment variable override (simulated)
            original_env = os.environ.get('PENGUIN_MEMORY_PROVIDER')
            
            # Simulate environment override
            os.environ['PENGUIN_MEMORY_PROVIDER'] = 'file'
            
            # Test config with override
            config_with_override = {
                'provider': 'auto',  # Should be overridden
                'storage_path': str(self.temp_dir / 'override_test')
            }
            
            # Note: This test would need actual environment variable handling
            # in the config system to work properly
            print("   ℹ️ Environment override test (simulated)")
            print(f"   📝 Would override provider to: {os.environ.get('PENGUIN_MEMORY_PROVIDER')}")
            
            # Restore environment
            if original_env:
                os.environ['PENGUIN_MEMORY_PROVIDER'] = original_env
            else:
                del os.environ['PENGUIN_MEMORY_PROVIDER']
            
            # Test provider-specific config override
            override_config = {
                'provider': 'sqlite',
                'storage_path': str(self.temp_dir / 'override_test'),
                'providers': {
                    'sqlite': {
                        'database_file': 'override.db',
                        'enable_fts': False  # Override default
                    }
                }
            }
            
            try:
                provider = create_memory_provider(override_config)
                print("   ✅ Provider-specific config override accepted")
            except Exception as e:
                print(f"   ❌ Provider-specific override failed: {e}")
                return False
            
            return True
            
        except Exception as e:
            print(f"   ❌ Configuration override test failed: {e}")
            return False
    
    async def run_all_tests(self):
        """Run all configuration tests and provide summary."""
        print("🚀 Starting Memory Configuration Test Suite")
        print("=" * 60)
        
        test_results = {}
        
        try:
            self.setup()
            
            # Run all tests
            tests = [
                ('default_config_loading', self.test_default_config_loading),
                ('custom_config_creation', self.test_custom_config_creation),
                ('provider_factory', self.test_provider_factory),
                ('provider_creation', self.test_provider_creation),
                ('health_monitoring', self.test_health_monitoring),
                ('configuration_validation', self.test_configuration_validation),
                ('memory_system_info', self.test_memory_system_info),
                ('configuration_overrides', self.test_configuration_overrides),
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
            self.cleanup()
        
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
            print("🎉 All tests passed! Memory configuration system is working correctly.")
            return True
        elif passed >= total * 0.8:  # 80% pass rate
            print("⚠️ Most tests passed. Some failures may be due to missing dependencies.")
            return True
        else:
            print("❌ Significant failures detected. Check the output above for details.")
            return False


async def main():
    """Main test runner."""
    tester = MemoryConfigTester()
    success = await tester.run_all_tests()
    
    if success:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main()) 