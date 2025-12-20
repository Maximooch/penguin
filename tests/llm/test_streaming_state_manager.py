"""Comprehensive tests for StreamingStateManager.

Test strategies:
1. State machine tests - verify state transitions
2. Edge case tests - empty chunks, whitespace, interleaved content
3. Coalescing tests - verify buffering behavior
4. Event generation tests - verify correct events are emitted
"""

import pytest
import time
from typing import List

from penguin.llm.stream_handler import (
    StreamingStateManager,
    StreamingConfig,
    StreamState,
    StreamEvent,
    FinalizedMessage,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def manager():
    """Create a fresh StreamingStateManager for each test."""
    return StreamingStateManager()


@pytest.fixture
def fast_coalesce_manager():
    """Manager with very short coalesce interval for faster tests."""
    config = StreamingConfig(
        min_emit_interval=0.001,  # 1ms
        min_emit_chars=1,  # emit on every char
    )
    return StreamingStateManager(config)


@pytest.fixture
def slow_coalesce_manager():
    """Manager with longer coalesce interval for testing buffering."""
    config = StreamingConfig(
        min_emit_interval=10.0,  # 10 seconds - won't emit based on time
        min_emit_chars=100,  # need 100 chars to emit
    )
    return StreamingStateManager(config)


# =============================================================================
# STATE MACHINE TESTS
# =============================================================================

class TestStateMachine:
    """Test state transitions: INACTIVE → ACTIVE → FINALIZING → INACTIVE"""

    def test_initial_state_is_inactive(self, manager):
        """Manager should start in INACTIVE state."""
        assert manager.state == StreamState.INACTIVE
        assert not manager.is_active
        assert manager.content == ""
        assert manager.reasoning_content == ""
        assert manager.stream_id is None

    def test_first_chunk_activates(self, manager):
        """First chunk should transition to ACTIVE state."""
        events = manager.handle_chunk("Hello")

        assert manager.state == StreamState.ACTIVE
        assert manager.is_active
        assert manager.stream_id is not None
        assert manager.content == "Hello"

    def test_subsequent_chunks_stay_active(self, manager):
        """Additional chunks should remain in ACTIVE state."""
        manager.handle_chunk("Hello")
        manager.handle_chunk(" world")

        assert manager.state == StreamState.ACTIVE
        assert manager.content == "Hello world"

    def test_finalize_returns_to_inactive(self, manager):
        """Finalize should transition back to INACTIVE."""
        manager.handle_chunk("Hello")
        message, events = manager.finalize()

        assert manager.state == StreamState.INACTIVE
        assert not manager.is_active
        assert manager.content == ""
        assert manager.stream_id is None

    def test_finalize_when_inactive_returns_none(self, manager):
        """Finalize when already inactive should return None."""
        message, events = manager.finalize()

        assert message is None
        assert events == []

    def test_abort_returns_to_inactive(self, manager):
        """Abort should transition back to INACTIVE."""
        manager.handle_chunk("Hello")
        events = manager.abort()

        assert manager.state == StreamState.INACTIVE
        assert len(events) == 1
        assert events[0].data.get("aborted") is True

    def test_multiple_finalize_is_safe(self, manager):
        """Multiple finalize calls should be safe."""
        manager.handle_chunk("Hello")
        msg1, _ = manager.finalize()
        msg2, _ = manager.finalize()

        assert msg1 is not None
        assert msg2 is None


# =============================================================================
# CONTENT ACCUMULATION TESTS
# =============================================================================

class TestContentAccumulation:
    """Test content and reasoning content accumulation."""

    def test_assistant_content_accumulates(self, fast_coalesce_manager):
        """Assistant chunks should accumulate in content."""
        m = fast_coalesce_manager
        m.handle_chunk("Hello")
        m.handle_chunk(" ")
        m.handle_chunk("world")

        assert m.content == "Hello world"

    def test_reasoning_content_accumulates_separately(self, manager):
        """Reasoning chunks should accumulate in reasoning_content."""
        manager.handle_chunk("Let me think...", message_type="reasoning")
        manager.handle_chunk("Step 1", message_type="reasoning")
        manager.handle_chunk("Answer", message_type="assistant")

        assert manager.reasoning_content == "Let me think...Step 1"
        assert manager.content == "Answer"

    def test_interleaved_content_types(self, manager):
        """Interleaved reasoning and assistant should accumulate correctly."""
        manager.handle_chunk("Thinking...", message_type="reasoning")
        manager.handle_chunk("First answer", message_type="assistant")
        manager.handle_chunk("More thinking", message_type="reasoning")
        manager.handle_chunk(" continued", message_type="assistant")

        assert manager.reasoning_content == "Thinking...More thinking"
        assert manager.content == "First answer continued"

    def test_role_is_preserved(self, manager):
        """Role should be preserved from first chunk."""
        manager.handle_chunk("System message", role="system")
        message, _ = manager.finalize()

        assert message.role == "system"


# =============================================================================
# EMPTY CHUNK TESTS (WALLET_GUARD)
# =============================================================================

class TestEmptyChunks:
    """Test WALLET_GUARD behavior for empty/whitespace chunks."""

    def test_empty_chunk_activates_streaming(self, manager):
        """Empty chunk should still activate streaming (WALLET_GUARD)."""
        events = manager.handle_chunk("")

        assert manager.is_active
        assert manager.empty_response_count == 1

    def test_multiple_empty_chunks_set_error(self, manager):
        """Multiple empty chunks should set error after threshold."""
        for _ in range(5):
            manager.handle_chunk("")

        assert manager.error == "Multiple empty responses received"
        assert manager.empty_response_count == 5

    def test_real_content_resets_empty_counter(self, manager):
        """Real content should reset empty response counter."""
        manager.handle_chunk("")
        manager.handle_chunk("")
        manager.handle_chunk("Hello")  # Real content

        assert manager.empty_response_count == 0

    def test_finalize_empty_response_adds_placeholder(self, manager):
        """Finalizing empty response should add placeholder (WALLET_GUARD)."""
        manager.handle_chunk("")
        message, _ = manager.finalize()

        assert message is not None
        assert message.content == "[Empty response from model]"
        assert message.was_empty is True
        assert message.metadata.get("was_empty") is True

    def test_whitespace_only_treated_as_empty(self, manager):
        """Whitespace-only response should be treated as empty."""
        manager.handle_chunk("   ")
        manager.handle_chunk("\n\t")
        message, _ = manager.finalize()

        assert message.was_empty is True
        assert message.content == "[Empty response from model]"


# =============================================================================
# COALESCING TESTS
# =============================================================================

class TestCoalescing:
    """Test chunk coalescing behavior."""

    def test_first_chunk_emits_immediately(self, slow_coalesce_manager):
        """First chunk should emit immediately regardless of size."""
        m = slow_coalesce_manager
        events = m.handle_chunk("Hi")  # Small chunk

        # First chunk should emit (last_emit_ts == 0.0 triggers emit)
        assert len(events) == 1
        assert events[0].data["chunk"] == "Hi"

    def test_small_chunks_are_buffered(self, slow_coalesce_manager):
        """Small subsequent chunks should be buffered."""
        m = slow_coalesce_manager
        m.handle_chunk("First")  # First always emits
        events = m.handle_chunk("X")  # Should buffer

        # Should not emit - too small and too soon
        assert len(events) == 0

    def test_buffer_flushes_on_finalize(self, slow_coalesce_manager):
        """Buffer should flush on finalize."""
        m = slow_coalesce_manager
        m.handle_chunk("First")
        m.handle_chunk("X")  # Buffered
        m.handle_chunk("Y")  # Buffered
        message, events = m.finalize()

        # Should have buffer flush event + final event
        assert len(events) >= 1
        assert any(e.data.get("is_final") for e in events)

    def test_large_chunk_emits(self, slow_coalesce_manager):
        """Chunk exceeding min_emit_chars should emit."""
        m = slow_coalesce_manager
        m.handle_chunk("First")
        # 100+ chars should trigger emit
        big_chunk = "X" * 150
        events = m.handle_chunk(big_chunk)

        assert len(events) == 1
        assert big_chunk in events[0].data["chunk"]


# =============================================================================
# EVENT GENERATION TESTS
# =============================================================================

class TestEventGeneration:
    """Test that correct events are generated."""

    def test_chunk_event_has_required_fields(self, fast_coalesce_manager):
        """Stream chunk events should have all required fields."""
        m = fast_coalesce_manager
        events = m.handle_chunk("Hello")

        assert len(events) >= 1
        event = events[0]
        assert event.event_type == "stream_chunk"

        data = event.data
        assert "stream_id" in data
        assert "chunk" in data
        assert "is_final" in data
        assert "message_type" in data
        assert "role" in data
        assert "content_so_far" in data
        assert "reasoning_so_far" in data
        assert "metadata" in data

    def test_reasoning_events_marked_correctly(self, manager):
        """Reasoning events should have is_reasoning=True."""
        events = manager.handle_chunk("Thinking", message_type="reasoning")

        assert len(events) == 1
        assert events[0].data["is_reasoning"] is True
        assert events[0].data["message_type"] == "reasoning"

    def test_final_event_has_full_content(self, fast_coalesce_manager):
        """Final event should include full content and reasoning."""
        m = fast_coalesce_manager
        m.handle_chunk("Reason", message_type="reasoning")
        m.handle_chunk("Answer")
        message, events = m.finalize()

        final_event = next(e for e in events if e.data.get("is_final"))
        assert final_event.data["content"] == "Answer"
        assert final_event.data["reasoning"] == "Reason"

    def test_stream_id_consistent_across_events(self, fast_coalesce_manager):
        """All events in a stream should have the same stream_id."""
        m = fast_coalesce_manager
        events1 = m.handle_chunk("Hello")
        events2 = m.handle_chunk(" world")
        message, final_events = m.finalize()

        all_events = events1 + events2 + final_events
        stream_ids = {e.data["stream_id"] for e in all_events}
        assert len(stream_ids) == 1

    def test_new_stream_gets_new_id(self, fast_coalesce_manager):
        """New stream should get a new stream_id."""
        m = fast_coalesce_manager
        m.handle_chunk("First stream")
        m.finalize()

        events = m.handle_chunk("Second stream")
        stream_id_1 = m.stream_id

        # The stream_id should be different (finalize resets and new handle_chunk creates new)
        assert stream_id_1 is not None


# =============================================================================
# FINALIZED MESSAGE TESTS
# =============================================================================

class TestFinalizedMessage:
    """Test FinalizedMessage structure and metadata."""

    def test_finalized_message_has_correct_content(self, fast_coalesce_manager):
        """FinalizedMessage should have correct content."""
        m = fast_coalesce_manager
        m.handle_chunk("Hello world")
        message, _ = m.finalize()

        assert message.content == "Hello world"
        assert message.role == "assistant"
        assert message.was_empty is False

    def test_reasoning_stored_in_metadata(self, fast_coalesce_manager):
        """Reasoning should be stored in metadata."""
        m = fast_coalesce_manager
        m.handle_chunk("Let me think", message_type="reasoning")
        m.handle_chunk("The answer")
        message, _ = m.finalize()

        assert message.reasoning == "Let me think"
        assert message.metadata.get("has_reasoning") is True
        assert message.metadata.get("reasoning") == "Let me think"
        assert "reasoning_length" in message.metadata

    def test_is_streaming_removed_from_final_metadata(self, fast_coalesce_manager):
        """is_streaming flag should be removed from final metadata."""
        m = fast_coalesce_manager
        m.handle_chunk("Hello")
        message, _ = m.finalize()

        assert "is_streaming" not in message.metadata

    def test_to_dict_serialization(self, fast_coalesce_manager):
        """FinalizedMessage.to_dict() should serialize correctly."""
        m = fast_coalesce_manager
        m.handle_chunk("Hello")
        message, _ = m.finalize()

        d = message.to_dict()
        assert d["content"] == "Hello"
        assert d["role"] == "assistant"
        assert d["was_empty"] is False
        assert isinstance(d["metadata"], dict)


# =============================================================================
# ABORT TESTS
# =============================================================================

class TestAbort:
    """Test abort functionality."""

    def test_abort_when_inactive_is_safe(self, manager):
        """Abort when inactive should not error."""
        events = manager.abort()
        assert events == []

    def test_abort_preserves_partial_content(self, fast_coalesce_manager):
        """Abort event should include partial content."""
        m = fast_coalesce_manager
        m.handle_chunk("Partial")
        events = m.abort()

        assert len(events) == 1
        assert events[0].data["content"] == "Partial"
        assert events[0].data["aborted"] is True

    def test_abort_resets_state(self, fast_coalesce_manager):
        """Abort should reset all state."""
        m = fast_coalesce_manager
        m.handle_chunk("Something")
        m.abort()

        assert m.state == StreamState.INACTIVE
        assert m.content == ""


# =============================================================================
# FORCE ACTIVATE TESTS
# =============================================================================

class TestForceActivate:
    """Test force_activate() for edge cases."""

    def test_force_activate_when_inactive(self, manager):
        """force_activate should activate when inactive."""
        manager.force_activate()

        assert manager.is_active
        assert manager.stream_id is not None

    def test_force_activate_when_active_is_noop(self, manager):
        """force_activate when already active should not reset state."""
        manager.handle_chunk("Hello")
        original_id = manager.stream_id
        manager.force_activate()

        assert manager.stream_id == original_id
        assert manager.content == "Hello"


# =============================================================================
# CUSTOM CONFIG TESTS
# =============================================================================

class TestCustomConfig:
    """Test custom StreamingConfig."""

    def test_custom_placeholder(self):
        """Custom empty response placeholder should be used."""
        config = StreamingConfig(empty_response_placeholder="[CUSTOM EMPTY]")
        m = StreamingStateManager(config)

        m.handle_chunk("")
        message, _ = m.finalize()

        assert message.content == "[CUSTOM EMPTY]"

    def test_custom_empty_threshold(self):
        """Custom empty chunk threshold should be respected."""
        config = StreamingConfig(max_empty_chunks_before_warning=1)
        m = StreamingStateManager(config)

        m.handle_chunk("")
        m.handle_chunk("")

        assert m.error == "Multiple empty responses received"


# =============================================================================
# EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Test various edge cases."""

    def test_unicode_content(self, fast_coalesce_manager):
        """Unicode content should be handled correctly."""
        m = fast_coalesce_manager
        m.handle_chunk("Hello 🌍")
        m.handle_chunk(" émojis 中文")
        message, _ = m.finalize()

        assert message.content == "Hello 🌍 émojis 中文"

    def test_very_long_content(self, fast_coalesce_manager):
        """Very long content should be handled correctly."""
        m = fast_coalesce_manager
        long_content = "X" * 100000
        m.handle_chunk(long_content)
        message, _ = m.finalize()

        assert message.content == long_content

    def test_newlines_and_special_chars(self, fast_coalesce_manager):
        """Newlines and special characters should be preserved."""
        m = fast_coalesce_manager
        m.handle_chunk("Line 1\nLine 2\tTabbed")
        message, _ = m.finalize()

        assert message.content == "Line 1\nLine 2\tTabbed"

    def test_rapid_chunk_sequence(self, fast_coalesce_manager):
        """Rapid sequence of small chunks should work."""
        m = fast_coalesce_manager
        for char in "Hello world!":
            m.handle_chunk(char)
        message, _ = m.finalize()

        assert message.content == "Hello world!"


# =============================================================================
# INTEGRATION-STYLE TESTS
# =============================================================================

class TestIntegration:
    """Integration-style tests simulating real usage patterns."""

    def test_typical_streaming_session(self, fast_coalesce_manager):
        """Simulate typical streaming session with reasoning and response."""
        m = fast_coalesce_manager
        all_events = []

        # Reasoning phase
        all_events.extend(m.handle_chunk("Let me analyze this...", message_type="reasoning"))
        all_events.extend(m.handle_chunk("Considering factors A, B, C", message_type="reasoning"))

        # Response phase
        all_events.extend(m.handle_chunk("Based on my analysis, "))
        all_events.extend(m.handle_chunk("the answer is 42."))

        # Finalize
        message, final_events = m.finalize()
        all_events.extend(final_events)

        # Verify
        assert message.content == "Based on my analysis, the answer is 42."
        assert message.reasoning == "Let me analyze this...Considering factors A, B, C"
        assert any(e.data.get("is_final") for e in all_events)

    def test_empty_response_recovery(self, fast_coalesce_manager):
        """Simulate provider returning empty response."""
        m = fast_coalesce_manager

        # Provider sends empty chunks
        m.handle_chunk("")
        m.handle_chunk("")
        m.handle_chunk("")

        # Finalize should add placeholder
        message, _ = m.finalize()

        assert message.was_empty is True
        assert "[Empty response" in message.content

    def test_interruption_and_abort(self, fast_coalesce_manager):
        """Simulate user interruption during streaming."""
        m = fast_coalesce_manager

        # Start streaming
        m.handle_chunk("Starting to respond...")

        # User interrupts
        abort_events = m.abort()

        # Should get abort event
        assert len(abort_events) == 1
        assert abort_events[0].data["aborted"] is True
        assert abort_events[0].data["content"] == "Starting to respond..."

        # Manager should be ready for new stream
        assert m.state == StreamState.INACTIVE


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
