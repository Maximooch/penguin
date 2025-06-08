#!/usr/bin/env python3
"""
Simple test script to verify package functionality before publishing.
"""

import sys
import traceback

def test_basic_import():
    """Test basic package import"""
    print("Testing basic import...")
    try:
        import penguin
        print(f"✅ Successfully imported penguin (version: {getattr(penguin, '__version__', 'unknown')})")
        return True
    except Exception as e:
        print(f"❌ Failed to import penguin: {e}")
        traceback.print_exc()
        return False

def test_core_import():
    """Test core module import"""
    print("Testing core module import...")
    try:
        from penguin.core import PenguinCore
        print("✅ Successfully imported PenguinCore")
        return True
    except Exception as e:
        print(f"❌ Failed to import PenguinCore: {e}")
        traceback.print_exc()
        return False

def test_cli_entry_point():
    """Test CLI entry point"""
    print("Testing CLI entry point...")
    try:
        from penguin.chat.cli import app
        print("✅ Successfully imported CLI app")
        return True
    except Exception as e:
        print(f"❌ Failed to import CLI app: {e}")
        traceback.print_exc()
        return False

def test_server_entry_point():
    """Test server entry point"""
    print("Testing server entry point...")
    try:
        from penguin.api.server import main
        print("✅ Successfully imported server main")
        return True
    except Exception as e:
        print(f"❌ Failed to import server main: {e}")
        traceback.print_exc()
        return False

def test_config_file():
    """Test config file is accessible"""
    print("Testing config file access...")
    try:
        import penguin
        import os
        from pathlib import Path
        
        # Find config.yml in the package
        package_dir = Path(penguin.__file__).parent
        config_path = package_dir / "config.yml"
        
        if config_path.exists():
            print(f"✅ Config file found at: {config_path}")
            return True
        else:
            print(f"❌ Config file not found at: {config_path}")
            return False
    except Exception as e:
        print(f"❌ Failed to check config file: {e}")
        traceback.print_exc()
        return False

def main():
    """Run all tests"""
    print("🐧 Penguin Package Test Suite")
    print("=" * 40)
    
    tests = [
        test_basic_import,
        test_core_import,
        test_cli_entry_point,
        test_server_entry_point,
        test_config_file,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ Test {test.__name__} crashed: {e}")
            failed += 1
        print()
    
    print("=" * 40)
    print(f"Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("🎉 All tests passed! Package is ready for publication.")
        return 0
    else:
        print("❌ Some tests failed. Please fix issues before publishing.")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 