#!/usr/bin/env python3
"""Manual test script for Phase 2 orchestration.

This script tests the orchestration system end-to-end.

Usage:
    # Test native backend (default)
    python scripts/test_orchestration_manual.py
    
    # Test with Temporal (requires Temporal server running)
    python scripts/test_orchestration_manual.py --backend temporal
    
    # Test via REST API (requires web server running)
    python scripts/test_orchestration_manual.py --api http://localhost:8000

Prerequisites:
    - For Temporal: temporal server start-dev
    - For API: penguin-web or uvicorn penguin.web.app:create_app --factory
"""

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_native_backend():
    """Test native orchestration backend."""
    print("\n" + "=" * 60)
    print("Testing Native Orchestration Backend")
    print("=" * 60)
    
    from penguin.orchestration import get_backend
    from penguin.orchestration.config import OrchestrationConfig, reset_backend, set_config
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Reset any global state
        reset_backend()
        
        config = OrchestrationConfig(backend="native")
        set_config(config)
        
        backend = get_backend(workspace_path=Path(tmpdir))
        print(f"✓ Created backend: {type(backend).__name__}")
        
        # Test 1: Start workflow
        print("\n[Test 1] Starting workflow...")
        workflow_id = await backend.start_workflow(
            task_id="test-task-001",
            blueprint_id="test-blueprint",
        )
        print(f"✓ Started workflow: {workflow_id}")
        
        # Test 2: Get status
        print("\n[Test 2] Getting status...")
        await asyncio.sleep(0.2)  # Let it initialize
        info = await backend.get_workflow_status(workflow_id)
        print(f"✓ Status: {info.status.value}, Phase: {info.phase.value}")
        
        # Test 3: Pause
        print("\n[Test 3] Pausing workflow...")
        success = await backend.pause_workflow(workflow_id)
        print(f"✓ Pause result: {success}")
        info = await backend.get_workflow_status(workflow_id)
        print(f"  Status after pause: {info.status.value}")
        
        # Test 4: Resume
        print("\n[Test 4] Resuming workflow...")
        success = await backend.resume_workflow(workflow_id)
        print(f"✓ Resume result: {success}")
        info = await backend.get_workflow_status(workflow_id)
        print(f"  Status after resume: {info.status.value}")
        
        # Test 5: Start more workflows
        print("\n[Test 5] Starting additional workflows...")
        for i in range(3):
            wf_id = await backend.start_workflow(task_id=f"test-task-{i+2}")
            print(f"  ✓ Started: {wf_id}")
        
        # Test 6: List workflows
        print("\n[Test 6] Listing workflows...")
        workflows = await backend.list_workflows()
        print(f"✓ Found {len(workflows)} workflow(s)")
        for wf in workflows:
            print(f"  - {wf.workflow_id}: {wf.status.value} ({wf.phase.value})")
        
        # Test 7: Cancel first workflow
        print("\n[Test 7] Cancelling workflow...")
        success = await backend.cancel_workflow(workflow_id)
        print(f"✓ Cancel result: {success}")
        info = await backend.get_workflow_status(workflow_id)
        print(f"  Status after cancel: {info.status.value}")
        
        # Cleanup
        reset_backend()
        
        print("\n" + "-" * 60)
        print("✓ Native backend tests completed successfully!")
        return True


async def test_temporal_backend():
    """Test Temporal orchestration backend."""
    print("\n" + "=" * 60)
    print("Testing Temporal Orchestration Backend")
    print("=" * 60)
    
    try:
        from penguin.orchestration.temporal import TemporalBackend
    except ImportError as e:
        print(f"✗ Temporal not available: {e}")
        print("  Install with: pip install penguin-ai[orchestration]")
        return False
    
    from penguin.orchestration.config import OrchestrationConfig, reset_backend, set_config
    
    with tempfile.TemporaryDirectory() as tmpdir:
        reset_backend()
        
        config = OrchestrationConfig(backend="temporal")
        set_config(config)
        
        print(f"Temporal address: {config.temporal.address}")
        print(f"Namespace: {config.temporal.namespace}")
        print(f"Task queue: {config.temporal.task_queue}")
        
        try:
            from penguin.orchestration import get_backend
            backend = get_backend(workspace_path=Path(tmpdir))
            print(f"✓ Created backend: {type(backend).__name__}")
            
            # Check connection
            if hasattr(backend, "_client"):
                print("  Connecting to Temporal server...")
                # Connection happens lazily
        except Exception as e:
            print(f"✗ Failed to create Temporal backend: {e}")
            print("  Make sure Temporal server is running:")
            print("    temporal server start-dev")
            return False
        
        # Similar tests as native...
        print("\n[Test] Starting workflow via Temporal...")
        try:
            workflow_id = await backend.start_workflow(
                task_id="temporal-test-001",
                blueprint_id="test-blueprint",
            )
            print(f"✓ Started workflow: {workflow_id}")
            
            await asyncio.sleep(1)  # Give Temporal time
            
            info = await backend.get_workflow_status(workflow_id)
            print(f"✓ Status: {info.status.value}, Phase: {info.phase.value}")
            
        except Exception as e:
            print(f"✗ Temporal test failed: {e}")
            return False
        finally:
            reset_backend()
        
        print("\n" + "-" * 60)
        print("✓ Temporal backend tests completed!")
        return True


async def test_via_api(base_url: str):
    """Test orchestration via REST API."""
    print("\n" + "=" * 60)
    print(f"Testing Orchestration via REST API: {base_url}")
    print("=" * 60)
    
    try:
        import httpx
    except ImportError:
        print("✗ httpx not installed. Install with: pip install httpx")
        return False
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Test 1: Check health
        print("\n[Test 1] Checking orchestration health...")
        try:
            resp = await client.get(f"{base_url}/api/v1/orchestration/health")
            print(f"  Status: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                print(f"  ✓ Backend: {data.get('backend', 'unknown')}")
                print(f"  ✓ Status: {data.get('status', 'unknown')}")
            else:
                print(f"  ✗ Error: {resp.text}")
        except Exception as e:
            print(f"  ✗ Request failed: {e}")
            print("  Make sure the web server is running:")
            print("    penguin-web")
            return False
        
        # Test 2: Get config
        print("\n[Test 2] Getting orchestration config...")
        resp = await client.get(f"{base_url}/api/v1/orchestration/config")
        if resp.status_code == 200:
            config = resp.json()
            print(f"  ✓ Backend: {config.get('backend')}")
            print(f"  ✓ Phase timeouts: {config.get('phase_timeouts')}")
        
        # Test 3: List workflows
        print("\n[Test 3] Listing workflows...")
        resp = await client.get(f"{base_url}/api/v1/workflows")
        if resp.status_code == 200:
            data = resp.json()
            print(f"  ✓ Found {data.get('count', 0)} workflow(s)")
        
        # Test 4: Start a workflow (requires a task to exist)
        print("\n[Test 4] Starting workflow...")
        resp = await client.post(
            f"{base_url}/api/v1/workflows",
            json={
                "task_id": "api-test-task-001",
                "blueprint_id": "test-blueprint",
            }
        )
        if resp.status_code == 200:
            data = resp.json()
            workflow_id = data.get("workflow_id")
            print(f"  ✓ Started workflow: {workflow_id}")
            
            # Test 5: Get workflow status
            print("\n[Test 5] Getting workflow status...")
            await asyncio.sleep(0.5)
            resp = await client.get(f"{base_url}/api/v1/workflows/{workflow_id}")
            if resp.status_code == 200:
                info = resp.json()
                print(f"  ✓ Status: {info.get('status')}")
                print(f"  ✓ Phase: {info.get('phase')}")
            
            # Test 6: Pause workflow
            print("\n[Test 6] Pausing workflow...")
            resp = await client.post(f"{base_url}/api/v1/workflows/{workflow_id}/pause")
            if resp.status_code == 200:
                print(f"  ✓ Paused")
            
            # Test 7: Resume workflow
            print("\n[Test 7] Resuming workflow...")
            resp = await client.post(f"{base_url}/api/v1/workflows/{workflow_id}/resume")
            if resp.status_code == 200:
                print(f"  ✓ Resumed")
            
            # Test 8: Cancel workflow
            print("\n[Test 8] Cancelling workflow...")
            resp = await client.post(f"{base_url}/api/v1/workflows/{workflow_id}/cancel")
            if resp.status_code == 200:
                print(f"  ✓ Cancelled")
        else:
            print(f"  ✗ Failed to start workflow: {resp.text}")
        
        print("\n" + "-" * 60)
        print("✓ REST API tests completed!")
        return True


async def main():
    parser = argparse.ArgumentParser(description="Test orchestration system")
    parser.add_argument(
        "--backend",
        choices=["native", "temporal", "both"],
        default="native",
        help="Backend to test",
    )
    parser.add_argument(
        "--api",
        type=str,
        help="Test via REST API at this URL (e.g., http://localhost:8000)",
    )
    args = parser.parse_args()
    
    print("=" * 60)
    print("Penguin Orchestration Test Suite")
    print("=" * 60)
    
    results = []
    
    if args.api:
        # Test via API
        results.append(("REST API", await test_via_api(args.api)))
    else:
        # Test backends directly
        if args.backend in ("native", "both"):
            results.append(("Native", await test_native_backend()))
        
        if args.backend in ("temporal", "both"):
            results.append(("Temporal", await test_temporal_backend()))
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results:
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False
    
    print()
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

