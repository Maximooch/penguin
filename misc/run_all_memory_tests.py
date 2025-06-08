#!/usr/bin/env python3
"""
Master Memory System Test Runner

Runs all memory system tests in sequence and provides a comprehensive summary:
1. Memory Configuration Test
2. FAISS Provider Test  
3. Memory Tools Integration Test

Usage: python run_all_memory_tests.py
"""

import asyncio
import subprocess
import sys
import time
from pathlib import Path


class MasterTestRunner:
    """Runs all memory system tests and provides unified reporting."""
    
    def __init__(self):
        self.test_scripts = [
            {
                'name': 'Memory Configuration',
                'script': 'test_memory_config.py',
                'description': 'Tests YAML config loading, provider factory, and auto-detection'
            },
            {
                'name': 'FAISS Provider',
                'script': 'test_faiss_provider.py', 
                'description': 'Tests FAISS vector search provider functionality'
            },
            {
                'name': 'Memory Tools Integration',
                'script': 'test_memory_tools.py',
                'description': 'Tests bridge system, tool manager, and parser integration'
            }
        ]
        self.results = {}
        
    def print_header(self):
        """Print test suite header."""
        print("🚀 PENGUIN MEMORY SYSTEM - STAGE 1 VALIDATION")
        print("=" * 70)
        print("Running comprehensive tests for the memory system refactor...")
        print(f"📊 Test Suites: {len(self.test_scripts)}")
        print("")
        
        for i, test in enumerate(self.test_scripts, 1):
            print(f"{i}. {test['name']}")
            print(f"   📝 {test['description']}")
        
        print("\n" + "=" * 70)
    
    def run_test_script(self, test_info):
        """Run a single test script and capture results."""
        print(f"\n🔧 Running {test_info['name']} Tests...")
        print("-" * 50)
        
        start_time = time.time()
        
        try:
            # Run the test script
            result = subprocess.run(
                [sys.executable, test_info['script']],
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            end_time = time.time()
            duration = end_time - start_time
            
            # Parse results
            success = result.returncode == 0
            output_lines = result.stdout.split('\n') if result.stdout else []
            error_lines = result.stderr.split('\n') if result.stderr else []
            
            # Look for test summary
            summary_line = None
            for line in output_lines:
                if 'Results:' in line and '/' in line:
                    summary_line = line.strip()
                    break
            
            # Store results
            self.results[test_info['name']] = {
                'success': success,
                'duration': duration,
                'summary': summary_line,
                'output': result.stdout,
                'errors': result.stderr,
                'returncode': result.returncode
            }
            
            # Print immediate feedback
            status = "✅ PASSED" if success else "❌ FAILED"
            print(f"{status} {test_info['name']} ({duration:.1f}s)")
            
            if summary_line:
                print(f"   📊 {summary_line}")
            
            if not success and result.stderr:
                print(f"   ⚠️ Errors: {result.stderr.strip()[:100]}...")
            
            return success
            
        except subprocess.TimeoutExpired:
            print(f"❌ {test_info['name']} TIMEOUT (>5 minutes)")
            self.results[test_info['name']] = {
                'success': False,
                'duration': 300,
                'summary': 'Test timed out',
                'output': '',
                'errors': 'Test exceeded 5 minute timeout',
                'returncode': -1
            }
            return False
            
        except Exception as e:
            print(f"❌ {test_info['name']} ERROR: {e}")
            self.results[test_info['name']] = {
                'success': False,
                'duration': 0,
                'summary': f'Error: {e}',
                'output': '',
                'errors': str(e),
                'returncode': -1
            }
            return False
    
    def print_summary(self):
        """Print comprehensive test summary."""
        print("\n" + "=" * 70)
        print("📊 COMPREHENSIVE TEST SUMMARY")
        print("=" * 70)
        
        total_tests = len(self.test_scripts)
        passed_tests = sum(1 for result in self.results.values() if result['success'])
        total_duration = sum(result['duration'] for result in self.results.values())
        
        # Overall status
        overall_success = passed_tests == total_tests
        status_icon = "🎉" if overall_success else "⚠️" if passed_tests > 0 else "❌"
        
        print(f"{status_icon} Overall Result: {passed_tests}/{total_tests} test suites passed")
        print(f"⏱️ Total Duration: {total_duration:.1f} seconds")
        print("")
        
        # Individual test results
        for test_info in self.test_scripts:
            name = test_info['name']
            result = self.results.get(name, {})
            
            status = "✅" if result.get('success') else "❌"
            duration = result.get('duration', 0)
            summary = result.get('summary', 'No summary available')
            
            print(f"{status} {name}")
            print(f"   ⏱️ Duration: {duration:.1f}s")
            print(f"   📊 {summary}")
            
            if not result.get('success') and result.get('errors'):
                error_preview = result['errors'][:150] + "..." if len(result['errors']) > 150 else result['errors']
                print(f"   ⚠️ Error: {error_preview}")
            
            print("")
        
        # Recommendations
        print("💡 RECOMMENDATIONS")
        print("-" * 30)
        
        if overall_success:
            print("🎉 All tests passed! The memory system Stage 1 implementation is working correctly.")
            print("✅ You can proceed with confidence to Stage 2 development.")
            print("📝 Consider running these tests regularly as a regression suite.")
        elif passed_tests >= total_tests * 0.8:  # 80% pass rate
            print("⚠️ Most tests passed, but some issues were detected:")
            
            failed_tests = [name for name, result in self.results.items() if not result['success']]
            for test_name in failed_tests:
                result = self.results[test_name]
                if 'dependencies' in result.get('errors', '').lower():
                    print(f"   • {test_name}: Install missing dependencies")
                elif 'timeout' in result.get('errors', '').lower():
                    print(f"   • {test_name}: Performance issue or infinite loop")
                else:
                    print(f"   • {test_name}: Check error details above")
            
            print("\n📝 The memory system core functionality appears to be working.")
            print("🔧 Address the failed tests before production deployment.")
        else:
            print("❌ Significant issues detected in the memory system:")
            print("🛠️ Review the error details above and fix the underlying issues.")
            print("⚠️ Do not proceed to Stage 2 until these tests pass.")
        
        # Detailed output option
        print(f"\n📋 For detailed output, check individual test script logs:")
        for test_info in self.test_scripts:
            print(f"   python {test_info['script']}")
    
    def run_all_tests(self):
        """Run all test scripts in sequence."""
        self.print_header()
        
        all_passed = True
        
        for test_info in self.test_scripts:
            success = self.run_test_script(test_info)
            if not success:
                all_passed = False
        
        self.print_summary()
        
        return all_passed


def main():
    """Main test runner."""
    runner = MasterTestRunner()
    success = runner.run_all_tests()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main() 