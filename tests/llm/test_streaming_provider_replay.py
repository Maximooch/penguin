"""Provider replay tests for StreamingStateManager.

These tests replay recorded provider responses to verify the StreamingStateManager
handles different provider behaviors correctly.

To add new fixtures:
1. Capture real provider responses
2. Add to fixtures/provider_responses.json
3. Tests will automatically pick them up
"""

import json
import pytest
from pathlib import Path
from typing import Any, Dict, List

from penguin.llm.stream_handler import (
    StreamingStateManager,
    StreamingConfig,
    StreamState,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def fixtures_path() -> Path:
    """Path to fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def provider_responses(fixtures_path: Path) -> Dict[str, Any]:
    """Load provider response fixtures."""
    fixture_file = fixtures_path / "provider_responses.json"
    with open(fixture_file) as f:
        return json.load(f)


@pytest.fixture
def manager():
    """Create StreamingStateManager with fast coalescing for tests."""
    config = StreamingConfig(
        min_emit_interval=0.001,
        min_emit_chars=1,
    )
    return StreamingStateManager(config)


# =============================================================================
# PARAMETERIZED REPLAY TESTS
# =============================================================================

def get_fixture_ids() -> List[str]:
    """Get list of fixture IDs for parameterization."""
    fixture_file = Path(__file__).parent / "fixtures" / "provider_responses.json"
    with open(fixture_file) as f:
        data = json.load(f)
    return [k for k in data.keys() if not k.startswith("_")]


@pytest.fixture(params=get_fixture_ids())
def fixture_data(request, provider_responses):
    """Parameterized fixture returning each provider response."""
    fixture_id = request.param
    data = provider_responses[fixture_id]
    data["fixture_id"] = fixture_id
    return data


class TestProviderReplay:
    """Replay provider responses and verify correct handling."""

    def test_content_matches_expected(self, fixture_data, manager):
        """Replayed chunks should produce expected content."""
        for chunk_data in fixture_data["chunks"]:
            manager.handle_chunk(
                chunk_data["content"],
                message_type=chunk_data.get("type", "assistant"),
            )

        message, _ = manager.finalize()

        expected = fixture_data["expected_content"]
        actual = message.content

        assert actual == expected, (
            f"Fixture '{fixture_data['fixture_id']}' content mismatch:\n"
            f"Expected: {repr(expected)}\n"
            f"Actual: {repr(actual)}"
        )

    def test_reasoning_matches_expected(self, fixture_data, manager):
        """Replayed chunks should produce expected reasoning."""
        for chunk_data in fixture_data["chunks"]:
            manager.handle_chunk(
                chunk_data["content"],
                message_type=chunk_data.get("type", "assistant"),
            )

        message, _ = manager.finalize()

        expected = fixture_data["expected_reasoning"]
        actual = message.reasoning

        assert actual == expected, (
            f"Fixture '{fixture_data['fixture_id']}' reasoning mismatch:\n"
            f"Expected: {repr(expected)}\n"
            f"Actual: {repr(actual)}"
        )

    def test_was_empty_flag(self, fixture_data, manager):
        """Check was_empty flag is set correctly."""
        for chunk_data in fixture_data["chunks"]:
            manager.handle_chunk(
                chunk_data["content"],
                message_type=chunk_data.get("type", "assistant"),
            )

        message, _ = manager.finalize()

        expected_empty = fixture_data.get("expected_was_empty", False)
        assert message.was_empty == expected_empty, (
            f"Fixture '{fixture_data['fixture_id']}' was_empty mismatch"
        )


# =============================================================================
# SPECIFIC PROVIDER TESTS
# =============================================================================

class TestOpenAIProvider:
    """Tests specific to OpenAI-style responses."""

    def test_openai_simple_response(self, provider_responses, manager):
        """Test simple OpenAI response."""
        data = provider_responses["openai_simple"]

        for chunk_data in data["chunks"]:
            manager.handle_chunk(chunk_data["content"])

        message, events = manager.finalize()

        assert message.content == data["expected_content"]
        # Should have final event
        assert any(e.data.get("is_final") for e in events)

    def test_rapid_small_tokens(self, provider_responses, manager):
        """Test rapid small token stream (typical GPT behavior)."""
        data = provider_responses["rapid_small_tokens"]

        all_events = []
        for chunk_data in data["chunks"]:
            events = manager.handle_chunk(chunk_data["content"])
            all_events.extend(events)

        message, final_events = manager.finalize()
        all_events.extend(final_events)

        assert message.content == data["expected_content"]
        # With fast coalescing, should have roughly one event per chunk
        assert len(all_events) > 5


class TestAnthropicProvider:
    """Tests specific to Anthropic-style responses with reasoning."""

    def test_reasoning_separated(self, provider_responses, manager):
        """Test that reasoning is separated from assistant content."""
        data = provider_responses["anthropic_with_reasoning"]

        for chunk_data in data["chunks"]:
            manager.handle_chunk(
                chunk_data["content"],
                message_type=chunk_data["type"],
            )

        message, _ = manager.finalize()

        # Reasoning should be separate
        assert message.reasoning == data["expected_reasoning"]
        assert message.content == data["expected_content"]

        # Metadata should indicate has_reasoning
        assert message.metadata.get("has_reasoning") is True
        assert "reasoning_length" in message.metadata

    def test_interleaved_reasoning(self, provider_responses, manager):
        """Test interleaved reasoning and assistant content."""
        data = provider_responses["interleaved_reasoning"]

        for chunk_data in data["chunks"]:
            manager.handle_chunk(
                chunk_data["content"],
                message_type=chunk_data["type"],
            )

        message, _ = manager.finalize()

        # Should maintain order within each stream
        assert message.content == data["expected_content"]
        assert message.reasoning == data["expected_reasoning"]


class TestEdgeCases:
    """Tests for edge case provider behaviors."""

    def test_empty_first_chunks(self, provider_responses, manager):
        """Test handling of empty first chunks."""
        data = provider_responses["empty_first_chunk"]

        for chunk_data in data["chunks"]:
            manager.handle_chunk(chunk_data["content"])

        message, _ = manager.finalize()

        # Should still get the content despite empty first chunks
        assert message.content == data["expected_content"]
        assert message.was_empty is False

    def test_all_empty_triggers_wallet_guard(self, provider_responses, manager):
        """Test that all-empty response triggers WALLET_GUARD."""
        data = provider_responses["all_empty_response"]

        for chunk_data in data["chunks"]:
            manager.handle_chunk(chunk_data["content"])

        message, _ = manager.finalize()

        # Should have placeholder and was_empty flag
        assert "[Empty response" in message.content
        assert message.was_empty is True

    def test_whitespace_preservation(self, provider_responses, manager):
        """Test that whitespace is preserved in content."""
        data = provider_responses["whitespace_chunks"]

        for chunk_data in data["chunks"]:
            manager.handle_chunk(chunk_data["content"])

        message, _ = manager.finalize()

        # Whitespace should be preserved
        assert message.content == data["expected_content"]

    def test_unicode_handling(self, provider_responses, manager):
        """Test unicode content is handled correctly."""
        data = provider_responses["unicode_heavy"]

        for chunk_data in data["chunks"]:
            manager.handle_chunk(chunk_data["content"])

        message, _ = manager.finalize()

        assert message.content == data["expected_content"]


class TestCodeBlocks:
    """Tests for code block handling."""

    def test_code_block_preserved(self, provider_responses, manager):
        """Test that code blocks are preserved correctly."""
        data = provider_responses["code_block_response"]

        for chunk_data in data["chunks"]:
            manager.handle_chunk(chunk_data["content"])

        message, _ = manager.finalize()

        # Code block structure should be preserved
        assert "```python" in message.content
        assert "def hello():" in message.content
        assert "```" in message.content


# =============================================================================
# EVENT SEQUENCE TESTS
# =============================================================================

class TestEventSequence:
    """Test that events are emitted in correct sequence."""

    def test_events_have_consistent_stream_id(self, provider_responses, manager):
        """All events in a stream should have same stream_id."""
        data = provider_responses["openai_simple"]

        all_events = []
        for chunk_data in data["chunks"]:
            events = manager.handle_chunk(chunk_data["content"])
            all_events.extend(events)

        _, final_events = manager.finalize()
        all_events.extend(final_events)

        # All events should have same stream_id
        stream_ids = {e.data.get("stream_id") for e in all_events}
        assert len(stream_ids) == 1
        assert None not in stream_ids

    def test_final_event_is_last(self, provider_responses, manager):
        """Final event should be the last event."""
        data = provider_responses["gemini_larger_chunks"]

        for chunk_data in data["chunks"]:
            manager.handle_chunk(chunk_data["content"])

        _, events = manager.finalize()

        # Last event should be final
        assert events[-1].data.get("is_final") is True

    def test_reasoning_events_marked(self, provider_responses, manager):
        """Reasoning events should be marked as such."""
        data = provider_responses["anthropic_with_reasoning"]

        all_events = []
        for chunk_data in data["chunks"]:
            events = manager.handle_chunk(
                chunk_data["content"],
                message_type=chunk_data["type"],
            )
            all_events.extend(events)

        reasoning_events = [e for e in all_events if e.data.get("is_reasoning")]
        assistant_events = [e for e in all_events if not e.data.get("is_reasoning")]

        # Should have both types
        assert len(reasoning_events) > 0
        assert len(assistant_events) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
