#!/usr/bin/env python3
"""
Interactive CLI demonstration of the conversation plane checkpointing system.

This script provides a simple command-line interface to test and demonstrate
the checkpointing functionality in an interactive way.
"""

import asyncio
import sys
from pathlib import Path

# Add the penguin package to the path
sys.path.insert(0, str(Path(__file__).parent))

from penguin.core import PenguinCore


async def main():
    """Interactive checkpoint demonstration."""
    print("🐧 Penguin Checkpoint Demo")
    print("=" * 30)
    print("Available commands:")
    print("  /checkpoint [name] - Create manual checkpoint")
    print("  /list - List all checkpoints")
    print("  /rollback <index> - Rollback to checkpoint by index")
    print("  /branch <index> [name] - Create branch from checkpoint by index")
    print("  /stats - Show checkpoint statistics")
    print("  /quit - Exit")
    print()
    print("💡 Tip: Use the index numbers from /list (e.g., '/rollback 1' or '/branch 2 my-branch')")
    print()
    
    # Initialize PenguinCore
    print("Initializing Penguin...")
    core = await PenguinCore.create(show_progress=False)
    
    # Check if checkpointing is enabled
    stats = core.get_checkpoint_stats()
    if not stats['enabled']:
        print("❌ Checkpointing is not enabled!")
        return
    
    print(f"✅ Checkpointing enabled (frequency: {stats['config']['frequency']})")
    print()
    
    # Keep track of checkpoint mapping for easy reference
    checkpoint_mapping = {}
    
    def update_checkpoint_mapping():
        """Update the mapping between indices and checkpoint IDs."""
        nonlocal checkpoint_mapping
        checkpoints = core.list_checkpoints(limit=50)
        checkpoint_mapping = {i+1: cp['id'] for i, cp in enumerate(checkpoints)}
        return checkpoints
    
    while True:
        try:
            user_input = input("You: ").strip()
            
            if not user_input:
                continue
                
            if user_input == "/quit":
                break
                
            elif user_input.startswith("/checkpoint"):
                parts = user_input.split(" ", 1)
                name = parts[1] if len(parts) > 1 else None
                checkpoint_id = await core.create_checkpoint(name=name)
                print(f"📍 Created checkpoint: {checkpoint_id}")
                # Update mapping after creating new checkpoint
                update_checkpoint_mapping()
                
            elif user_input == "/list":
                checkpoints = update_checkpoint_mapping()
                if not checkpoints:
                    print("No checkpoints found.")
                else:
                    print("📋 Checkpoints:")
                    for i, cp in enumerate(checkpoints):
                        name = cp.get('name') or 'Auto checkpoint'
                        created_at = cp['created_at'][:19].replace('T', ' ')  # Format timestamp
                        print(f"  {i+1:2d}. {cp['id'][:16]}... ({cp['type']}) - {name}")
                        print(f"      Created: {created_at} | Messages: {cp['message_count']}")
                        
            elif user_input.startswith("/rollback"):
                parts = user_input.split(" ", 1)
                if len(parts) < 2:
                    print("Usage: /rollback <index>")
                    print("Use /list to see available checkpoint indices")
                    continue
                    
                try:
                    index = int(parts[1])
                    if index not in checkpoint_mapping:
                        print(f"❌ Invalid index {index}. Use /list to see available checkpoints.")
                        continue
                        
                    checkpoint_id = checkpoint_mapping[index]
                    success = await core.rollback_to_checkpoint(checkpoint_id)
                    if success:
                        print(f"⏪ Rolled back to checkpoint #{index} ({checkpoint_id[:16]}...)")
                        # Update mapping after rollback
                        update_checkpoint_mapping()
                    else:
                        print(f"❌ Failed to rollback to checkpoint #{index}")
                except ValueError:
                    print("❌ Index must be a number. Use /list to see available indices.")
                    
            elif user_input.startswith("/branch"):
                parts = user_input.split(" ")
                if len(parts) < 2:
                    print("Usage: /branch <index> [name]")
                    print("Use /list to see available checkpoint indices")
                    continue
                    
                try:
                    index = int(parts[1])
                    if index not in checkpoint_mapping:
                        print(f"❌ Invalid index {index}. Use /list to see available checkpoints.")
                        continue
                        
                    checkpoint_id = checkpoint_mapping[index]
                    name = " ".join(parts[2:]) if len(parts) > 2 else f"Branch from #{index}"
                    branch_id = await core.branch_from_checkpoint(checkpoint_id, name=name)
                    if branch_id:
                        print(f"🌿 Created branch '{name}': {branch_id}")
                        # Update mapping after creating branch
                        update_checkpoint_mapping()
                    else:
                        print(f"❌ Failed to create branch from checkpoint #{index}")
                except ValueError:
                    print("❌ Index must be a number. Use /list to see available indices.")
                    
            elif user_input == "/stats":
                stats = core.get_checkpoint_stats()
                print("📊 Checkpoint Statistics:")
                print(f"  Total: {stats['total_checkpoints']}")
                print(f"  Auto: {stats['auto_checkpoints']}")
                print(f"  Manual: {stats['manual_checkpoints']}")
                print(f"  Branches: {stats['branch_checkpoints']}")
                print(f"  Frequency: Every {stats['config']['frequency']} message(s)")
                print(f"  Retention: {stats['config']['retention_hours']}h / {stats['config']['max_age_days']}d")
                
            elif user_input.startswith("/help") or user_input == "/?":
                print("🐧 Available Commands:")
                print("  /checkpoint [name]    - Create a manual checkpoint with optional name")
                print("  /list                 - List all checkpoints with indices")
                print("  /rollback <index>     - Rollback to checkpoint by index number")
                print("  /branch <index> [name] - Create branch from checkpoint by index")
                print("  /stats                - Show checkpoint system statistics")
                print("  /help or /?           - Show this help message")
                print("  /quit                 - Exit the demo")
                print()
                print("💡 Examples:")
                print("  /checkpoint Important milestone")
                print("  /rollback 3")
                print("  /branch 2 experimental-feature")
                
            else:
                # Regular message
                response = await core.process(user_input)
                assistant_response = response.get('assistant_response', 'No response')
                print(f"🐧: {assistant_response}")
                # Update mapping after each message (auto-checkpoints may be created)
                update_checkpoint_mapping()
                
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
    
    print("\nDemo completed!")


if __name__ == "__main__":
    asyncio.run(main()) 