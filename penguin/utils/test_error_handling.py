"""Manual error-handling demo script

This module is **not** intended to be collected or executed by the automated
test-runner.  Unfortunately its filename (``test_*.py``) means `pytest` picks
it up during discovery which causes internal errors in CI/workflow validation.

We therefore unconditionally tell *pytest* to skip the module as soon as it is
imported.  When the file is executed directly (``python test_error_handling.py``)
the import of *pytest* will fail and the original demo logic below can still
run unchanged.
"""

# ---------------------------------------------------------------------------
# Skip on **any** pytest import – this happens right at import time so that no
# further code in this file is evaluated when the automated test-suite runs.
# ---------------------------------------------------------------------------

try:
    import pytest  # type: ignore
    pytest.skip("manual demo – skip during pytest collection", allow_module_level=True)
except ModuleNotFoundError:
    # Running outside pytest – proceed with the original demo script
    pass

import asyncio
import sys
import time
from pathlib import Path
from typing import Any, Dict

print("Script started")  # Debug output
print(f"Python version: {sys.version}")  # Debug output
print(f"Current directory: {Path.cwd()}")  # Debug output

try:
    from errors import error_handler, setup_global_error_handling

    print("Successfully imported error_handler")  # Debug output
except ImportError as e:
    print(f"Failed to import error_handler: {e}")
    print(f"Python path: {sys.path}")
    sys.exit(1)

# Setup error handling for tests
setup_global_error_handling()
print("Global error handling setup complete")  # Debug output


# Add pause at exit to see output
def pause_at_exit():
    print("\nPress Enter to exit...")
    input()


class DangerousOperations:
    """Class containing operations that will trigger different types of errors"""

    def trigger_zero_division(self) -> None:
        """Triggers a ZeroDivisionError"""
        try:
            1 / 0
        except Exception as e:
            error_handler.log_error(
                e,
                context={
                    "component": "tests",
                    "method": "trigger_zero_division",
                    "calculation": "1/0",
                },
            )
            raise

    def trigger_key_error(self) -> Dict[str, Any]:
        """Triggers a KeyError"""
        try:
            empty_dict = {}
            return empty_dict["nonexistent_key"]
        except Exception as e:
            error_handler.log_error(
                e,
                context={
                    "component": "tests",
                    "method": "trigger_key_error",
                    "dict_state": str(empty_dict),
                },
            )
            raise

    async def trigger_timeout(self) -> None:
        """Triggers an asyncio TimeoutError"""
        try:
            async with asyncio.timeout(0.1):
                await asyncio.sleep(1.0)
        except Exception as e:
            error_handler.log_error(
                e,
                context={
                    "component": "tests",
                    "method": "trigger_timeout",
                    "timeout_value": 0.1,
                    "sleep_value": 1.0,
                },
            )
            raise

    def trigger_file_error(self) -> None:
        """Triggers a FileNotFoundError"""
        try:
            nonexistent = Path("/definitely/not/a/real/path/file.txt")
            nonexistent.read_text()
        except Exception as e:
            error_handler.log_error(
                e,
                context={
                    "component": "tests",
                    "method": "trigger_file_error",
                    "attempted_path": str(nonexistent),
                },
            )
            raise

    def trigger_uncaught(self) -> None:
        """Triggers an error that won't be caught locally"""
        x = None
        x.some_method()  # Will raise AttributeError


if __name__ == "__main__":
    # Manual test runner with improved output handling
    async def run_tests():
        try:
            ops = DangerousOperations()

            print("\n=== Running Error Handler Tests ===\n")

            # Test each error type
            tests = [
                (lambda: ops.trigger_zero_division(), "ZeroDivisionError"),
                (lambda: ops.trigger_key_error(), "KeyError"),
                (lambda: ops.trigger_file_error(), "FileNotFoundError"),
                (ops.trigger_timeout, "TimeoutError"),
                (lambda: ops.trigger_uncaught(), "AttributeError (Uncaught)"),
            ]

            error_log_dir = Path("errors_log")
            error_log_dir.mkdir(exist_ok=True)
            print(f"Error logs will be written to: {error_log_dir.absolute()}\n")

            for test_func, error_type in tests:
                print(f"\nTesting {error_type}...")
                try:
                    if asyncio.iscoroutinefunction(test_func):
                        await test_func()
                    else:
                        test_func()
                    print("✗ Error was not raised as expected")
                except Exception as e:
                    print(f"✓ Successfully caught {type(e).__name__}")
                    print(f"  Error message: {str(e)}")
                    # Give filesystem time to write logs
                    time.sleep(0.1)

                    # List the most recent error log
                    logs = sorted(error_log_dir.glob("error_*.json"))
                    if logs:
                        latest_log = logs[-1]
                        print(f"  Log file: {latest_log.name}")

            print("\n=== Test Complete ===")
            print(f"\nError logs are in: {error_log_dir.absolute()}")

        except Exception as e:
            print(f"\n❌ Test runner failed: {type(e).__name__}: {str(e)}")
            import traceback

            print("\nTraceback:")
            print(traceback.format_exc())

        finally:
            pause_at_exit()

    # Run with proper asyncio handling
    if sys.platform.startswith("win"):
        # Windows requires specific event loop policy
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    try:
        asyncio.run(run_tests())
    except KeyboardInterrupt:
        print("\nTests interrupted by user")
        pause_at_exit()
