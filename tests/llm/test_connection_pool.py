"""Tests for ConnectionPoolManager HTTP connection pooling.

Tests the connection pooling system including:
- Singleton pattern
- Client creation and caching
- Configuration options
- Cleanup and shutdown
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from penguin.llm.api_client import (
    ConnectionPoolManager,
    ConnectionPoolConfig,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the singleton instance before/after each test."""
    ConnectionPoolManager._instance = None
    yield
    # Cleanup after test
    if ConnectionPoolManager._instance is not None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(ConnectionPoolManager._instance.close_all())
            else:
                loop.run_until_complete(ConnectionPoolManager._instance.close_all())
        except Exception:
            pass
    ConnectionPoolManager._instance = None


@pytest.fixture
def pool_config():
    """Create a test configuration."""
    return ConnectionPoolConfig(
        max_keepalive_connections=5,
        max_connections=10,
        keepalive_expiry=15.0,
        connect_timeout=5.0,
        read_timeout=30.0,
        write_timeout=5.0,
    )


# =============================================================================
# SINGLETON PATTERN TESTS
# =============================================================================

class TestSingletonPattern:
    """Test the singleton pattern for ConnectionPoolManager."""

    def test_get_instance_creates_singleton(self):
        """Test that get_instance creates a singleton."""
        manager1 = ConnectionPoolManager.get_instance()
        manager2 = ConnectionPoolManager.get_instance()

        assert manager1 is manager2
        assert manager1 is not None

    def test_get_instance_with_config(self, pool_config):
        """Test get_instance with custom config."""
        manager = ConnectionPoolManager.get_instance(pool_config)

        assert manager._config.max_connections == 10
        assert manager._config.max_keepalive_connections == 5

    def test_singleton_ignores_subsequent_configs(self, pool_config):
        """Test that subsequent configs are ignored after first creation."""
        manager1 = ConnectionPoolManager.get_instance(pool_config)

        # Try to create with different config
        different_config = ConnectionPoolConfig(max_connections=999)
        manager2 = ConnectionPoolManager.get_instance(different_config)

        # Should still have original config
        assert manager2._config.max_connections == 10
        assert manager1 is manager2


# =============================================================================
# CONFIGURATION TESTS
# =============================================================================

class TestConfiguration:
    """Test ConnectionPoolConfig behavior."""

    def test_default_config_values(self):
        """Test default configuration values."""
        config = ConnectionPoolConfig()

        assert config.max_keepalive_connections == 20
        assert config.max_connections == 100
        assert config.keepalive_expiry == 30.0
        assert config.connect_timeout == 10.0
        assert config.read_timeout == 300.0  # Actual default from implementation
        assert config.write_timeout == 10.0

    def test_custom_config_values(self):
        """Test custom configuration values."""
        config = ConnectionPoolConfig(
            max_keepalive_connections=50,
            max_connections=200,
            keepalive_expiry=60.0,
            connect_timeout=15.0,
            read_timeout=180.0,
            write_timeout=20.0,
        )

        assert config.max_keepalive_connections == 50
        assert config.max_connections == 200
        assert config.keepalive_expiry == 60.0
        assert config.connect_timeout == 15.0
        assert config.read_timeout == 180.0
        assert config.write_timeout == 20.0

    def test_to_limits_creates_httpx_limits(self):
        """Test that to_limits creates valid httpx.Limits."""
        config = ConnectionPoolConfig(
            max_keepalive_connections=25,
            max_connections=50,
        )

        limits = config.to_limits()

        assert isinstance(limits, httpx.Limits)
        assert limits.max_keepalive_connections == 25
        assert limits.max_connections == 50


# =============================================================================
# CLIENT CREATION TESTS (with mocked httpx)
# =============================================================================

class TestClientCreation:
    """Test HTTP client creation and caching."""

    @pytest.mark.asyncio
    async def test_clients_dict_starts_empty(self):
        """Test that manager starts with empty clients dict."""
        manager = ConnectionPoolManager.get_instance()
        assert len(manager._clients) == 0

    @pytest.mark.asyncio
    async def test_get_client_adds_to_dict(self):
        """Test that get_client adds client to internal dict."""
        manager = ConnectionPoolManager.get_instance()

        # Mock httpx.AsyncClient to avoid actual HTTP setup
        with patch('penguin.llm.api_client.httpx.AsyncClient') as mock_client:
            mock_instance = MagicMock()
            mock_client.return_value = mock_instance

            client = await manager.get_client("https://api.example.com")

            assert "https://api.example.com" in manager._clients
            assert client is mock_instance

    @pytest.mark.asyncio
    async def test_get_client_returns_cached(self):
        """Test that get_client returns cached client for same URL."""
        manager = ConnectionPoolManager.get_instance()

        with patch('penguin.llm.api_client.httpx.AsyncClient') as mock_client:
            mock_instance = MagicMock()
            mock_client.return_value = mock_instance

            client1 = await manager.get_client("https://api.example.com")
            client2 = await manager.get_client("https://api.example.com")

            assert client1 is client2
            # Should only create one client
            assert mock_client.call_count == 1

    @pytest.mark.asyncio
    async def test_different_urls_get_different_clients(self):
        """Test that different URLs get different clients."""
        manager = ConnectionPoolManager.get_instance()

        with patch('penguin.llm.api_client.httpx.AsyncClient') as mock_client:
            mock_instance1 = MagicMock()
            mock_instance2 = MagicMock()
            mock_client.side_effect = [mock_instance1, mock_instance2]

            client1 = await manager.get_client("https://api1.example.com")
            client2 = await manager.get_client("https://api2.example.com")

            assert client1 is not client2
            assert mock_client.call_count == 2


# =============================================================================
# CONTEXT MANAGER TESTS
# =============================================================================

class TestContextManager:
    """Test the async context manager interface."""

    @pytest.mark.asyncio
    async def test_client_context_basic(self):
        """Test basic client_context usage."""
        manager = ConnectionPoolManager.get_instance()

        with patch('penguin.llm.api_client.httpx.AsyncClient') as mock_client:
            mock_instance = MagicMock()
            mock_client.return_value = mock_instance

            async with manager.client_context("https://api.example.com") as client:
                assert client is not None
                assert client is mock_instance

    @pytest.mark.asyncio
    async def test_client_context_reuses_client(self):
        """Test that client_context reuses cached client."""
        manager = ConnectionPoolManager.get_instance()

        with patch('penguin.llm.api_client.httpx.AsyncClient') as mock_client:
            mock_instance = MagicMock()
            mock_client.return_value = mock_instance

            async with manager.client_context("https://api.example.com") as client1:
                pass

            async with manager.client_context("https://api.example.com") as client2:
                pass

            assert client1 is client2
            # Only one client should be created
            assert mock_client.call_count == 1


# =============================================================================
# CLEANUP TESTS
# =============================================================================

class TestCleanup:
    """Test cleanup and shutdown operations."""

    @pytest.mark.asyncio
    async def test_close_all_clears_clients(self):
        """Test close_all clears all clients."""
        manager = ConnectionPoolManager.get_instance()

        with patch('penguin.llm.api_client.httpx.AsyncClient') as mock_client:
            mock_instance = MagicMock()
            mock_instance.aclose = AsyncMock()
            mock_client.return_value = mock_instance

            # Create some clients
            await manager.get_client("https://api1.example.com")
            await manager.get_client("https://api2.example.com")

            assert len(manager._clients) == 2

            # Close all
            await manager.close_all()

            assert len(manager._clients) == 0

    @pytest.mark.asyncio
    async def test_close_all_on_empty(self):
        """Test close_all works when no clients exist."""
        manager = ConnectionPoolManager.get_instance()

        # Should not raise
        await manager.close_all()

        assert len(manager._clients) == 0

    @pytest.mark.asyncio
    async def test_recreate_client_after_close(self):
        """Test that clients can be recreated after close."""
        manager = ConnectionPoolManager.get_instance()

        with patch('penguin.llm.api_client.httpx.AsyncClient') as mock_client:
            mock_instance1 = MagicMock()
            mock_instance1.aclose = AsyncMock()
            mock_instance2 = MagicMock()
            mock_client.side_effect = [mock_instance1, mock_instance2]

            client1 = await manager.get_client("https://api.example.com")
            await manager.close_all()

            client2 = await manager.get_client("https://api.example.com")

            assert client2 is not None
            assert client2 is not client1  # New instance


# =============================================================================
# CONCURRENT ACCESS TESTS
# =============================================================================

class TestConcurrentAccess:
    """Test thread-safe concurrent access."""

    @pytest.mark.asyncio
    async def test_concurrent_get_client(self):
        """Test concurrent get_client calls for same URL."""
        manager = ConnectionPoolManager.get_instance()

        with patch('penguin.llm.api_client.httpx.AsyncClient') as mock_client:
            mock_instance = MagicMock()
            mock_client.return_value = mock_instance

            # Concurrent requests for same URL
            tasks = [
                manager.get_client("https://api.example.com")
                for _ in range(10)
            ]

            clients = await asyncio.gather(*tasks)

            # All should be the same client
            assert all(c is clients[0] for c in clients)
            # Only one client should have been created
            assert mock_client.call_count == 1

    @pytest.mark.asyncio
    async def test_concurrent_different_urls(self):
        """Test concurrent get_client calls for different URLs."""
        manager = ConnectionPoolManager.get_instance()

        with patch('penguin.llm.api_client.httpx.AsyncClient') as mock_client:
            # Create unique mock for each call
            mock_client.side_effect = [MagicMock() for _ in range(5)]

            urls = [f"https://api{i}.example.com" for i in range(5)]
            tasks = [manager.get_client(url) for url in urls]

            clients = await asyncio.gather(*tasks)

            # All should be different
            assert len(set(id(c) for c in clients)) == 5


# =============================================================================
# ASYNC INSTANCE TESTS
# =============================================================================

class TestAsyncInstance:
    """Test async singleton accessor."""

    @pytest.mark.asyncio
    async def test_get_instance_async(self):
        """Test get_instance_async creates singleton."""
        manager1 = await ConnectionPoolManager.get_instance_async()
        manager2 = await ConnectionPoolManager.get_instance_async()

        assert manager1 is manager2
        assert manager1 is not None

    @pytest.mark.asyncio
    async def test_sync_and_async_same_instance(self):
        """Test that sync and async accessors return same instance."""
        manager_sync = ConnectionPoolManager.get_instance()
        manager_async = await ConnectionPoolManager.get_instance_async()

        assert manager_sync is manager_async


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
