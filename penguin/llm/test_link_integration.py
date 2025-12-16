"""
Integration tests for Link LLM proxy integration.

Tests the LLMClient, configurable base_url, and X-Link-* header injection.

Run with pytest:
    pytest penguin/llm/test_link_integration.py -v
    
Or standalone (no pytest required):
    python penguin/llm/test_link_integration.py
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import modules under test
try:
    from penguin.llm.client import LLMClient, LLMClientConfig, LinkConfig
    from penguin.llm.model_config import ModelConfig
    from penguin.llm.openrouter_gateway import OpenRouterGateway
except ImportError as e:
    logger.error(f"ImportError: {e}. Make sure this script is run from the project root.")
    sys.exit(1)


# --- Helper Functions for Creating Test Objects ---

def create_mock_model_config() -> ModelConfig:
    """Create a mock ModelConfig for testing."""
    return ModelConfig(
        model="anthropic/claude-haiku-4.5",
        provider="openrouter",
        client_preference="openrouter",
        api_key="test-api-key-12345",
        streaming_enabled=True,
    )


def create_link_config() -> LinkConfig:
    """Create a LinkConfig for testing."""
    return LinkConfig(
        user_id="user-test-123",
        session_id="sess-test-456",
        agent_id="agent-test-789",
        workspace_id="ws-test-abc",
        api_key="link-api-key-xyz",
    )


def create_llm_client_config(link_config: Optional[LinkConfig] = None) -> LLMClientConfig:
    """Create an LLMClientConfig for testing."""
    if link_config is None:
        link_config = create_link_config()
    return LLMClientConfig(
        base_url="http://localhost:3001/api/v1",
        link=link_config,
    )


# --- Unit Tests: LinkConfig ---

class TestLinkConfig:
    """Tests for LinkConfig dataclass."""
    
    def test_to_headers(self):
        """Test LinkConfig.to_headers() generates correct headers."""
        link_config = create_link_config()
        headers = link_config.to_headers()
        
        assert headers["X-Link-User-Id"] == "user-test-123"
        assert headers["X-Link-Session-Id"] == "sess-test-456"
        assert headers["X-Link-Agent-Id"] == "agent-test-789"
        assert headers["X-Link-Workspace-Id"] == "ws-test-abc"
        assert headers["Authorization"] == "Bearer link-api-key-xyz"
    
    def test_to_headers_partial(self):
        """Test to_headers() with partial configuration."""
        config = LinkConfig(user_id="user-only")
        headers = config.to_headers()
        
        assert headers == {"X-Link-User-Id": "user-only"}
        assert "X-Link-Session-Id" not in headers
        assert "Authorization" not in headers
    
    def test_is_configured(self):
        """Test is_configured property."""
        assert LinkConfig(user_id="test").is_configured is True
        assert LinkConfig().is_configured is False
        assert LinkConfig(session_id="sess").is_configured is False  # user_id required


# --- Unit Tests: LLMClientConfig ---

class TestLLMClientConfig:
    """Tests for LLMClientConfig dataclass."""
    
    def test_effective_base_url_with_value(self):
        """Test effective_base_url returns set value."""
        config = LLMClientConfig(base_url="http://custom:3001/v1")
        assert config.effective_base_url == "http://custom:3001/v1"
    
    def test_effective_base_url_default(self):
        """Test effective_base_url falls back to OpenRouter."""
        config = LLMClientConfig()
        assert config.effective_base_url == "https://openrouter.ai/api/v1"
    
    def test_is_link_proxy_detection(self):
        """Test is_link_proxy correctly identifies Link proxy URLs."""
        # Link proxy URLs
        assert LLMClientConfig(base_url="http://localhost:3001/api/v1").is_link_proxy is True
        assert LLMClientConfig(base_url="https://linkplatform.ai/api/v1").is_link_proxy is True
        assert LLMClientConfig(base_url="http://127.0.0.1:3001/v1").is_link_proxy is True
        
        # Non-Link URLs
        assert LLMClientConfig(base_url="https://openrouter.ai/api/v1").is_link_proxy is False
        assert LLMClientConfig(base_url="https://api.openai.com/v1").is_link_proxy is False
        assert LLMClientConfig(base_url=None).is_link_proxy is False


# --- Unit Tests: LLMClient ---

class TestLLMClient:
    """Tests for LLMClient class."""
    
    def test_init_with_config(self):
        """Test LLMClient initialization with explicit config."""
        model_config = create_mock_model_config()
        llm_config = create_llm_client_config()
        
        client = LLMClient(model_config, llm_config)
        
        assert client.config.base_url == "http://localhost:3001/api/v1"
        assert client.config.link.user_id == "user-test-123"
    
    def test_update_config(self):
        """Test runtime configuration update."""
        model_config = create_mock_model_config()
        llm_config = create_llm_client_config()
        client = LLMClient(model_config, llm_config)
        
        # Initial state
        assert client.config.link.user_id == "user-test-123"
        assert client.config.base_url == "http://localhost:3001/api/v1"
        
        # Update configuration
        new_config = client.update_config(
            base_url="https://production.link/api/v1",
            link_user_id="new-user-456",
        )
        
        # Verify update
        assert new_config.base_url == "https://production.link/api/v1"
        assert new_config.link.user_id == "new-user-456"
        # Unchanged values preserved
        assert new_config.link.session_id == "sess-test-456"
        assert new_config._source == "runtime_api"
    
    def test_get_link_headers(self):
        """Test Link header generation."""
        model_config = create_mock_model_config()
        llm_config = create_llm_client_config()
        client = LLMClient(model_config, llm_config)
        
        headers = client.get_link_headers()
        
        assert "X-Link-User-Id" in headers
        assert headers["X-Link-User-Id"] == "user-test-123"
        assert "Authorization" in headers
    
    def test_get_link_headers_not_configured(self):
        """Test get_link_headers returns empty dict when not configured."""
        model_config = create_mock_model_config()
        config = LLMClientConfig()  # No Link config
        client = LLMClient(model_config, config)
        
        headers = client.get_link_headers()
        
        assert headers == {}
    
    def test_get_status(self):
        """Test get_status returns correct information."""
        model_config = create_mock_model_config()
        llm_config = create_llm_client_config()
        client = LLMClient(model_config, llm_config)
        
        status = client.get_status()
        
        assert status["base_url"] == "http://localhost:3001/api/v1"
        assert status["is_link_proxy"] is True
        assert status["link_configured"] is True
        assert status["link_user_id"] == "user-test-123"
        assert status["model"] == "anthropic/claude-haiku-4.5"


# --- Integration Tests: OpenRouterGateway with Link ---

class TestOpenRouterGatewayLinkIntegration:
    """Integration tests for OpenRouterGateway with Link configuration."""
    
    def test_gateway_accepts_base_url(self):
        """Test OpenRouterGateway accepts custom base_url."""
        model_config = create_mock_model_config()
        gateway = OpenRouterGateway(
            model_config,
            base_url="http://localhost:3001/api/v1",
        )
        
        assert gateway.base_url == "http://localhost:3001/api/v1"
        # OpenAI SDK may normalize URL with trailing slash
        assert str(gateway.client.base_url).rstrip('/') == "http://localhost:3001/api/v1"
    
    def test_gateway_accepts_extra_headers(self):
        """Test OpenRouterGateway accepts and merges extra_headers."""
        model_config = create_mock_model_config()
        link_headers = {
            "X-Link-User-Id": "test-user",
            "X-Link-Session-Id": "test-session",
        }
        
        gateway = OpenRouterGateway(
            model_config,
            extra_headers=link_headers,
        )
        
        assert "X-Link-User-Id" in gateway.extra_headers
        assert gateway.extra_headers["X-Link-User-Id"] == "test-user"
        # Site headers should also be present
        assert "X-Title" in gateway.extra_headers
    
    def test_gateway_default_base_url(self):
        """Test OpenRouterGateway uses OpenRouter by default."""
        model_config = create_mock_model_config()
        
        # Clear env var if set
        old_val = os.environ.pop("OPENAI_BASE_URL", None)
        try:
            gateway = OpenRouterGateway(model_config)
            assert gateway.base_url == "https://openrouter.ai/api/v1"
        finally:
            if old_val:
                os.environ["OPENAI_BASE_URL"] = old_val


# --- Live Integration Test ---

class TestLiveIntegration:
    """Live integration tests that make real API calls to OpenRouter.
    
    Uses anthropic/claude-haiku-4.5 (cheap model) for cost efficiency.
    """
    
    def _get_live_model_config(self) -> ModelConfig:
        """Create ModelConfig for live testing."""
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        
        return ModelConfig(
            model="anthropic/claude-haiku-4.5",
            provider="openrouter",
            client_preference="openrouter",
            api_key=api_key,
            streaming_enabled=True,
        )
    
    def test_live_request_with_link_headers(self):
        """Test a live request with Link headers configured.
        
        This verifies:
        1. The gateway works with Link headers configured
        2. OpenRouter accepts requests with extra headers (they're ignored)
        3. The response is properly formatted
        """
        model_config = self._get_live_model_config()
        
        link_config = LinkConfig(
            user_id="test-live-user",
            session_id="test-live-session",
        )
        
        config = LLMClientConfig(
            base_url=None,  # Use default OpenRouter
            link=link_config,
        )
        
        client = LLMClient(model_config, config)
        
        messages = [
            {"role": "user", "content": "Say exactly: 'Link integration test successful'"}
        ]
        
        # Run async test
        async def do_request():
            return await client.chat_completion(
                messages=messages,
                max_output_tokens=50,
                temperature=0,
                stream=False,
            )
        
        response = asyncio.run(do_request())
        
        assert "content" in response, f"Response missing 'content': {response}"
        assert len(response["content"]) > 0, "Empty response content"
        logger.info(f"Live test response: {response['content'][:100]}")


# --- Standalone Test Runner ---

def run_tests():
    """Run tests when executed as a script."""
    print("=" * 60)
    print("Link Integration Tests")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    # Test LinkConfig
    print("\n--- Testing LinkConfig ---\n")
    
    try:
        t = TestLinkConfig()
        t.test_to_headers()
        print("  ✓ test_to_headers")
        passed += 1
    except AssertionError as e:
        print(f"  ✗ test_to_headers: {e}")
        failed += 1
    
    try:
        t = TestLinkConfig()
        t.test_to_headers_partial()
        print("  ✓ test_to_headers_partial")
        passed += 1
    except AssertionError as e:
        print(f"  ✗ test_to_headers_partial: {e}")
        failed += 1
    
    try:
        t = TestLinkConfig()
        t.test_is_configured()
        print("  ✓ test_is_configured")
        passed += 1
    except AssertionError as e:
        print(f"  ✗ test_is_configured: {e}")
        failed += 1
    
    # Test LLMClientConfig
    print("\n--- Testing LLMClientConfig ---\n")
    
    try:
        t = TestLLMClientConfig()
        t.test_effective_base_url_with_value()
        print("  ✓ test_effective_base_url_with_value")
        passed += 1
    except AssertionError as e:
        print(f"  ✗ test_effective_base_url_with_value: {e}")
        failed += 1
    
    try:
        t = TestLLMClientConfig()
        t.test_effective_base_url_default()
        print("  ✓ test_effective_base_url_default")
        passed += 1
    except AssertionError as e:
        print(f"  ✗ test_effective_base_url_default: {e}")
        failed += 1
    
    try:
        t = TestLLMClientConfig()
        t.test_is_link_proxy_detection()
        print("  ✓ test_is_link_proxy_detection")
        passed += 1
    except AssertionError as e:
        print(f"  ✗ test_is_link_proxy_detection: {e}")
        failed += 1
    
    # Test LLMClient
    print("\n--- Testing LLMClient ---\n")
    
    try:
        t = TestLLMClient()
        t.test_init_with_config()
        print("  ✓ test_init_with_config")
        passed += 1
    except AssertionError as e:
        print(f"  ✗ test_init_with_config: {e}")
        failed += 1
    
    try:
        t = TestLLMClient()
        t.test_update_config()
        print("  ✓ test_update_config")
        passed += 1
    except AssertionError as e:
        print(f"  ✗ test_update_config: {e}")
        failed += 1
    
    try:
        t = TestLLMClient()
        t.test_get_link_headers()
        print("  ✓ test_get_link_headers")
        passed += 1
    except AssertionError as e:
        print(f"  ✗ test_get_link_headers: {e}")
        failed += 1
    
    try:
        t = TestLLMClient()
        t.test_get_link_headers_not_configured()
        print("  ✓ test_get_link_headers_not_configured")
        passed += 1
    except AssertionError as e:
        print(f"  ✗ test_get_link_headers_not_configured: {e}")
        failed += 1
    
    try:
        t = TestLLMClient()
        t.test_get_status()
        print("  ✓ test_get_status")
        passed += 1
    except AssertionError as e:
        print(f"  ✗ test_get_status: {e}")
        failed += 1
    
    # Test OpenRouterGateway
    print("\n--- Testing OpenRouterGateway with Link ---\n")
    
    try:
        t = TestOpenRouterGatewayLinkIntegration()
        t.test_gateway_accepts_base_url()
        print("  ✓ test_gateway_accepts_base_url")
        passed += 1
    except AssertionError as e:
        print(f"  ✗ test_gateway_accepts_base_url: {e}")
        failed += 1
    
    try:
        t = TestOpenRouterGatewayLinkIntegration()
        t.test_gateway_accepts_extra_headers()
        print("  ✓ test_gateway_accepts_extra_headers")
        passed += 1
    except AssertionError as e:
        print(f"  ✗ test_gateway_accepts_extra_headers: {e}")
        failed += 1
    
    try:
        t = TestOpenRouterGatewayLinkIntegration()
        t.test_gateway_default_base_url()
        print("  ✓ test_gateway_default_base_url")
        passed += 1
    except AssertionError as e:
        print(f"  ✗ test_gateway_default_base_url: {e}")
        failed += 1
    
    # Live integration test (if API key available)
    if os.getenv("OPENROUTER_API_KEY"):
        print("\n--- Testing Live API Call ---\n")
        
        try:
            t = TestLiveIntegration()
            t.test_live_request_with_link_headers()
            print("  ✓ test_live_request_with_link_headers")
            passed += 1
        except Exception as e:
            print(f"  ✗ test_live_request_with_link_headers: {e}")
            failed += 1
    else:
        print("\n--- Skipping Live API Test (no OPENROUTER_API_KEY) ---\n")
    
    # Summary
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
