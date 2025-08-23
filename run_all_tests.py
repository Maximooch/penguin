#!/usr/bin/env python3
"""
Test runner for all OpenRouter gateway fix tests.

This script runs all the test files in sequence and provides a summary.

Run with: python run_all_tests.py
"""

import subprocess
import sys
import time
from pathlib import Path

def run_test_script(script_path):
    """Run a test script and capture its output."""
    print(f"🏃 Running {script_path.name}...")
    print("=" * 60)
    
    start_time = time.time()
    
    try:
        # Run the script
        result = subprocess.run(
            ["python", str(script_path)], 
            capture_output=True, 
            text=True,
            cwd=script_path.parent
        )
        
        duration = time.time() - start_time
        
        # Print output
        if result.stdout:
            print(result.stdout)
        
        if result.stderr and result.returncode != 0:
            print("STDERR:", result.stderr)
        
        status = "✅ PASSED" if result.returncode == 0 else f"❌ FAILED (exit code {result.returncode})"
        print(f"\n{status} - {script_path.name} completed in {duration:.2f}s")
        
        return result.returncode == 0, duration, result.stdout + result.stderr
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"💥 ERROR running {script_path.name}: {e}"
        print(error_msg)
        return False, duration, error_msg

def main():
    """Run all test scripts."""
    print("🧪 Running All OpenRouter Gateway Tests\n")
    
    # Find test scripts in current directory
    test_dir = Path(__file__).parent
    test_scripts = [
        # Lightweight event/streaming integration test (no network)
        test_dir / "test_runmode_streaming.py",
        test_dir / "test_openrouter_fixes.py",
        test_dir / "test_action_tag_parser.py",
        test_dir / "test_context_commands.py",
        # Note: test_reasoning_models.py requires API key, run separately
    ]
    
    # Check if scripts exist
    missing_scripts = [s for s in test_scripts if not s.exists()]
    if missing_scripts:
        print("❌ Missing test scripts:")
        for script in missing_scripts:
            print(f"   - {script}")
        return 1
    
    results = {}
    total_duration = 0
    
    # Run each test script
    for script in test_scripts:
        success, duration, output = run_test_script(script)
        results[script.name] = {
            'success': success,
            'duration': duration,
            'output': output
        }
        total_duration += duration
        print("\n" + "="*80 + "\n")
    
    # Summary
    print("📊 TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for r in results.values() if r['success'])
    total = len(results)
    
    for script_name, result in results.items():
        status = "✅" if result['success'] else "❌"
        print(f"{status} {script_name:<30} ({result['duration']:.2f}s)")
    
    print(f"\nOverall: {passed}/{total} test scripts passed")
    print(f"Total runtime: {total_duration:.2f}s")
    
    # Additional info
    print(f"\n📝 Additional Tests Available:")
    reasoning_test = test_dir / "test_reasoning_models.py"
    if reasoning_test.exists():
        print(f"  🧠 {reasoning_test.name} - Requires OPENROUTER_API_KEY")
        print(f"      Run with: python {reasoning_test.name}")
    
    # Recommendations based on results
    if passed == total:
        print(f"\n🎉 All tests passed! The OpenRouter gateway fixes are working correctly.")
        print(f"   - Reasoning token configuration is properly formatted")
        print(f"   - Conversation reformatting preserves all content") 
        print(f"   - Action tag detection is consistent between parser and gateway")
        print(f"\n🔬 Next step: Test with actual reasoning models using test_reasoning_models.py")
    else:
        print(f"\n⚠️  Some tests failed. Check the output above for details.")
        failed_scripts = [name for name, result in results.items() if not result['success']]
        print(f"   Failed scripts: {', '.join(failed_scripts)}")
    
    return 0 if passed == total else 1

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n⏹️  Tests interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"💥 Unexpected error in test runner: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)