#!/usr/bin/env python3
"""
Test runner for Phase 1 API update tests.

This script runs all the tests created for Phase 1 functionality including:
- PenguinCore checkpoint management tests
- PenguinCore model management tests  
- PenguinCore system diagnostics tests
- PenguinClient API client tests
- Package exports and imports tests
- Integration tests for complete workflows

Usage:
    python tests/run_phase1_tests.py [--verbose] [--coverage] [--integration-only]
"""

import sys
import subprocess
import argparse
from pathlib import Path


def run_command(cmd, description):
    """Run a command and return success status."""
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(cmd)}")
    print('='*60)
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        print(f"✅ {description} - PASSED")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} - FAILED")
        print("STDOUT:", e.stdout)
        print("STDERR:", e.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Run Phase 1 API update tests")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--coverage", "-c", action="store_true", help="Run with coverage")
    parser.add_argument("--integration-only", "-i", action="store_true", help="Run only integration tests")
    parser.add_argument("--unit-only", "-u", action="store_true", help="Run only unit tests")
    args = parser.parse_args()
    
    # Base pytest command
    base_cmd = ["python", "-m", "pytest"]
    
    if args.verbose:
        base_cmd.append("-v")
    
    if args.coverage:
        base_cmd.extend(["--cov=penguin", "--cov-report=html", "--cov-report=term"])
    
    # Test files for Phase 1
    test_files = {
        "checkpoint_management": "tests/test_core_checkpoint_management.py",
        "model_management": "tests/test_core_model_management.py", 
        "system_diagnostics": "tests/test_core_system_diagnostics.py",
        "api_client": "tests/test_api_client.py",
        "package_exports": "tests/test_package_exports.py",
        "integration": "tests/test_phase1_integration.py"
    }
    
    results = {}
    
    print("🐧 Penguin Phase 1 Test Suite")
    print("="*60)
    print("Testing the following Phase 1 features:")
    print("• PenguinCore checkpoint management methods")
    print("• PenguinCore model management methods")
    print("• PenguinCore system diagnostics methods")
    print("• PenguinClient high-level API")
    print("• Package exports and imports")
    print("• End-to-end integration scenarios")
    print()
    
    if args.integration_only:
        # Run only integration tests
        test_selection = {"integration": test_files["integration"]}
    elif args.unit_only:
        # Run only unit tests (exclude integration)
        test_selection = {k: v for k, v in test_files.items() if k != "integration"}
    else:
        # Run all tests
        test_selection = test_files
    
    # Run each test file
    for test_name, test_file in test_selection.items():
        if Path(test_file).exists():
            cmd = base_cmd + [test_file]
            success = run_command(cmd, f"{test_name.replace('_', ' ').title()} Tests")
            results[test_name] = success
        else:
            print(f"⚠️  Test file not found: {test_file}")
            results[test_name] = False
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for success in results.values() if success)
    total = len(results)
    
    for test_name, success in results.items():
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{test_name.replace('_', ' ').title():<25} {status}")
    
    print(f"\nOverall: {passed}/{total} test suites passed")
    
    if passed == total:
        print("\n🎉 All Phase 1 tests PASSED! The API updates are working correctly.")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test suite(s) FAILED. Please check the output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())