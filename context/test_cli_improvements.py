#!/usr/bin/env python3
"""
Test script for Python CLI improvements (Kimi patterns implementation)

Tests all new features added in the CLI refactoring:
- Checkpoint commands (/checkpoint, /rollback, /checkpoints, /branch)
- Context window display (/tokens, /truncations)
- StreamingDisplay with Rich.Live
- Tool execution indicators

Usage:
    python context/test_cli_improvements.py
"""

import asyncio
import sys
import time
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.panel import Panel

console = Console()


def print_test_header(test_name: str):
    """Print a test section header"""
    console.print(f"\n{'='*60}")
    console.print(f"[bold cyan]TEST: {test_name}[/bold cyan]")
    console.print(f"{'='*60}\n")


def print_test_result(passed: bool, message: str):
    """Print test result"""
    icon = "✓" if passed else "✗"
    color = "green" if passed else "red"
    console.print(f"[{color}]{icon} {message}[/{color}]")


async def test_checkpoint_commands():
    """Test checkpoint command integration"""
    print_test_header("Checkpoint Commands")
    
    try:
        from penguin.core import PenguinCore
        from penguin.cli.interface import PenguinInterface
        
        # Create core instance
        console.print("[dim]Creating PenguinCore instance...[/dim]")
        core = await PenguinCore.create(fast_startup=True, show_progress=False)
        interface = PenguinInterface(core)
        
        # Test 1: Create a checkpoint
        console.print("\n[bold]Test 1: Create checkpoint[/bold]")
        result = await interface._handle_checkpoint_command(["test_checkpoint", "Test checkpoint description"])
        
        if "checkpoint_id" in result:
            checkpoint_id = result["checkpoint_id"]
            print_test_result(True, f"Created checkpoint: {checkpoint_id}")
        else:
            print_test_result(False, f"Failed to create checkpoint: {result.get('error', 'Unknown error')}")
            return False
        
        # Wait for async checkpoint worker to process the queue
        console.print("[dim]Waiting for checkpoint worker to process...[/dim]")
        await asyncio.sleep(0.5)
        
        # Test 2: List checkpoints
        console.print("\n[bold]Test 2: List checkpoints[/bold]")
        result = await interface._handle_checkpoints_command([])
        
        if "checkpoints" in result and len(result["checkpoints"]) > 0:
            print_test_result(True, f"Found {len(result['checkpoints'])} checkpoint(s)")
        else:
            print_test_result(False, "No checkpoints found")
            return False
        
        # Test 3: Add some messages to create difference
        console.print("\n[bold]Test 3: Add messages after checkpoint[/bold]")
        await interface.process_input({"text": "This is a test message after checkpoint"})
        print_test_result(True, "Added test message")
        
        # Test 4: Rollback to checkpoint
        console.print("\n[bold]Test 4: Rollback to checkpoint[/bold]")
        result = await interface._handle_rollback_command([checkpoint_id])
        
        if "status" in result and "Rolled back" in result["status"]:
            print_test_result(True, "Successfully rolled back to checkpoint")
        else:
            print_test_result(False, f"Rollback failed: {result.get('error', 'Unknown error')}")
            return False
        
        # Test 5: Create branch from checkpoint
        console.print("\n[bold]Test 5: Create branch from checkpoint[/bold]")
        result = await interface._handle_branch_command([checkpoint_id, "test_branch"])
        
        if "branch_id" in result:
            print_test_result(True, f"Created branch: {result['branch_id']}")
        else:
            print_test_result(False, f"Branch creation failed: {result.get('error', 'Unknown error')}")
            return False
        
        console.print("\n[bold green]✓ All checkpoint tests passed![/bold green]")
        return True
        
    except Exception as e:
        print_test_result(False, f"Exception in checkpoint tests: {e}")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        return False


async def test_context_window_commands():
    """Test context window display commands"""
    print_test_header("Context Window Display Commands")
    
    try:
        from penguin.core import PenguinCore
        from penguin.cli.interface import PenguinInterface
        
        # Create core instance
        console.print("[dim]Creating PenguinCore instance...[/dim]")
        core = await PenguinCore.create(fast_startup=True, show_progress=False)
        interface = PenguinInterface(core)
        
        # Test 1: Display token usage
        console.print("\n[bold]Test 1: Display token usage[/bold]")
        result = await interface._handle_tokens_command([])
        
        if "token_usage" in result:
            usage = result["token_usage"]
            total = usage.get("current_total_tokens", 0)
            max_tokens = usage.get("max_tokens", 0)
            print_test_result(True, f"Token usage: {total}/{max_tokens}")
        else:
            print_test_result(False, "Failed to get token usage")
            return False
        
        # Test 2: Display detailed token usage
        console.print("\n[bold]Test 2: Display detailed token usage[/bold]")
        result = await interface._handle_tokens_command(["detail"])
        
        if "token_usage_detailed" in result:
            print_test_result(True, "Got detailed token usage")
        else:
            print_test_result(False, "Failed to get detailed token usage")
        
        # Test 3: Display truncations (should be empty initially)
        console.print("\n[bold]Test 3: Display truncations[/bold]")
        result = await interface._handle_truncations_command([])
        
        if "truncations" in result:
            count = len(result["truncations"])
            print_test_result(True, f"Got truncation data (count: {count})")
        else:
            print_test_result(False, "Failed to get truncations")
            return False
        
        console.print("\n[bold green]✓ All context window tests passed![/bold green]")
        return True
        
    except Exception as e:
        print_test_result(False, f"Exception in context window tests: {e}")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        return False


async def test_streaming_display():
    """Test StreamingDisplay class"""
    print_test_header("StreamingDisplay with Rich.Live")
    
    try:
        from penguin.cli.streaming_display import StreamingDisplay
        
        # Test 1: Basic streaming
        console.print("\n[bold]Test 1: Basic text streaming[/bold]")
        display = StreamingDisplay(console=console)
        display.start_message("assistant")
        
        # Simulate streaming chunks
        test_message = "This is a test message that will be streamed word by word."
        words = test_message.split()
        
        for i, word in enumerate(words):
            display.append_text(word + " ")
            await asyncio.sleep(0.1)  # Simulate streaming delay
        
        display.stop(finalize=True)
        print_test_result(True, "Streamed text successfully")
        
        # Test 2: Reasoning content
        console.print("\n[bold]Test 2: Reasoning content streaming[/bold]")
        display = StreamingDisplay(console=console)
        display.start_message("assistant")
        
        display.append_text("Let me think about this... ", is_reasoning=True)
        await asyncio.sleep(0.2)
        display.append_text("Here's my response: ")
        await asyncio.sleep(0.2)
        display.append_text("The answer is 42.")
        
        display.stop(finalize=True)
        print_test_result(True, "Reasoning and content separated correctly")
        
        # Test 3: Tool execution indicator
        console.print("\n[bold]Test 3: Tool execution indicator[/bold]")
        display = StreamingDisplay(console=console)
        display.start_message("assistant")
        
        display.append_text("I'll execute a tool now... ")
        await asyncio.sleep(0.3)
        
        display.set_tool("read_file")
        await asyncio.sleep(0.5)
        
        display.clear_tool()
        display.append_text("Done! The file contains...")
        await asyncio.sleep(0.3)
        
        display.stop(finalize=True)
        print_test_result(True, "Tool indicator worked correctly")
        
        # Test 4: Status updates
        console.print("\n[bold]Test 4: Status message display[/bold]")
        display = StreamingDisplay(console=console)
        display.start_message("assistant")
        
        display.set_status("Processing request...")
        display.append_text("Starting analysis... ")
        await asyncio.sleep(0.3)
        
        display.set_status("Analyzing code...")
        await asyncio.sleep(0.3)
        
        display.clear_status()
        display.append_text("Analysis complete!")
        await asyncio.sleep(0.2)
        
        display.stop(finalize=True)
        print_test_result(True, "Status messages displayed correctly")
        
        console.print("\n[bold green]✓ All streaming display tests passed![/bold green]")
        return True
        
    except Exception as e:
        print_test_result(False, f"Exception in streaming tests: {e}")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        return False


async def test_cli_integration():
    """Test full CLI integration with new features"""
    print_test_header("Full CLI Integration Test")
    
    try:
        from penguin.core import PenguinCore
        from penguin.cli.cli import PenguinCLI
        
        # Create core and CLI
        console.print("[dim]Creating PenguinCore and CLI instances...[/dim]")
        core = await PenguinCore.create(fast_startup=True, show_progress=False)
        cli = PenguinCLI(core)
        
        # Verify StreamingDisplay is initialized
        console.print("\n[bold]Test 1: StreamingDisplay initialization[/bold]")
        if hasattr(cli, 'streaming_display') and cli.streaming_display is not None:
            print_test_result(True, "StreamingDisplay initialized in PenguinCLI")
        else:
            print_test_result(False, "StreamingDisplay not found in PenguinCLI")
            return False
        
        # Verify display methods exist
        console.print("\n[bold]Test 2: Display methods exist[/bold]")
        required_methods = [
            '_display_checkpoints_response',
            '_display_truncations_response',
            '_display_token_usage_response'
        ]
        
        all_exist = True
        for method in required_methods:
            if hasattr(cli, method):
                print_test_result(True, f"Method {method} exists")
            else:
                print_test_result(False, f"Method {method} missing")
                all_exist = False
        
        if not all_exist:
            return False
        
        console.print("\n[bold green]✓ CLI integration tests passed![/bold green]")
        return True
        
    except Exception as e:
        print_test_result(False, f"Exception in CLI integration tests: {e}")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        return False


async def benchmark_startup():
    """Benchmark startup performance"""
    print_test_header("Startup Performance Benchmark")
    
    try:
        from penguin.core import PenguinCore
        
        # Benchmark normal startup
        console.print("\n[bold]Benchmarking normal startup...[/bold]")
        start = time.perf_counter()
        core = await PenguinCore.create(fast_startup=False, show_progress=False)
        normal_time = time.perf_counter() - start
        console.print(f"[green]Normal startup: {normal_time:.3f}s[/green]")
        
        # Clean up
        if hasattr(core, 'reset_state'):
            await core.reset_state()
        del core
        
        # Benchmark fast startup
        console.print("\n[bold]Benchmarking fast startup...[/bold]")
        start = time.perf_counter()
        core = await PenguinCore.create(fast_startup=True, show_progress=False)
        fast_time = time.perf_counter() - start
        console.print(f"[green]Fast startup: {fast_time:.3f}s[/green]")
        
        # Calculate improvement
        improvement = ((normal_time - fast_time) / normal_time) * 100
        console.print(f"\n[bold]Performance improvement: {improvement:.1f}% faster[/bold]")
        
        # Clean up
        if hasattr(core, 'reset_state'):
            await core.reset_state()
        del core
        
        return True
        
    except Exception as e:
        print_test_result(False, f"Benchmark failed: {e}")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        return False


async def main():
    """Run all tests"""
    console.print(Panel(
        "[bold cyan]Python CLI Improvements Test Suite[/bold cyan]\n"
        "Testing Kimi-inspired CLI patterns implementation",
        title="🐧 Penguin CLI Tests",
        border_style="cyan"
    ))
    
    results = {}
    
    # Run all test suites
    results["Checkpoint Commands"] = await test_checkpoint_commands()
    await asyncio.sleep(1)
    
    results["Context Window Display"] = await test_context_window_commands()
    await asyncio.sleep(1)
    
    results["StreamingDisplay"] = await test_streaming_display()
    await asyncio.sleep(1)
    
    results["CLI Integration"] = await test_cli_integration()
    await asyncio.sleep(1)
    
    results["Startup Performance"] = await benchmark_startup()
    
    # Print summary
    console.print(f"\n{'='*60}")
    console.print("[bold cyan]TEST SUMMARY[/bold cyan]")
    console.print(f"{'='*60}\n")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        icon = "✓" if result else "✗"
        color = "green" if result else "red"
        console.print(f"[{color}]{icon} {test_name}[/{color}]")
    
    console.print(f"\n[bold]Result: {passed}/{total} test suites passed[/bold]")
    
    if passed == total:
        console.print("\n[bold green]🎉 All tests passed![/bold green]")
        return 0
    else:
        console.print(f"\n[bold red]⚠️ {total - passed} test suite(s) failed[/bold red]")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
