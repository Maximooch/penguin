"""Tests for the event system and task state management."""

import asyncio
import pytest # type: ignore
from unittest.mock import MagicMock, patch

from penguin.system.state import TaskState
from penguin.utils.events import EventBus, EventPriority, TaskEvent

# Ensure consistent event naming between test and implementation
START_EVENT = TaskEvent.STARTED.value
PROGRESS_EVENT = TaskEvent.PROGRESSED.value
COMPLETE_EVENT = TaskEvent.COMPLETED.value
NEED_INPUT_EVENT = TaskEvent.NEEDS_INPUT.value

class TestTaskState:
    """Test the TaskState enum and transitions."""
    
    def test_valid_transitions(self):
        """Test valid state transitions."""
        # Test all valid transitions for each state
        assert TaskState.ACTIVE in TaskState.get_valid_transitions(TaskState.PENDING)
        assert TaskState.FAILED in TaskState.get_valid_transitions(TaskState.PENDING)
        assert TaskState.BLOCKED in TaskState.get_valid_transitions(TaskState.PENDING)
        
        assert TaskState.PAUSED in TaskState.get_valid_transitions(TaskState.ACTIVE)
        assert TaskState.COMPLETED in TaskState.get_valid_transitions(TaskState.ACTIVE)
        assert TaskState.FAILED in TaskState.get_valid_transitions(TaskState.ACTIVE)
        
        assert TaskState.ACTIVE in TaskState.get_valid_transitions(TaskState.PAUSED)
        assert TaskState.FAILED in TaskState.get_valid_transitions(TaskState.PAUSED)
        
        # Terminal states
        assert not TaskState.get_valid_transitions(TaskState.COMPLETED)
        
        # Retry from failed
        assert TaskState.PENDING in TaskState.get_valid_transitions(TaskState.FAILED)
        
        # Transitions from blocked
        assert TaskState.PENDING in TaskState.get_valid_transitions(TaskState.BLOCKED)
        assert TaskState.ACTIVE in TaskState.get_valid_transitions(TaskState.BLOCKED)
    
    def test_invalid_transitions(self):
        """Test invalid state transitions."""
        # Test some invalid transitions
        assert TaskState.COMPLETED not in TaskState.get_valid_transitions(TaskState.PENDING)
        assert TaskState.COMPLETED not in TaskState.get_valid_transitions(TaskState.PAUSED)
        assert TaskState.ACTIVE not in TaskState.get_valid_transitions(TaskState.COMPLETED)


class TestEventBus:
    """Test the EventBus functionality."""
    
    @pytest.fixture
    def event_bus(self):
        """Create a fresh EventBus for testing."""
        bus = EventBus()
        bus.clear_all_handlers()
        return bus
    
    def test_singleton(self):
        """Test that EventBus is a singleton."""
        bus1 = EventBus.get_instance()
        bus2 = EventBus.get_instance()
        assert bus1 is bus2
    
    def test_subscribe_and_count(self, event_bus):
        """Test subscribing to events and counting subscribers."""
        def handler(data):
            pass
            
        event_bus.subscribe("test_event", handler)
        assert event_bus.get_subscriber_count("test_event") == 1
        
        # Subscribe same handler again
        event_bus.subscribe("test_event", handler)
        assert event_bus.get_subscriber_count("test_event") == 2
        
        # Subscribe to another event
        event_bus.subscribe("another_event", handler)
        assert event_bus.get_subscriber_count("another_event") == 1
    
    def test_unsubscribe(self, event_bus):
        """Test unsubscribing from events."""
        def handler1(data):
            pass
            
        def handler2(data):
            pass
            
        event_bus.subscribe("test_event", handler1)
        event_bus.subscribe("test_event", handler2)
        assert event_bus.get_subscriber_count("test_event") == 2
        
        event_bus.unsubscribe("test_event", handler1)
        assert event_bus.get_subscriber_count("test_event") == 1
        
        event_bus.unsubscribe("test_event", handler2)
        assert event_bus.get_subscriber_count("test_event") == 0
    
    @pytest.mark.asyncio
    async def test_publish(self, event_bus):
        """Test publishing events."""
        # Create mock handlers
        mock_handler = MagicMock()
        
        # Subscribe to event
        event_bus.subscribe("test_event", mock_handler)
        
        # Publish event
        test_data = {"key": "value"}
        await event_bus.publish("test_event", test_data)
        
        # Check that handler was called with correct data
        mock_handler.assert_called_once_with(test_data)
    
    @pytest.mark.asyncio
    async def test_publish_async_handler(self, event_bus):
        """Test publishing events with async handlers."""
        # Create a tracking variable
        result = {"called": False, "data": None}
        
        # Create async handler
        async def async_handler(data):
            await asyncio.sleep(0.1)  # Simulate async work
            result["called"] = True
            result["data"] = data
        
        # Subscribe to event
        event_bus.subscribe("test_event", async_handler)
        
        # Publish event
        test_data = {"key": "value"}
        await event_bus.publish("test_event", test_data)
        
        # Check that handler was called with correct data
        assert result["called"] is True
        assert result["data"] == test_data
    
    @pytest.mark.asyncio
    async def test_priority_order(self, event_bus):
        """Test that handlers are called in priority order."""
        # Create tracking variables
        call_order = []
        
        # Create handlers with different priorities
        def high_priority(data):
            call_order.append("high")
            
        def normal_priority(data):
            call_order.append("normal")
            
        def low_priority(data):
            call_order.append("low")
        
        # Subscribe handlers with different priorities
        event_bus.subscribe("test_event", normal_priority, EventPriority.NORMAL)
        event_bus.subscribe("test_event", low_priority, EventPriority.LOW)
        event_bus.subscribe("test_event", high_priority, EventPriority.HIGH)
        
        # Publish event
        await event_bus.publish("test_event")
        
        # Check execution order
        assert call_order == ["high", "normal", "low"]


@pytest.mark.asyncio
async def test_task_events_integration():
    """Test integration between TaskEvent and EventBus."""
    # Create event bus
    event_bus = EventBus.get_instance()
    event_bus.clear_all_handlers()
    
    # Create mock handlers
    mock_start = MagicMock()
    mock_progress = MagicMock()
    mock_complete = MagicMock()
    
    # Subscribe to events with the correct event names
    event_bus.subscribe(START_EVENT, mock_start)
    event_bus.subscribe(PROGRESS_EVENT, mock_progress)
    event_bus.subscribe(COMPLETE_EVENT, mock_complete)
    
    # Publish events with the correct event names
    await event_bus.publish(START_EVENT, {"task_id": "test123"})
    await event_bus.publish(PROGRESS_EVENT, {"task_id": "test123", "progress": 50})
    await event_bus.publish(COMPLETE_EVENT, {"task_id": "test123"})
    
    # Check that handlers were called
    mock_start.assert_called_once()
    mock_progress.assert_called_once()
    mock_complete.assert_called_once()
    
    # Check data
    assert mock_start.call_args[0][0]["task_id"] == "test123"
    assert mock_progress.call_args[0][0]["progress"] == 50
    assert mock_complete.call_args[0][0]["task_id"] == "test123" 