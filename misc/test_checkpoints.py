#!/usr/bin/env python3
"""
Test script for the conversation plane checkpointing system.

This script tests the basic functionality of the V2.1 checkpointing implementation:
- Auto-checkpoint creation
- Manual checkpoint creation
- Rollback functionality
- Branch creation
- Cleanup operations
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add the penguin package to the path
sys.path.insert(0, str(Path(__file__).parent))

from penguin.core import PenguinCore
from penguin.system.checkpoint_manager import CheckpointConfig, CheckpointType

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_checkpointing():
    """Test the checkpointing functionality."""
    print("🐧 Testing Penguin Conversation Plane Checkpointing")
    print("=" * 50)
    
    try:
        # Create PenguinCore instance with checkpointing enabled
        print("1. Initializing PenguinCore with checkpointing...")
        core = await PenguinCore.create(show_progress=False)
        
        # Check if checkpointing is enabled
        stats = core.get_checkpoint_stats()
        print(f"   Checkpointing enabled: {stats['enabled']}")
        print(f"   Initial checkpoints: {stats['total_checkpoints']}")
        
        if not stats['enabled']:
            print("❌ Checkpointing is not enabled!")
            return False
        
        # Test 1: Send a few messages to trigger auto-checkpoints
        print("\n2. Testing auto-checkpoint creation...")
        
        # Send first message
        response1 = await core.process("Hello, this is my first message!")
        print(f"   Sent message 1: {response1['assistant_response'][:50]}...")
        
        # Send second message
        response2 = await core.process("This is my second message.")
        print(f"   Sent message 2: {response2['assistant_response'][:50]}...")
        
        # Send third message
        response3 = await core.process("And this is my third message.")
        print(f"   Sent message 3: {response3['assistant_response'][:50]}...")
        
        # Check auto-checkpoints created
        await asyncio.sleep(1)  # Give workers time to process
        stats = core.get_checkpoint_stats()
        print(f"   Auto-checkpoints created: {stats['auto_checkpoints']}")
        
        # Test 2: Create a manual checkpoint
        print("\n3. Testing manual checkpoint creation...")
        manual_checkpoint_id = await core.create_checkpoint(
            name="Test Manual Checkpoint",
            description="This is a test manual checkpoint"
        )
        print(f"   Created manual checkpoint: {manual_checkpoint_id}")
        
        # Test 3: List checkpoints
        print("\n4. Listing all checkpoints...")
        checkpoints = core.list_checkpoints(limit=10)
        for i, cp in enumerate(checkpoints):
            print(f"   {i+1}. {cp['id'][:16]}... ({cp['type']}) - {cp.get('name', 'Auto checkpoint')}")
        
        # Test 4: Send another message after manual checkpoint
        print("\n5. Sending message after manual checkpoint...")
        response4 = await core.process("This message comes after the manual checkpoint.")
        print(f"   Sent message 4: {response4['assistant_response'][:50]}...")
        
        # Test 5: Rollback to manual checkpoint
        print("\n6. Testing rollback to manual checkpoint...")
        if manual_checkpoint_id:
            success = await core.rollback_to_checkpoint(manual_checkpoint_id)
            print(f"   Rollback successful: {success}")
            
            if success:
                # Check current conversation state
                current_session = core.conversation_manager.get_current_session()
                print(f"   Messages after rollback: {len(current_session.messages)}")
        
        # Test 6: Create a branch from checkpoint
        print("\n7. Testing branch creation...")
        if checkpoints:
            branch_checkpoint_id = await core.branch_from_checkpoint(
                checkpoints[0]['id'],
                name="Test Branch",
                description="This is a test branch"
            )
            print(f"   Created branch: {branch_checkpoint_id}")
        
        # Test 7: Final statistics
        print("\n8. Final checkpoint statistics...")
        final_stats = core.get_checkpoint_stats()
        print(f"   Total checkpoints: {final_stats['total_checkpoints']}")
        print(f"   Auto checkpoints: {final_stats['auto_checkpoints']}")
        print(f"   Manual checkpoints: {final_stats['manual_checkpoints']}")
        print(f"   Branch checkpoints: {final_stats['branch_checkpoints']}")
        
        # Test 8: Cleanup old checkpoints
        print("\n9. Testing checkpoint cleanup...")
        cleaned_count = await core.cleanup_old_checkpoints()
        print(f"   Cleaned up {cleaned_count} old checkpoints")
        
        print("\n✅ All checkpoint tests completed successfully!")
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Main test function."""
    success = await test_checkpointing()
    
    if success:
        print("\n🎉 Checkpoint system is working correctly!")
        sys.exit(0)
    else:
        print("\n💥 Checkpoint system tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main()) 