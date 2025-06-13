#!/usr/bin/env python3
"""
Test script to compare Penguin startup performance with and without fast startup mode.

This script runs Penguin initialization in both modes and provides detailed
performance analysis.
"""

import asyncio
import time
import sys
from pathlib import Path

# Add penguin to path
sys.path.insert(0, str(Path(__file__).parent))

from penguin.core import PenguinCore
from penguin.utils.profiling import profiler, enable_profiling, reset_profiling, print_startup_report


async def test_startup_performance():
    """Test and compare startup performance."""
    print("="*80)
    print("PENGUIN STARTUP PERFORMANCE TEST")
    print("="*80)
    
    # Enable profiling
    enable_profiling()
    
    # Test 1: Normal startup (with memory indexing)
    print("\n🐧 TEST 1: Normal Startup (with memory indexing)")
    print("-" * 50)
    
    reset_profiling()
    start_time = time.perf_counter()
    
    try:
        core_normal = await PenguinCore.create(
            fast_startup=False,
            show_progress=False
        )
        normal_time = time.perf_counter() - start_time
        
        print(f"✓ Normal startup completed in {normal_time:.4f} seconds")
        print("\nNormal startup report:")
        core_normal.print_startup_report()
        
        # Get memory provider status
        memory_status = core_normal.get_memory_provider_status()
        print(f"\nMemory provider status: {memory_status}")
        
    except Exception as e:
        print(f"✗ Normal startup failed: {e}")
        normal_time = float('inf')
    
    # Reset profiling for second test
    reset_profiling()
    
    # Test 2: Fast startup (deferred memory indexing)
    print("\n🚀 TEST 2: Fast Startup (deferred memory indexing)")
    print("-" * 50)
    
    start_time = time.perf_counter()
    
    try:
        core_fast = await PenguinCore.create(
            fast_startup=True,
            show_progress=False
        )
        fast_time = time.perf_counter() - start_time
        
        print(f"✓ Fast startup completed in {fast_time:.4f} seconds")
        print("\nFast startup report:")
        core_fast.print_startup_report()
        
        # Get memory provider status
        memory_status = core_fast.get_memory_provider_status()
        print(f"\nMemory provider status: {memory_status}")
        
    except Exception as e:
        print(f"✗ Fast startup failed: {e}")
        fast_time = float('inf')
    
    # Comparison
    print("\n📊 PERFORMANCE COMPARISON")
    print("=" * 50)
    print(f"Normal startup time: {normal_time:.4f} seconds")
    print(f"Fast startup time:   {fast_time:.4f} seconds")
    
    if normal_time != float('inf') and fast_time != float('inf'):
        improvement = ((normal_time - fast_time) / normal_time) * 100
        speedup = normal_time / fast_time if fast_time > 0 else float('inf')
        print(f"Performance improvement: {improvement:.1f}% faster")
        print(f"Speedup factor: {speedup:.2f}x")
        
        if improvement > 0:
            print("🎉 Fast startup mode is working!")
        else:
            print("⚠️ Fast startup mode might not be working as expected")
    
    # Test 3: Memory tool lazy loading
    print("\n🧠 TEST 3: Memory Tool Lazy Loading")
    print("-" * 50)
    
    if 'core_fast' in locals():
        print("Testing memory search on fast startup core...")
        
        # This should trigger lazy loading of memory provider
        start_lazy_time = time.perf_counter()
        try:
            # Try to use memory search tool
            result = await core_fast.tool_manager.perform_memory_search("test query", k=1)
            lazy_time = time.perf_counter() - start_lazy_time
            
            print(f"✓ Memory search completed in {lazy_time:.4f} seconds (includes lazy loading)")
            print(f"Result preview: {result[:100]}...")
            
            # Check memory provider status after lazy loading
            memory_status_after = core_fast.get_memory_provider_status()
            print(f"Memory provider status after lazy loading: {memory_status_after}")
            
        except Exception as e:
            print(f"✗ Memory search failed: {e}")
    
    print("\n" + "="*80)
    print("PERFORMANCE TEST COMPLETE")
    print("="*80)


async def test_memory_indexing_status():
    """Test memory indexing status monitoring."""
    print("\n🔍 MEMORY INDEXING STATUS MONITOR")
    print("-" * 50)
    
    # Create fast startup core
    core = await PenguinCore.create(fast_startup=True, show_progress=False)
    
    print("Initial memory status:")
    status = core.get_memory_provider_status()
    print(status)
    
    # Trigger memory provider initialization
    print("\nTriggering memory provider initialization...")
    await core.tool_manager.ensure_memory_provider()
    
    print("Memory status after initialization:")
    status = core.get_memory_provider_status()
    print(status)
    
    # Wait a bit and check indexing progress
    print("\nWaiting for background indexing...")
    await asyncio.sleep(2)
    
    print("Memory status after waiting:")
    status = core.get_memory_provider_status()
    print(status)


if __name__ == "__main__":
    # Run the performance test
    asyncio.run(test_startup_performance())
    
    # Run the memory indexing status test
    asyncio.run(test_memory_indexing_status()) 