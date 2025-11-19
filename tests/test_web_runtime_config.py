#!/usr/bin/env python3
"""
Test script for Penguin Web API RuntimeConfig endpoints.

Tests the following endpoints:
- GET  /api/v1/system/config
- POST /api/v1/system/config/project-root
- POST /api/v1/system/config/workspace-root
- POST /api/v1/system/config/execution-mode

Prerequisites:
- Penguin web server running on localhost:8000
- Run with: python test_web_runtime_config.py
"""

import requests
import json
from pathlib import Path
import sys
from typing import Dict, Any


BASE_URL = "http://localhost:8000"
CONFIG_ENDPOINT = f"{BASE_URL}/api/v1/system/config"


def print_section(title: str):
    """Print a section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_response(response: requests.Response, show_full: bool = False):
    """Pretty print a response."""
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        print("✓ Success")
        data = response.json()
        if show_full:
            print(json.dumps(data, indent=2))
        else:
            # Print relevant fields only
            if 'config' in data:
                print(f"Config: {json.dumps(data['config'], indent=2)}")
            elif 'status' in data:
                print(f"Status: {data['status']}")
                if 'message' in data:
                    print(f"Message: {data['message']}")
                if 'path' in data:
                    print(f"Path: {data['path']}")
                if 'active_root' in data:
                    print(f"Active Root: {data['active_root']}")
                if 'execution_mode' in data:
                    print(f"Execution Mode: {data['execution_mode']}")
    else:
        print(f"✗ Error: {response.status_code}")
        try:
            print(json.dumps(response.json(), indent=2))
        except:
            print(response.text)


def test_get_config():
    """Test GET /api/v1/system/config"""
    print_section("Test 1: GET Current Configuration")
    
    try:
        response = requests.get(CONFIG_ENDPOINT)
        print_response(response, show_full=True)
        
        if response.status_code == 200:
            data = response.json()
            config = data.get('config', {})
            return config
        return None
    except Exception as e:
        print(f"✗ Request failed: {e}")
        return None


def test_set_project_root(path: str):
    """Test POST /api/v1/system/config/project-root"""
    print_section(f"Test 2: Set Project Root to: {path}")
    
    try:
        response = requests.post(
            f"{CONFIG_ENDPOINT}/project-root",
            json={"path": path}
        )
        print_response(response)
        return response.status_code == 200
    except Exception as e:
        print(f"✗ Request failed: {e}")
        return False


def test_set_workspace_root(path: str):
    """Test POST /api/v1/system/config/workspace-root"""
    print_section(f"Test 3: Set Workspace Root to: {path}")
    
    try:
        response = requests.post(
            f"{CONFIG_ENDPOINT}/workspace-root",
            json={"path": path}
        )
        print_response(response)
        return response.status_code == 200
    except Exception as e:
        print(f"✗ Request failed: {e}")
        return False


def test_set_execution_mode(mode: str):
    """Test POST /api/v1/system/config/execution-mode"""
    print_section(f"Test 4: Set Execution Mode to: {mode}")
    
    try:
        response = requests.post(
            f"{CONFIG_ENDPOINT}/execution-mode",
            json={"path": mode}  # Using 'path' field for consistency
        )
        print_response(response)
        return response.status_code == 200
    except Exception as e:
        print(f"✗ Request failed: {e}")
        return False


def test_invalid_path():
    """Test error handling with invalid path"""
    print_section("Test 5: Error Handling (Invalid Path)")
    
    try:
        response = requests.post(
            f"{CONFIG_ENDPOINT}/project-root",
            json={"path": "/this/path/does/not/exist/12345"}
        )
        print_response(response)
        
        if response.status_code == 400:
            print("✓ Correctly returned 400 Bad Request")
            return True
        else:
            print(f"✗ Expected 400, got {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Request failed: {e}")
        return False


def test_invalid_execution_mode():
    """Test error handling with invalid execution mode"""
    print_section("Test 6: Error Handling (Invalid Execution Mode)")
    
    try:
        response = requests.post(
            f"{CONFIG_ENDPOINT}/execution-mode",
            json={"path": "invalid_mode"}
        )
        print_response(response)
        
        if response.status_code == 400:
            print("✓ Correctly returned 400 Bad Request")
            return True
        else:
            print(f"✗ Expected 400, got {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Request failed: {e}")
        return False


def test_mode_switch_and_verify():
    """Test switching between modes and verifying changes"""
    print_section("Test 7: Mode Switching (project → workspace → project)")
    
    # Get initial state
    print("\n📍 Getting initial state...")
    initial_config = test_get_config()
    if not initial_config:
        print("✗ Could not get initial config")
        return False
    
    initial_mode = initial_config.get('execution_mode')
    print(f"Initial mode: {initial_mode}")
    
    # Switch to opposite mode
    new_mode = 'workspace' if initial_mode == 'project' else 'project'
    print(f"\n📍 Switching to {new_mode} mode...")
    if not test_set_execution_mode(new_mode):
        print(f"✗ Failed to switch to {new_mode}")
        return False
    
    # Verify change
    print(f"\n📍 Verifying mode changed to {new_mode}...")
    current_config = test_get_config()
    if not current_config:
        print("✗ Could not get config after change")
        return False
    
    if current_config.get('execution_mode') == new_mode:
        print(f"✓ Mode successfully changed to {new_mode}")
    else:
        print(f"✗ Mode did not change (expected {new_mode}, got {current_config.get('execution_mode')})")
        return False
    
    # Switch back to initial mode
    print(f"\n📍 Switching back to {initial_mode} mode...")
    if not test_set_execution_mode(initial_mode):
        print(f"✗ Failed to switch back to {initial_mode}")
        return False
    
    # Verify restored
    print(f"\n📍 Verifying mode restored to {initial_mode}...")
    final_config = test_get_config()
    if not final_config:
        print("✗ Could not get config after restore")
        return False
    
    if final_config.get('execution_mode') == initial_mode:
        print(f"✓ Mode successfully restored to {initial_mode}")
        return True
    else:
        print(f"✗ Mode not restored (expected {initial_mode}, got {final_config.get('execution_mode')})")
        return False


def check_server_health():
    """Check if the server is running and healthy"""
    try:
        response = requests.get(f"{BASE_URL}/api/v1/health", timeout=2)
        return response.status_code == 200
    except:
        return False


def main():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("  Penguin Web API RuntimeConfig Test Suite")
    print("=" * 70)
    print(f"\nServer: {BASE_URL}")
    
    # Check server is running
    print("\n📡 Checking if server is running...")
    if not check_server_health():
        print(f"✗ Server not responding at {BASE_URL}")
        print("\nPlease ensure the Penguin web server is running:")
        print("  $ penguin-web")
        return 1
    print("✓ Server is running")
    
    # Get some valid paths for testing
    current_dir = str(Path.cwd())
    home_dir = str(Path.home())
    
    results = []
    
    # Test 1: Get initial config
    initial_config = test_get_config()
    results.append(("Get Config", initial_config is not None))
    
    # Test 2: Set project root (to current directory)
    results.append(("Set Project Root", test_set_project_root(current_dir)))
    
    # Test 3: Set workspace root (to home directory)
    results.append(("Set Workspace Root", test_set_workspace_root(home_dir)))
    
    # Test 4: Set execution mode to project
    results.append(("Set Mode to Project", test_set_execution_mode("project")))
    
    # Test 5: Invalid path error handling
    results.append(("Invalid Path Error", test_invalid_path()))
    
    # Test 6: Invalid mode error handling
    results.append(("Invalid Mode Error", test_invalid_execution_mode()))
    
    # Test 7: Mode switching and verification
    results.append(("Mode Switching", test_mode_switch_and_verify()))
    
    # Final verification
    print_section("Final Configuration State")
    final_config = test_get_config()
    
    # Print summary
    print("\n" + "=" * 70)
    print("  Test Summary")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status:10} {test_name}")
    
    print("\n" + "-" * 70)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 70)
    
    return 0 if passed == total else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n✗ Test suite failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

