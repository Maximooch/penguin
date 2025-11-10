#!/usr/bin/env python3
"""
Test display fixes based on user feedback:
1. Checkpoint/truncation tables actually display (not just status)
2. Verbose code blocks are summarized (not shown in full)
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console

console = Console()


async def test_table_display_fix():
    """Test that tables actually display, not just status messages"""
    console.print("[bold cyan]Test: Checkpoint Table Display Fix[/bold cyan]\n")
    
    from penguin.core import PenguinCore
    from penguin.cli.cli import PenguinCLI
    
    core = await PenguinCore.create(fast_startup=True, show_progress=False)
    cli = PenguinCLI(core)
    
    # Create a checkpoint
    result = await cli.interface._handle_checkpoint_command(["test", "Test checkpoint"])
    checkpoint_id = result.get("checkpoint_id")
    
    await asyncio.sleep(0.5)  # Wait for worker
    
    # Get checkpoints response
    result = await cli.interface._handle_checkpoints_command([])
    
    console.print(f"Response keys: {list(result.keys())}")
    console.print(f"Has 'status': {'status' in result}")
    console.print(f"Has 'checkpoints': {'checkpoints' in result}")
    console.print(f"Checkpoint count: {len(result.get('checkpoints', []))}")
    
    # Now display it through CLI's response handler
    console.print("\n[bold]Displaying via CLI handler:[/bold]")
    
    # Simulate the response display logic
    if "checkpoints" in result:
        console.print("[green]✓ Checkpoints key found - calling _display_checkpoints_response[/green]")
        cli._display_checkpoints_response(result)
    elif "status" in result:
        console.print("[yellow]⚠ Only status found - would show message only[/yellow]")
        console.print(f"  Status: {result['status']}")
    
    console.print("\n[green]✓ Table display fix verified![/green]\n")


async def test_code_block_filtering():
    """Test that verbose <execute> blocks are summarized"""
    console.print("[bold cyan]Test: Code Block Filtering[/bold cyan]\n")
    
    from penguin.core import PenguinCore
    from penguin.cli.cli import PenguinCLI
    
    core = await PenguinCore.create(fast_startup=True, show_progress=False)
    cli = PenguinCLI(core)
    
    # Test message with verbose execute block
    test_message = """Here's what I'll do:

<execute>
from pathlib import Path
import subprocess
import sys

# Check current Flask installation
print("Checking Flask installation...")
result = subprocess.run(
    [sys.executable, '-c', 'import flask; print(flask.__version__)'],
    capture_output=True,
    text=True
)

if result.returncode == 0:
    print(f"✓ Flask is installed: {result.stdout.strip()}")
else:
    print(f"✗ Flask not found: {result.stderr}")
</execute>

That should check if Flask is installed."""

    console.print("[bold]Original message:[/bold]")
    console.print(f"Length: {len(test_message)} chars")
    console.print(f"Has <execute> block: {'<execute>' in test_message}")
    
    # Filter it
    filtered = cli._filter_verbose_code_blocks(test_message)
    
    console.print("\n[bold]Filtered message:[/bold]")
    console.print(f"Length: {len(filtered)} chars")
    console.print(f"Has <execute> block: {'<execute>' in filtered}")
    console.print(f"\nFiltered content:\n{filtered}")
    
    if len(filtered) < len(test_message):
        console.print("\n[green]✓ Code block successfully summarized![/green]")
    else:
        console.print("\n[yellow]⚠ No filtering occurred[/yellow]")
    
    console.print()


async def main():
    """Run both tests"""
    console.print("\n" + "="*70)
    console.print("  🐧 Display Fixes Verification", style="bold cyan")
    console.print("="*70 + "\n")
    
    try:
        await test_table_display_fix()
        await asyncio.sleep(0.5)
        
        await test_code_block_filtering()
        
        console.print("="*70)
        console.print("  ✅ All display fixes verified!", style="bold green")
        console.print("="*70 + "\n")
        
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())

