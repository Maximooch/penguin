"""Tests for comprehensive health monitoring endpoint.

Tests the enhanced /api/v1/health endpoint that returns detailed metrics
for container monitoring and Link integration.
"""

import os
import time
import urllib.request
import urllib.error
import json
from typing import Any, Dict


BASE_URL = os.environ.get("PENGUIN_API_URL", "http://127.0.0.1:8000")


def _wait_for_server(timeout: int = 30) -> None:
    """Wait for server to be ready."""
    print(f"Waiting for server at {BASE_URL} (max {timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f"{BASE_URL}/api/v1/health", timeout=2) as resp:
                if resp.status == 200:
                    print(f"✓ Server ready after {time.time() - start:.1f}s")
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"Server not ready after {timeout}s")


def _get(path: str) -> Dict[str, Any]:
    """GET request helper."""
    url = f"{BASE_URL}{path}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        raise AssertionError(f"GET {path} failed: {e.code} {e.reason}\n{body}")


def test_health_endpoint_basic_structure():
    """Test that health endpoint returns expected top-level structure."""
    _wait_for_server()

    resp = _get("/api/v1/health")

    # Check top-level required fields
    required_fields = ["status", "timestamp", "uptime", "resource_usage",
                       "agent_capacity", "performance_metrics"]

    for field in required_fields:
        assert field in resp, f"Health response missing required field: {field}"

    print(f"✓ Health endpoint returns all required top-level fields: {required_fields}")


def test_health_status_values():
    """Test that health status is one of the expected values."""
    resp = _get("/api/v1/health")

    status = resp.get("status")
    valid_statuses = ["healthy", "degraded", "at_capacity"]

    assert status in valid_statuses, \
        f"Status '{status}' not in valid values: {valid_statuses}"

    print(f"✓ Health status is valid: {status}")


def test_health_timestamp_format():
    """Test that timestamp is in ISO format."""
    resp = _get("/api/v1/health")

    timestamp = resp.get("timestamp")
    assert timestamp is not None, "Timestamp is missing"

    # Verify it's a valid ISO format string
    from datetime import datetime
    try:
        parsed = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        print(f"✓ Timestamp is valid ISO format: {timestamp}")
    except (ValueError, AttributeError) as e:
        raise AssertionError(f"Timestamp not in valid ISO format: {timestamp}")


def test_uptime_structure():
    """Test uptime information structure."""
    resp = _get("/api/v1/health")

    uptime = resp.get("uptime")
    assert isinstance(uptime, dict), "Uptime should be a dictionary"

    required_uptime_fields = ["start_time", "uptime_seconds", "uptime_human"]
    for field in required_uptime_fields:
        assert field in uptime, f"Uptime missing field: {field}"

    # Validate types
    assert isinstance(uptime["uptime_seconds"], int), "uptime_seconds should be integer"
    assert isinstance(uptime["uptime_human"], str), "uptime_human should be string"
    assert uptime["uptime_seconds"] >= 0, "uptime_seconds should be non-negative"

    print(f"✓ Uptime structure valid: {uptime['uptime_seconds']}s ({uptime['uptime_human']})")


def test_resource_usage_structure():
    """Test resource usage metrics structure."""
    resp = _get("/api/v1/health")

    resource_usage = resp.get("resource_usage")
    assert isinstance(resource_usage, dict), "resource_usage should be a dictionary"

    required_fields = ["memory_mb", "memory_percent", "cpu_percent", "threads", "active_tasks"]
    for field in required_fields:
        assert field in resource_usage, f"resource_usage missing field: {field}"

    # Validate types and ranges
    assert isinstance(resource_usage["memory_mb"], (int, float)), "memory_mb should be numeric"
    assert isinstance(resource_usage["memory_percent"], (int, float)), "memory_percent should be numeric"
    assert isinstance(resource_usage["cpu_percent"], (int, float)), "cpu_percent should be numeric"
    assert isinstance(resource_usage["threads"], int), "threads should be integer"
    assert isinstance(resource_usage["active_tasks"], int), "active_tasks should be integer"

    # Check ranges
    assert resource_usage["memory_mb"] >= 0, "memory_mb should be non-negative"
    assert 0 <= resource_usage["memory_percent"] <= 100, "memory_percent should be 0-100"
    assert resource_usage["cpu_percent"] >= 0, "cpu_percent should be non-negative"
    assert resource_usage["threads"] >= 0, "threads should be non-negative"
    assert resource_usage["active_tasks"] >= 0, "active_tasks should be non-negative"

    print(f"✓ Resource usage structure valid:")
    print(f"  - Memory: {resource_usage['memory_mb']} MB ({resource_usage['memory_percent']}%)")
    print(f"  - CPU: {resource_usage['cpu_percent']}%")
    print(f"  - Threads: {resource_usage['threads']}")
    print(f"  - Active tasks: {resource_usage['active_tasks']}")


def test_agent_capacity_structure():
    """Test agent capacity metrics structure."""
    resp = _get("/api/v1/health")

    capacity = resp.get("agent_capacity")
    assert isinstance(capacity, dict), "agent_capacity should be a dictionary"

    required_fields = ["max", "active", "available", "utilization"]
    for field in required_fields:
        assert field in capacity, f"agent_capacity missing field: {field}"

    # Validate types
    assert isinstance(capacity["max"], int), "max should be integer"
    assert isinstance(capacity["active"], int), "active should be integer"
    assert isinstance(capacity["available"], int), "available should be integer"
    assert isinstance(capacity["utilization"], (int, float)), "utilization should be numeric"

    # Validate logic
    assert capacity["max"] >= 0, "max should be non-negative"
    assert capacity["active"] >= 0, "active should be non-negative"
    assert capacity["available"] >= 0, "available should be non-negative"
    assert 0 <= capacity["utilization"] <= 1, "utilization should be 0-1"

    # Check math
    assert capacity["active"] + capacity["available"] == capacity["max"], \
        "active + available should equal max"

    if capacity["max"] > 0:
        expected_utilization = capacity["active"] / capacity["max"]
        assert abs(capacity["utilization"] - expected_utilization) < 0.01, \
            "utilization calculation incorrect"

    print(f"✓ Agent capacity structure valid:")
    print(f"  - Max: {capacity['max']}")
    print(f"  - Active: {capacity['active']}")
    print(f"  - Available: {capacity['available']}")
    print(f"  - Utilization: {capacity['utilization'] * 100}%")


def test_performance_metrics_structure():
    """Test performance metrics structure."""
    resp = _get("/api/v1/health")

    metrics = resp.get("performance_metrics")
    assert isinstance(metrics, dict), "performance_metrics should be a dictionary"

    required_fields = [
        "request_count", "avg_latency_ms", "p95_latency_ms", "p99_latency_ms",
        "min_latency_ms", "max_latency_ms", "success_rate", "error_count",
        "task_count", "avg_task_duration_sec"
    ]

    for field in required_fields:
        assert field in metrics, f"performance_metrics missing field: {field}"

    # Validate types
    assert isinstance(metrics["request_count"], int), "request_count should be integer"
    assert isinstance(metrics["error_count"], int), "error_count should be integer"
    assert isinstance(metrics["task_count"], int), "task_count should be integer"

    # Numeric metrics
    numeric_fields = ["avg_latency_ms", "p95_latency_ms", "p99_latency_ms",
                      "min_latency_ms", "max_latency_ms", "success_rate",
                      "avg_task_duration_sec"]
    for field in numeric_fields:
        assert isinstance(metrics[field], (int, float)), f"{field} should be numeric"

    # Validate ranges
    assert metrics["request_count"] >= 0, "request_count should be non-negative"
    assert metrics["error_count"] >= 0, "error_count should be non-negative"
    assert metrics["task_count"] >= 0, "task_count should be non-negative"
    assert 0 <= metrics["success_rate"] <= 1, "success_rate should be 0-1"

    # Latency logic
    if metrics["request_count"] > 0:
        assert metrics["min_latency_ms"] <= metrics["avg_latency_ms"], \
            "min_latency should be <= avg_latency"
        assert metrics["avg_latency_ms"] <= metrics["max_latency_ms"], \
            "avg_latency should be <= max_latency"
        assert metrics["p95_latency_ms"] <= metrics["max_latency_ms"], \
            "p95_latency should be <= max_latency"
        assert metrics["p99_latency_ms"] <= metrics["max_latency_ms"], \
            "p99_latency should be <= max_latency"

    print(f"✓ Performance metrics structure valid:")
    print(f"  - Requests: {metrics['request_count']} (success rate: {metrics['success_rate'] * 100}%)")
    print(f"  - Latency: avg={metrics['avg_latency_ms']}ms, p95={metrics['p95_latency_ms']}ms, p99={metrics['p99_latency_ms']}ms")
    print(f"  - Tasks: {metrics['task_count']} (avg duration: {metrics['avg_task_duration_sec']}s)")
    print(f"  - Errors: {metrics['error_count']}")


def test_components_health():
    """Test component health information if available."""
    resp = _get("/api/v1/health")

    # Components are optional (only present if core is available)
    if "components" in resp:
        components = resp["components"]
        assert isinstance(components, dict), "components should be a dictionary"

        expected_components = [
            "core_initialized",
            "engine_available",
            "api_client_ready",
            "tool_manager_ready",
            "conversation_manager_ready"
        ]

        for component in expected_components:
            if component in components:
                assert isinstance(components[component], bool), \
                    f"{component} should be boolean"

        print(f"✓ Component health available:")
        for component, status in components.items():
            print(f"  - {component}: {status}")
    else:
        print("⊘ Component health not available (core may not be initialized)")


def test_agents_information():
    """Test agent information if available."""
    resp = _get("/api/v1/health")

    # Agents info is optional
    if "agents" in resp:
        agents = resp["agents"]
        assert isinstance(agents, dict), "agents should be a dictionary"

        if "total" in agents:
            assert isinstance(agents["total"], int), "agents.total should be integer"
            assert agents["total"] >= 0, "agents.total should be non-negative"

        if "active" in agents:
            assert isinstance(agents["active"], int), "agents.active should be integer"
            assert agents["active"] >= 0, "agents.active should be non-negative"

        print(f"✓ Agent information available: {agents}")
    else:
        print("⊘ Agent information not available")


def test_health_status_transitions():
    """Test that health status reflects system state correctly."""
    resp = _get("/api/v1/health")

    status = resp["status"]
    capacity = resp["agent_capacity"]
    resource_usage = resp["resource_usage"]

    # If at capacity, status should reflect it
    if capacity["available"] == 0 and capacity["max"] > 0:
        assert status == "at_capacity", \
            f"Status should be 'at_capacity' when no capacity available, got '{status}'"
        print("✓ Status correctly shows 'at_capacity'")

    # If resources are high, status should be degraded
    if resource_usage["memory_percent"] > 90 or resource_usage["cpu_percent"] > 90:
        assert status in ["degraded", "at_capacity"], \
            f"Status should be 'degraded' or 'at_capacity' with high resource usage, got '{status}'"
        print("✓ Status correctly shows 'degraded' with high resource usage")

    # Otherwise should be healthy
    if capacity["available"] > 0 and resource_usage["memory_percent"] <= 90 and resource_usage["cpu_percent"] <= 90:
        assert status == "healthy", \
            f"Status should be 'healthy' with available capacity and normal resources, got '{status}'"
        print("✓ Status correctly shows 'healthy'")


def test_health_endpoint_performance():
    """Test that the health endpoint responds quickly."""
    # Make multiple requests and measure latency
    latencies = []

    for _ in range(5):
        start = time.time()
        _get("/api/v1/health")
        latency_ms = (time.time() - start) * 1000
        latencies.append(latency_ms)

    avg_latency = sum(latencies) / len(latencies)
    max_latency = max(latencies)

    # Health endpoint should be fast (under 1 second)
    assert max_latency < 1000, f"Health endpoint too slow: max {max_latency}ms"

    print(f"✓ Health endpoint performance acceptable:")
    print(f"  - Average latency: {avg_latency:.2f}ms")
    print(f"  - Max latency: {max_latency:.2f}ms")


def test_health_endpoint_stability():
    """Test that health endpoint returns consistent structure across multiple calls."""
    _wait_for_server()

    # Make multiple requests
    responses = [_get("/api/v1/health") for _ in range(3)]

    # All should have same structure
    first_keys = set(responses[0].keys())
    for i, resp in enumerate(responses[1:], 1):
        assert set(resp.keys()) == first_keys, \
            f"Response {i} has different keys than first response"

    print(f"✓ Health endpoint returns consistent structure across {len(responses)} requests")


def test_json_serialization():
    """Test that health response is valid JSON with no serialization errors."""
    resp = _get("/api/v1/health")

    # Try to re-serialize to ensure no problematic values
    try:
        json_str = json.dumps(resp)
        # And deserialize back
        parsed = json.loads(json_str)
        assert parsed == resp, "Re-serialized JSON doesn't match original"
        print("✓ Health response serializes/deserializes correctly")
    except (TypeError, ValueError) as e:
        raise AssertionError(f"Health response contains non-serializable data: {e}")


if __name__ == "__main__":
    """Run all health monitoring tests."""
    print("=" * 60)
    print("Health Monitoring Tests")
    print("=" * 60)
    print()

    tests = [
        ("Basic structure", test_health_endpoint_basic_structure),
        ("Status values", test_health_status_values),
        ("Timestamp format", test_health_timestamp_format),
        ("Uptime structure", test_uptime_structure),
        ("Resource usage structure", test_resource_usage_structure),
        ("Agent capacity structure", test_agent_capacity_structure),
        ("Performance metrics structure", test_performance_metrics_structure),
        ("Components health", test_components_health),
        ("Agents information", test_agents_information),
        ("Status transitions", test_health_status_transitions),
        ("Endpoint performance", test_health_endpoint_performance),
        ("Endpoint stability", test_health_endpoint_stability),
        ("JSON serialization", test_json_serialization),
    ]

    passed = 0
    failed = 0
    skipped = 0

    for name, test_func in tests:
        try:
            print(f"\n[{name}]")
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"✗ FAILED: {e}")
            failed += 1
        except Exception as e:
            if "Skipping" in str(e) or "⊘" in str(e):
                skipped += 1
            else:
                print(f"✗ ERROR: {e}")
                failed += 1

    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped")
    print("=" * 60)

    exit(0 if failed == 0 else 1)
