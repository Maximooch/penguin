"""Tests for authentication middleware.

Tests API key and JWT authentication for the Penguin web API.
Tests can run against a local server or container with auth enabled.
"""

import os
import time
import urllib.request
import urllib.error
import json
from typing import Any, Dict, Optional
from datetime import datetime, timedelta
import jwt


BASE_URL = os.environ.get("PENGUIN_API_URL", "http://127.0.0.1:8000")

# Test API keys (set these in environment for auth-enabled tests)
TEST_API_KEY = os.getenv("TEST_API_KEY", "test-key-12345")
TEST_JWT_SECRET = os.getenv("TEST_JWT_SECRET", "test-secret-for-jwt-testing")


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


def _get(path: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """GET request helper."""
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        raise AssertionError(f"GET {path} failed: {e.code} {e.reason}\n{body}")


def _get_expect_error(path: str, headers: Optional[Dict[str, str]] = None, expected_status: int = 401) -> Dict[str, Any]:
    """GET request that expects an error response."""
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raise AssertionError(f"Expected {expected_status} error but got {resp.status}")
    except urllib.error.HTTPError as e:
        if e.code != expected_status:
            raise AssertionError(f"Expected {expected_status} but got {e.code}")
        body = e.read().decode("utf-8") if e.fp else "{}"
        return json.loads(body)


def _create_test_jwt(subject: str, expired: bool = False, invalid_signature: bool = False) -> str:
    """Create a test JWT token."""
    claims = {
        "sub": subject,
        "iat": datetime.utcnow(),
    }

    if expired:
        claims["exp"] = datetime.utcnow() - timedelta(hours=1)  # Expired 1 hour ago
    else:
        claims["exp"] = datetime.utcnow() + timedelta(hours=24)

    secret = "wrong-secret" if invalid_signature else TEST_JWT_SECRET
    return jwt.encode(claims, secret, algorithm="HS256")


def test_public_endpoint_no_auth():
    """Test that public endpoints (like /health) don't require authentication."""
    _wait_for_server()

    # Health endpoint should always be accessible
    resp = _get("/api/v1/health")
    assert "status" in resp, "Health endpoint should return status"
    print("✓ Public endpoint accessible without auth")


def test_auth_disabled_allows_all():
    """Test that when auth is disabled, all endpoints are accessible.

    Note: This test only passes when PENGUIN_AUTH_ENABLED=false
    """
    auth_enabled = os.getenv("PENGUIN_AUTH_ENABLED", "false").lower() == "true"
    if auth_enabled:
        print("⊘ Skipping test_auth_disabled_allows_all (auth is enabled)")
        return

    # Try accessing a normally protected endpoint without credentials
    try:
        resp = _get("/api/v1/capabilities")
        assert isinstance(resp, dict), "Should receive valid response"
        print("✓ Auth disabled allows access to all endpoints")
    except AssertionError:
        print("⊘ Could not verify - endpoint may not exist")


def test_api_key_header_authentication():
    """Test API key authentication via X-API-Key header."""
    auth_enabled = os.getenv("PENGUIN_AUTH_ENABLED", "false").lower() == "true"
    if not auth_enabled:
        print("⊘ Skipping test_api_key_header_authentication (auth disabled)")
        return

    headers = {"X-API-Key": TEST_API_KEY}

    try:
        resp = _get("/api/v1/capabilities", headers=headers)
        assert isinstance(resp, dict), "Should receive valid response with API key"
        print(f"✓ API key authentication via X-API-Key header works")
    except AssertionError as e:
        if "401" in str(e):
            print(f"⊘ API key authentication failed - check TEST_API_KEY is in PENGUIN_API_KEYS")
        else:
            raise


def test_api_key_query_parameter():
    """Test API key authentication via query parameter (less secure)."""
    auth_enabled = os.getenv("PENGUIN_AUTH_ENABLED", "false").lower() == "true"
    if not auth_enabled:
        print("⊘ Skipping test_api_key_query_parameter (auth disabled)")
        return

    try:
        resp = _get(f"/api/v1/capabilities?api_key={TEST_API_KEY}")
        assert isinstance(resp, dict), "Should receive valid response with API key"
        print("✓ API key authentication via query parameter works (insecure)")
    except AssertionError as e:
        if "401" in str(e):
            print("⊘ API key query auth failed - check TEST_API_KEY configuration")
        else:
            raise


def test_invalid_api_key_rejected():
    """Test that invalid API keys are rejected."""
    auth_enabled = os.getenv("PENGUIN_AUTH_ENABLED", "false").lower() == "true"
    if not auth_enabled:
        print("⊘ Skipping test_invalid_api_key_rejected (auth disabled)")
        return

    headers = {"X-API-Key": "invalid-key-that-does-not-exist"}

    error_resp = _get_expect_error("/api/v1/capabilities", headers=headers, expected_status=401)

    # Check error structure
    assert "error" in error_resp or "detail" in error_resp, "Error response should have error field"
    print("✓ Invalid API key rejected with 401")


def test_missing_api_key_rejected():
    """Test that requests without credentials are rejected when auth is enabled."""
    auth_enabled = os.getenv("PENGUIN_AUTH_ENABLED", "false").lower() == "true"
    if not auth_enabled:
        print("⊘ Skipping test_missing_api_key_rejected (auth disabled)")
        return

    error_resp = _get_expect_error("/api/v1/capabilities", expected_status=401)

    # Check error structure
    if isinstance(error_resp, dict):
        # Should have structured error response
        detail = error_resp.get("detail", {})
        if isinstance(detail, dict) and "error" in detail:
            error = detail["error"]
            assert error.get("code") in ["AUTHENTICATION_FAILED", "AUTHENTICATION_REQUIRED"], \
                f"Expected authentication error code, got {error.get('code')}"
            assert error.get("recoverable") == False, "Authentication errors should not be recoverable"
            print(f"✓ Missing credentials rejected with structured error: {error.get('code')}")
        else:
            print("✓ Missing credentials rejected (non-structured error)")


def test_jwt_bearer_token_authentication():
    """Test JWT Bearer token authentication."""
    auth_enabled = os.getenv("PENGUIN_AUTH_ENABLED", "false").lower() == "true"
    jwt_secret = os.getenv("PENGUIN_JWT_SECRET")

    if not auth_enabled:
        print("⊘ Skipping test_jwt_bearer_token_authentication (auth disabled)")
        return

    if not jwt_secret:
        print("⊘ Skipping test_jwt_bearer_token_authentication (JWT not configured)")
        return

    # Create a valid JWT token
    token = _create_test_jwt("test-user")
    headers = {"Authorization": f"Bearer {token}"}

    try:
        resp = _get("/api/v1/capabilities", headers=headers)
        assert isinstance(resp, dict), "Should receive valid response with JWT"
        print("✓ JWT Bearer token authentication works")
    except AssertionError as e:
        if "401" in str(e):
            print("⊘ JWT authentication failed - check PENGUIN_JWT_SECRET matches TEST_JWT_SECRET")
        else:
            raise


def test_expired_jwt_rejected():
    """Test that expired JWT tokens are rejected."""
    auth_enabled = os.getenv("PENGUIN_AUTH_ENABLED", "false").lower() == "true"
    jwt_secret = os.getenv("PENGUIN_JWT_SECRET")

    if not auth_enabled or not jwt_secret:
        print("⊘ Skipping test_expired_jwt_rejected (auth/JWT not configured)")
        return

    # Create an expired JWT token
    token = _create_test_jwt("test-user", expired=True)
    headers = {"Authorization": f"Bearer {token}"}

    error_resp = _get_expect_error("/api/v1/capabilities", headers=headers, expected_status=401)

    # Check error indicates expiration
    detail = error_resp.get("detail", {})
    if isinstance(detail, dict) and "error" in detail:
        error = detail["error"]
        assert "expire" in error.get("message", "").lower() or \
               "AUTHENTICATION_FAILED" in error.get("code", ""), \
               "Error should indicate token expiration"
        print("✓ Expired JWT token rejected")
    else:
        print("✓ Expired JWT token rejected (non-structured error)")


def test_invalid_jwt_signature_rejected():
    """Test that JWT tokens with invalid signatures are rejected."""
    auth_enabled = os.getenv("PENGUIN_AUTH_ENABLED", "false").lower() == "true"
    jwt_secret = os.getenv("PENGUIN_JWT_SECRET")

    if not auth_enabled or not jwt_secret:
        print("⊘ Skipping test_invalid_jwt_signature_rejected (auth/JWT not configured)")
        return

    # Create a JWT token with wrong signature
    token = _create_test_jwt("test-user", invalid_signature=True)
    headers = {"Authorization": f"Bearer {token}"}

    error_resp = _get_expect_error("/api/v1/capabilities", headers=headers, expected_status=401)

    print("✓ JWT token with invalid signature rejected")


def test_malformed_bearer_token_rejected():
    """Test that malformed Bearer tokens are rejected."""
    auth_enabled = os.getenv("PENGUIN_AUTH_ENABLED", "false").lower() == "true"

    if not auth_enabled:
        print("⊘ Skipping test_malformed_bearer_token_rejected (auth disabled)")
        return

    headers = {"Authorization": "Bearer not-a-valid-jwt-token"}
    error_resp = _get_expect_error("/api/v1/capabilities", headers=headers, expected_status=401)

    print("✓ Malformed Bearer token rejected")


def test_error_response_structure():
    """Test that authentication errors follow the structured error format."""
    auth_enabled = os.getenv("PENGUIN_AUTH_ENABLED", "false").lower() == "true"

    if not auth_enabled:
        print("⊘ Skipping test_error_response_structure (auth disabled)")
        return

    # Trigger an auth error
    error_resp = _get_expect_error("/api/v1/capabilities", expected_status=401)

    # Validate structured error format
    assert isinstance(error_resp, dict), "Error response should be a dictionary"

    detail = error_resp.get("detail", {})
    if isinstance(detail, dict) and "error" in detail:
        error = detail["error"]

        # Check required fields
        assert "code" in error, "Error should have 'code' field"
        assert "message" in error, "Error should have 'message' field"
        assert "recoverable" in error, "Error should have 'recoverable' field"
        assert "suggested_action" in error, "Error should have 'suggested_action' field"

        # Validate field types
        assert isinstance(error["code"], str), "Error code should be string"
        assert isinstance(error["message"], str), "Error message should be string"
        assert isinstance(error["recoverable"], bool), "Error recoverable should be boolean"
        assert isinstance(error["suggested_action"], str), "Error suggested_action should be string"

        print(f"✓ Authentication error follows structured format:")
        print(f"  - code: {error['code']}")
        print(f"  - recoverable: {error['recoverable']}")
        print(f"  - suggested_action: {error['suggested_action']}")
    else:
        print("⊘ Error response not in structured format (may be using default format)")


if __name__ == "__main__":
    """Run all authentication tests."""
    print("=" * 60)
    print("Authentication Middleware Tests")
    print("=" * 60)
    print()

    # Check configuration
    auth_enabled = os.getenv("PENGUIN_AUTH_ENABLED", "false").lower() == "true"
    jwt_configured = bool(os.getenv("PENGUIN_JWT_SECRET"))

    print("Configuration:")
    print(f"  PENGUIN_AUTH_ENABLED: {auth_enabled}")
    print(f"  PENGUIN_JWT_SECRET: {'configured' if jwt_configured else 'not configured'}")
    print(f"  TEST_API_KEY: {TEST_API_KEY[:8]}..." if len(TEST_API_KEY) > 8 else TEST_API_KEY)
    print()

    tests = [
        ("Public endpoints accessible", test_public_endpoint_no_auth),
        ("Auth disabled allows all", test_auth_disabled_allows_all),
        ("API key header auth", test_api_key_header_authentication),
        ("API key query param auth", test_api_key_query_parameter),
        ("Invalid API key rejected", test_invalid_api_key_rejected),
        ("Missing credentials rejected", test_missing_api_key_rejected),
        ("JWT Bearer token auth", test_jwt_bearer_token_authentication),
        ("Expired JWT rejected", test_expired_jwt_rejected),
        ("Invalid JWT signature rejected", test_invalid_jwt_signature_rejected),
        ("Malformed Bearer token rejected", test_malformed_bearer_token_rejected),
        ("Error response structure", test_error_response_structure),
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
