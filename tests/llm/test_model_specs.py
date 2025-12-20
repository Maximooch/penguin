"""Tests for ModelSpecsService.

Tests cover:
- Cache behavior (memory and disk)
- API response parsing
- TTL expiration
- Error handling
- Singleton access
"""

import asyncio
import json
import pytest
import time

# Configure pytest-asyncio mode
pytestmark = pytest.mark.asyncio(loop_scope="function")
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

from penguin.llm.model_config import (
    ModelSpecs,
    ModelSpecsService,
    _CacheEntry as CacheEntry,  # Renamed to private in consolidated module
    fetch_model_specs,
    get_model_specs_service,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_cache_dir():
    """Provide a temporary directory for disk cache tests."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def service(temp_cache_dir):
    """Create a ModelSpecsService with temp cache dir."""
    return ModelSpecsService(
        cache_dir=temp_cache_dir,
        ttl_seconds=3600,
        enable_disk_cache=True,
    )


@pytest.fixture
def mock_api_response():
    """Mock OpenRouter API response."""
    return {
        "data": [
            {
                "id": "openai/gpt-4o",
                "name": "GPT-4o",
                "context_length": 128000,
                "top_provider": {"max_completion_tokens": 16384},
                "pricing": {"prompt": "0.000005", "completion": "0.000015"},
                "architecture": {"modality": "text+image->text"},
            },
            {
                "id": "anthropic/claude-opus-4",
                "name": "Claude Opus 4",
                "context_length": 200000,
                "top_provider": {"max_completion_tokens": 64000},
                "pricing": {"prompt": "0.000015", "completion": "0.000075"},
                "architecture": {"modality": "text"},
            },
            {
                "id": "google/gemini-2.5-pro-preview",
                "name": "Gemini 2.5 Pro",
                "context_length": 1048576,
                "top_provider": {"max_completion_tokens": 65536},
                "architecture": {"modality": "multimodal"},
            },
            {
                "id": "deepseek/deepseek-r1",
                "name": "DeepSeek R1",
                "context_length": 163840,
                "top_provider": {"max_completion_tokens": 32768},
                "architecture": {"modality": "text"},
            },
        ]
    }


# =============================================================================
# ModelSpecs DATACLASS TESTS
# =============================================================================

class TestModelSpecs:
    """Tests for ModelSpecs dataclass."""

    def test_to_dict(self):
        """ModelSpecs should serialize to dict."""
        specs = ModelSpecs(
            model_id="openai/gpt-4o",
            name="GPT-4o",
            context_length=128000,
            max_output_tokens=16384,
            provider="openai",
            supports_vision=True,
        )
        result = specs.to_dict()

        assert result["model_id"] == "openai/gpt-4o"
        assert result["name"] == "GPT-4o"
        assert result["context_length"] == 128000
        assert result["max_output_tokens"] == 16384
        assert result["provider"] == "openai"
        assert result["supports_vision"] is True

    def test_from_dict(self):
        """ModelSpecs should deserialize from dict."""
        data = {
            "model_id": "anthropic/claude-opus-4",
            "name": "Claude Opus 4",
            "context_length": 200000,
            "max_output_tokens": 64000,
            "provider": "anthropic",
            "supports_reasoning": True,
        }
        specs = ModelSpecs.from_dict(data)

        assert specs.model_id == "anthropic/claude-opus-4"
        assert specs.name == "Claude Opus 4"
        assert specs.context_length == 200000
        assert specs.max_output_tokens == 64000
        assert specs.provider == "anthropic"
        assert specs.supports_reasoning is True

    def test_roundtrip(self):
        """to_dict and from_dict should be inverses."""
        original = ModelSpecs(
            model_id="test/model",
            name="Test Model",
            context_length=10000,
            max_output_tokens=2000,
            provider="test",
            pricing_prompt=5.0,
            pricing_completion=15.0,
            supports_vision=True,
            supports_reasoning=True,
        )
        restored = ModelSpecs.from_dict(original.to_dict())

        assert restored.model_id == original.model_id
        assert restored.name == original.name
        assert restored.context_length == original.context_length
        assert restored.max_output_tokens == original.max_output_tokens
        assert restored.provider == original.provider
        assert restored.pricing_prompt == original.pricing_prompt
        assert restored.pricing_completion == original.pricing_completion
        assert restored.supports_vision == original.supports_vision
        assert restored.supports_reasoning == original.supports_reasoning


# =============================================================================
# CacheEntry TESTS
# =============================================================================

class TestCacheEntry:
    """Tests for CacheEntry TTL behavior."""

    def test_not_expired_within_ttl(self):
        """Entry should not be expired within TTL."""
        specs = ModelSpecs(
            model_id="test/model",
            name="Test",
            context_length=10000,
            max_output_tokens=2000,
            provider="test",
        )
        entry = CacheEntry(specs=specs, fetched_at=time.time())

        assert entry.is_expired(ttl_seconds=3600) is False

    def test_expired_after_ttl(self):
        """Entry should be expired after TTL."""
        specs = ModelSpecs(
            model_id="test/model",
            name="Test",
            context_length=10000,
            max_output_tokens=2000,
            provider="test",
        )
        # Simulate entry from 2 hours ago
        entry = CacheEntry(specs=specs, fetched_at=time.time() - 7200)

        assert entry.is_expired(ttl_seconds=3600) is True


# =============================================================================
# ModelSpecsService TESTS
# =============================================================================

class TestServiceCaching:
    """Tests for in-memory caching behavior."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached(self, service, mock_api_response):
        """Cached specs should be returned without API call."""
        # Pre-populate cache
        specs = ModelSpecs(
            model_id="openai/gpt-4o",
            name="GPT-4o (cached)",
            context_length=128000,
            max_output_tokens=16384,
            provider="openai",
        )
        service._cache["openai/gpt-4o"] = CacheEntry(
            specs=specs, fetched_at=time.time()
        )

        # Should return cached version
        result = await service.get_specs("openai/gpt-4o")

        assert result is not None
        assert result.name == "GPT-4o (cached)"

    @pytest.mark.asyncio
    async def test_cache_miss_fetches_api(self, service, mock_api_response):
        """Cache miss should trigger API fetch."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_api_response
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await service.get_specs("openai/gpt-4o")

            assert result is not None
            assert result.model_id == "openai/gpt-4o"
            assert result.context_length == 128000
            mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_force_refresh_bypasses_cache(self, service, mock_api_response):
        """force_refresh should bypass cache and fetch API."""
        # Pre-populate cache with old data
        old_specs = ModelSpecs(
            model_id="openai/gpt-4o",
            name="Old Name",
            context_length=100000,
            max_output_tokens=10000,
            provider="openai",
        )
        service._cache["openai/gpt-4o"] = CacheEntry(
            specs=old_specs, fetched_at=time.time()
        )

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_api_response
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await service.get_specs("openai/gpt-4o", force_refresh=True)

            assert result is not None
            assert result.name == "GPT-4o"  # From API, not cache
            assert result.context_length == 128000
            mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_expired_cache_triggers_refresh(self, service, mock_api_response):
        """Expired cache entry should trigger API fetch."""
        # Pre-populate cache with expired data
        old_specs = ModelSpecs(
            model_id="openai/gpt-4o",
            name="Expired",
            context_length=100000,
            max_output_tokens=10000,
            provider="openai",
        )
        service._cache["openai/gpt-4o"] = CacheEntry(
            specs=old_specs, fetched_at=time.time() - 7200  # 2 hours ago
        )

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_api_response
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await service.get_specs("openai/gpt-4o")

            assert result is not None
            assert result.name == "GPT-4o"  # Fresh from API
            mock_client.get.assert_called_once()


class TestServiceDiskCache:
    """Tests for disk cache persistence."""

    @pytest.mark.asyncio
    async def test_save_and_load_disk_cache(self, temp_cache_dir, mock_api_response):
        """Cache should persist to disk and reload."""
        # Create service and populate cache
        service1 = ModelSpecsService(
            cache_dir=temp_cache_dir,
            enable_disk_cache=True,
        )

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_api_response
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            await service1.get_specs("openai/gpt-4o")

        # Create new service instance (should load from disk)
        service2 = ModelSpecsService(
            cache_dir=temp_cache_dir,
            enable_disk_cache=True,
        )

        # Should have cached entry without API call
        cached = service2.get_cached_specs("openai/gpt-4o")
        assert cached is not None
        assert cached.model_id == "openai/gpt-4o"

    def test_disk_cache_disabled(self, temp_cache_dir):
        """Disk cache should not be used when disabled."""
        service = ModelSpecsService(
            cache_dir=temp_cache_dir,
            enable_disk_cache=False,
        )

        # Add to memory cache
        specs = ModelSpecs(
            model_id="test/model",
            name="Test",
            context_length=10000,
            max_output_tokens=2000,
            provider="test",
        )
        service._cache["test/model"] = CacheEntry(
            specs=specs, fetched_at=time.time()
        )

        # Cache file should not exist
        cache_file = temp_cache_dir / service.CACHE_FILE_NAME
        assert not cache_file.exists()


class TestServiceAPIparsing:
    """Tests for OpenRouter API response parsing."""

    @pytest.mark.asyncio
    async def test_parse_vision_support(self, service, mock_api_response):
        """Vision support should be detected from modality."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_api_response
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # GPT-4o has text+image modality
            gpt4o = await service.get_specs("openai/gpt-4o")
            assert gpt4o.supports_vision is True

            # Claude doesn't have image in modality
            claude = await service.get_specs("anthropic/claude-opus-4")
            assert claude.supports_vision is False

    @pytest.mark.asyncio
    async def test_parse_reasoning_support(self, service, mock_api_response):
        """Reasoning support should be detected from model ID."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_api_response
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # DeepSeek R1 has reasoning in name
            deepseek = await service.get_specs("deepseek/deepseek-r1")
            assert deepseek.supports_reasoning is True

            # Regular GPT-4o doesn't
            gpt4o = await service.get_specs("openai/gpt-4o")
            assert gpt4o.supports_reasoning is False

    @pytest.mark.asyncio
    async def test_parse_pricing(self, service, mock_api_response):
        """Pricing should be parsed and converted to per-1M tokens."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_api_response
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            specs = await service.get_specs("openai/gpt-4o")

            # $0.000005 per token * 1M = $5.00 per 1M tokens
            assert specs.pricing_prompt == 5.0
            # $0.000015 per token * 1M = $15.00 per 1M tokens
            assert specs.pricing_completion == 15.0


class TestServicePreload:
    """Tests for preload_all functionality."""

    @pytest.mark.asyncio
    async def test_preload_all_populates_cache(self, service, mock_api_response):
        """preload_all should populate cache with all models."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_api_response
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            count = await service.preload_all()

            assert count == 4  # 4 models in mock response
            assert len(service.list_cached_models()) == 4
            assert "openai/gpt-4o" in service.list_cached_models()
            assert "anthropic/claude-opus-4" in service.list_cached_models()

    @pytest.mark.asyncio
    async def test_preload_only_once(self, service, mock_api_response):
        """preload_all should only fetch once."""
        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            response = MagicMock()
            response.json.return_value = mock_api_response
            response.raise_for_status = MagicMock()
            return response

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = mock_get
            mock_client_class.return_value.__aenter__.return_value = mock_client

            await service.preload_all()
            await service.preload_all()
            await service.preload_all()

            assert call_count == 1


class TestServiceErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_api_failure_returns_none(self, service):
        """API failure should return None for unknown model."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get.side_effect = Exception("Network error")
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await service.get_specs("unknown/model")

            assert result is None

    @pytest.mark.asyncio
    async def test_model_not_found_returns_none(self, service, mock_api_response):
        """Model not in API response should return None."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_api_response
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            result = await service.get_specs("nonexistent/model")

            assert result is None

    def test_clear_cache(self, service):
        """clear_cache should remove all entries."""
        # Add some entries
        specs = ModelSpecs(
            model_id="test/model",
            name="Test",
            context_length=10000,
            max_output_tokens=2000,
            provider="test",
        )
        service._cache["test/model"] = CacheEntry(
            specs=specs, fetched_at=time.time()
        )
        service._all_models_fetched = True

        service.clear_cache()

        assert len(service._cache) == 0
        assert service._all_models_fetched is False


# =============================================================================
# CONVENIENCE FUNCTION TESTS
# =============================================================================

class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    @pytest.mark.asyncio
    async def test_fetch_model_specs_returns_dict(self, mock_api_response):
        """fetch_model_specs should return dict for backwards compatibility."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_api_response
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Clear singleton cache
            import penguin.llm.model_config as module
            module._specs_service = None

            result = await fetch_model_specs("openai/gpt-4o")

            assert isinstance(result, dict)
            assert result["context_length"] == 128000
            assert result["max_output_tokens"] == 16384
            assert result["name"] == "GPT-4o"
            assert result["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_fetch_model_specs_empty_on_not_found(self):
        """fetch_model_specs should return empty dict if not found."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = {"data": []}
            mock_response.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client

            # Clear singleton cache
            import penguin.llm.model_config as module
            module._specs_service = None

            result = await fetch_model_specs("nonexistent/model")

            assert result == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
