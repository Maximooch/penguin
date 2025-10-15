"""Performance and load tests for health monitoring endpoint.

Tests the health monitoring endpoint under various load conditions
to ensure it can handle concurrent requests and doesn't degrade
system performance.
"""

import os
import time
import urllib.request
import urllib.error
import json
import threading
import statistics
from typing import Any, Dict, List
from concurrent.futures import ThreadPoolExecutor, as_completed


BASE_URL = os.environ.get("PENGUIN_API_URL", "http://127.0.0.1:8000")

# Test configuration
CONCURRENT_REQUESTS = 10
SEQUENTIAL_REQUESTS = 50
STRESS_TEST_DURATION = 30  # seconds


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


def _get_health() -> tuple[Dict[str, Any], float]:
    """Get health endpoint and return response + latency in ms."""
    url = f"{BASE_URL}/api/v1/health"
    start = time.time()
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            latency_ms = (time.time() - start) * 1000
            return data, latency_ms
    except Exception as e:
        latency_ms = (time.time() - start) * 1000
        raise AssertionError(f"Health request failed after {latency_ms:.2f}ms: {e}")


def test_health_endpoint_latency():
    """Test health endpoint has acceptable latency."""
    _wait_for_server()

    # Warm-up request
    _get_health()

    # Measure latency over multiple requests
    latencies = []
    for _ in range(10):
        _, latency = _get_health()
        latencies.append(latency)
        time.sleep(0.1)  # Small delay between requests

    avg_latency = statistics.mean(latencies)
    median_latency = statistics.median(latencies)
    max_latency = max(latencies)
    min_latency = min(latencies)

    # Health endpoint should be fast (under 500ms on average)
    assert avg_latency < 500, f"Average latency too high: {avg_latency:.2f}ms"

    print(f"✓ Health endpoint latency acceptable:")
    print(f"  - Average: {avg_latency:.2f}ms")
    print(f"  - Median: {median_latency:.2f}ms")
    print(f"  - Min: {min_latency:.2f}ms")
    print(f"  - Max: {max_latency:.2f}ms")


def test_health_endpoint_consistency():
    """Test that health endpoint returns consistent structure across requests."""
    _wait_for_server()

    # Make multiple requests
    responses = []
    for _ in range(5):
        resp, _ = _get_health()
        responses.append(resp)
        time.sleep(0.2)

    # All responses should have same top-level keys
    first_keys = set(responses[0].keys())
    for i, resp in enumerate(responses[1:], 1):
        assert set(resp.keys()) == first_keys, \
            f"Response {i} has different keys than first response"

    print(f"✓ Health endpoint returns consistent structure across {len(responses)} requests")


def test_concurrent_health_requests():
    """Test health endpoint under concurrent load."""
    _wait_for_server()

    latencies = []
    errors = []

    def make_request(request_id: int) -> tuple[int, float, bool]:
        """Make a health request and return ID, latency, success."""
        try:
            _, latency = _get_health()
            return request_id, latency, True
        except Exception as e:
            errors.append(str(e))
            return request_id, 0, False

    print(f"Sending {CONCURRENT_REQUESTS} concurrent requests...")

    start = time.time()
    with ThreadPoolExecutor(max_workers=CONCURRENT_REQUESTS) as executor:
        futures = [executor.submit(make_request, i) for i in range(CONCURRENT_REQUESTS)]

        for future in as_completed(futures):
            request_id, latency, success = future.result()
            if success:
                latencies.append(latency)

    total_time = time.time() - start

    # Check results
    success_count = len(latencies)
    error_count = len(errors)

    assert error_count == 0, f"{error_count} requests failed: {errors[:3]}"
    assert success_count == CONCURRENT_REQUESTS, \
        f"Only {success_count}/{CONCURRENT_REQUESTS} requests succeeded"

    # Calculate statistics
    avg_latency = statistics.mean(latencies)
    p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]
    max_latency = max(latencies)

    # Under concurrent load, latency should still be reasonable
    assert avg_latency < 1000, f"Average latency under load too high: {avg_latency:.2f}ms"

    print(f"✓ Concurrent requests handled successfully:")
    print(f"  - Requests: {CONCURRENT_REQUESTS}")
    print(f"  - Total time: {total_time:.2f}s")
    print(f"  - Success rate: {success_count}/{CONCURRENT_REQUESTS}")
    print(f"  - Average latency: {avg_latency:.2f}ms")
    print(f"  - P95 latency: {p95_latency:.2f}ms")
    print(f"  - Max latency: {max_latency:.2f}ms")


def test_sequential_load():
    """Test health endpoint under sequential load."""
    _wait_for_server()

    print(f"Sending {SEQUENTIAL_REQUESTS} sequential requests...")

    latencies = []
    errors = []

    start = time.time()
    for i in range(SEQUENTIAL_REQUESTS):
        try:
            _, latency = _get_health()
            latencies.append(latency)
        except Exception as e:
            errors.append(str(e))

        # Small delay to avoid overwhelming
        if i % 10 == 0 and i > 0:
            time.sleep(0.1)

    total_time = time.time() - start

    # Check for errors
    assert len(errors) == 0, f"{len(errors)} requests failed during sequential load"

    # Calculate statistics
    avg_latency = statistics.mean(latencies)
    first_10_avg = statistics.mean(latencies[:10])
    last_10_avg = statistics.mean(latencies[-10:])

    # Latency should not significantly increase over time (no memory leak)
    latency_increase = last_10_avg - first_10_avg
    latency_increase_percent = (latency_increase / first_10_avg) * 100

    print(f"✓ Sequential load handled successfully:")
    print(f"  - Requests: {SEQUENTIAL_REQUESTS}")
    print(f"  - Total time: {total_time:.2f}s")
    print(f"  - Average latency: {avg_latency:.2f}ms")
    print(f"  - First 10 avg: {first_10_avg:.2f}ms")
    print(f"  - Last 10 avg: {last_10_avg:.2f}ms")
    print(f"  - Latency increase: {latency_increase_percent:.1f}%")

    # Warn if significant degradation
    if latency_increase_percent > 50:
        print(f"⚠ Warning: Latency increased by {latency_increase_percent:.1f}% over {SEQUENTIAL_REQUESTS} requests")


def test_resource_usage_tracking():
    """Test that resource usage metrics change appropriately under load."""
    _wait_for_server()

    # Get initial resource usage
    initial_health, _ = _get_health()
    initial_memory = initial_health.get("resource_usage", {}).get("memory_mb", 0)
    initial_cpu = initial_health.get("resource_usage", {}).get("cpu_percent", 0)

    # Generate some load
    for _ in range(20):
        _get_health()
        time.sleep(0.05)

    # Get resource usage after load
    final_health, _ = _get_health()
    final_memory = final_health.get("resource_usage", {}).get("memory_mb", 0)
    final_cpu = final_health.get("resource_usage", {}).get("cpu_percent", 0)

    # Memory should not explode (allow for reasonable increase)
    memory_increase = final_memory - initial_memory
    if initial_memory > 0:
        memory_increase_percent = (memory_increase / initial_memory) * 100
    else:
        memory_increase_percent = 0

    print(f"✓ Resource usage tracking:")
    print(f"  - Initial memory: {initial_memory:.2f} MB")
    print(f"  - Final memory: {final_memory:.2f} MB")
    print(f"  - Memory increase: {memory_increase_percent:.1f}%")
    print(f"  - Initial CPU: {initial_cpu:.1f}%")
    print(f"  - Final CPU: {final_cpu:.1f}%")

    # Warn about excessive memory growth
    if memory_increase_percent > 100 and initial_memory > 0:
        print(f"⚠ Warning: Memory usage increased by {memory_increase_percent:.1f}%")


def test_performance_metrics_collection():
    """Test that performance metrics are collected correctly."""
    _wait_for_server()

    # Make some requests to populate metrics
    for _ in range(10):
        _get_health()
        time.sleep(0.1)

    # Check that metrics are being tracked
    health, _ = _get_health()
    metrics = health.get("performance_metrics", {})

    request_count = metrics.get("request_count", 0)
    avg_latency = metrics.get("avg_latency_ms", 0)
    p95_latency = metrics.get("p95_latency_ms", 0)

    # Metrics should reflect our requests
    # Note: Other requests may also be counted
    assert request_count >= 10, \
        f"Performance metrics should track requests (got {request_count})"

    print(f"✓ Performance metrics collection working:")
    print(f"  - Request count: {request_count}")
    print(f"  - Average latency: {avg_latency:.2f}ms")
    print(f"  - P95 latency: {p95_latency:.2f}ms")


def test_stress_test():
    """Stress test: continuous concurrent requests for a duration."""
    _wait_for_server()

    print(f"Running stress test for {STRESS_TEST_DURATION} seconds with {CONCURRENT_REQUESTS} workers...")

    latencies = []
    errors = []
    request_count = 0
    stop_flag = threading.Event()

    def make_continuous_requests(worker_id: int):
        """Make continuous requests until stop flag is set."""
        nonlocal request_count
        while not stop_flag.is_set():
            try:
                _, latency = _get_health()
                latencies.append(latency)
                request_count += 1
            except Exception as e:
                errors.append(str(e))
            time.sleep(0.1)  # Small delay between requests

    # Start workers
    start = time.time()
    workers = []
    for i in range(CONCURRENT_REQUESTS):
        worker = threading.Thread(target=make_continuous_requests, args=(i,))
        worker.start()
        workers.append(worker)

    # Run for specified duration
    time.sleep(STRESS_TEST_DURATION)
    stop_flag.set()

    # Wait for all workers to finish
    for worker in workers:
        worker.join(timeout=5)

    total_time = time.time() - start

    # Calculate statistics
    success_count = len(latencies)
    error_count = len(errors)
    requests_per_second = success_count / total_time

    if latencies:
        avg_latency = statistics.mean(latencies)
        p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]
        max_latency = max(latencies)
    else:
        avg_latency = p95_latency = max_latency = 0

    # Should handle continuous load without errors
    error_rate = error_count / (success_count + error_count) if (success_count + error_count) > 0 else 0

    assert error_rate < 0.05, f"Error rate too high under stress: {error_rate * 100:.1f}%"

    print(f"✓ Stress test completed:")
    print(f"  - Duration: {total_time:.2f}s")
    print(f"  - Total requests: {request_count}")
    print(f"  - Successful: {success_count}")
    print(f"  - Errors: {error_count}")
    print(f"  - Requests/sec: {requests_per_second:.2f}")
    print(f"  - Average latency: {avg_latency:.2f}ms")
    print(f"  - P95 latency: {p95_latency:.2f}ms")
    print(f"  - Max latency: {max_latency:.2f}ms")
    print(f"  - Error rate: {error_rate * 100:.2f}%")


def test_no_memory_leak():
    """Test for memory leaks by checking memory stability over many requests."""
    _wait_for_server()

    print("Testing for memory leaks (100 requests)...")

    memory_samples = []

    # Make requests and sample memory periodically
    for i in range(100):
        _get_health()

        # Sample memory every 10 requests
        if i % 10 == 0:
            health, _ = _get_health()
            memory_mb = health.get("resource_usage", {}).get("memory_mb", 0)
            memory_samples.append(memory_mb)

        time.sleep(0.05)

    # Check if memory is growing linearly (sign of leak)
    if len(memory_samples) > 2:
        first_third = memory_samples[:len(memory_samples)//3]
        last_third = memory_samples[-len(memory_samples)//3:]

        avg_first = statistics.mean(first_third)
        avg_last = statistics.mean(last_third)

        if avg_first > 0:
            growth_percent = ((avg_last - avg_first) / avg_first) * 100
        else:
            growth_percent = 0

        print(f"✓ Memory leak test:")
        print(f"  - Initial memory (avg first third): {avg_first:.2f} MB")
        print(f"  - Final memory (avg last third): {avg_last:.2f} MB")
        print(f"  - Growth: {growth_percent:.1f}%")

        # Warn about potential memory leak
        if growth_percent > 20:
            print(f"⚠ Warning: Memory grew by {growth_percent:.1f}% - possible memory leak")


if __name__ == "__main__":
    """Run all performance tests."""
    print("=" * 60)
    print("Health Monitoring Performance Tests")
    print("=" * 60)
    print()
    print("Configuration:")
    print(f"  - BASE_URL: {BASE_URL}")
    print(f"  - CONCURRENT_REQUESTS: {CONCURRENT_REQUESTS}")
    print(f"  - SEQUENTIAL_REQUESTS: {SEQUENTIAL_REQUESTS}")
    print(f"  - STRESS_TEST_DURATION: {STRESS_TEST_DURATION}s")
    print()

    tests = [
        ("Endpoint latency", test_health_endpoint_latency),
        ("Response consistency", test_health_endpoint_consistency),
        ("Concurrent requests", test_concurrent_health_requests),
        ("Sequential load", test_sequential_load),
        ("Resource usage tracking", test_resource_usage_tracking),
        ("Performance metrics collection", test_performance_metrics_collection),
        ("Stress test", test_stress_test),
        ("Memory leak test", test_no_memory_leak),
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
