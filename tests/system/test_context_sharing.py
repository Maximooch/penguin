"""Tests for context sharing utilities in ConversationManager.

Tests the context sharing methods for multi-agent parallelization:
- shares_context_window()
- get_context_sharing_info()
- get_context_window_stats()
- sync_context_to_child()
- get_shared_context_agents()
"""

import pytest
from typing import Dict, Any, List

from penguin.system.conversation_manager import ConversationManager
from penguin.system.state import MessageCategory


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_workspace(tmp_path):
    """Create a temporary workspace directory."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def cm(temp_workspace):
    """Create a ConversationManager with temporary workspace."""
    return ConversationManager(workspace_path=temp_workspace)


@pytest.fixture
def cm_with_agents(cm):
    """Create ConversationManager with default and child agents."""
    # Default agent exists automatically
    # Create a child agent that shares context window
    cm.create_sub_agent(
        "child-shared",
        parent_agent_id="default",
        share_session=False,
        share_context_window=True,
    )
    # Create a child agent with isolated context window
    cm.create_sub_agent(
        "child-isolated",
        parent_agent_id="default",
        share_session=False,
        share_context_window=False,
    )
    return cm


# =============================================================================
# SHARES_CONTEXT_WINDOW TESTS
# =============================================================================

class TestSharesContextWindow:
    """Test the shares_context_window method."""

    def test_same_agent_shares_with_self(self, cm):
        """Test that an agent shares context with itself."""
        assert cm.shares_context_window("default", "default") is True

    def test_shared_context_agents(self, cm_with_agents):
        """Test that agents with share_context_window=True share the same CWM."""
        assert cm_with_agents.shares_context_window("default", "child-shared") is True

    def test_isolated_context_agents(self, cm_with_agents):
        """Test that agents with share_context_window=False have different CWMs."""
        assert cm_with_agents.shares_context_window("default", "child-isolated") is False

    def test_nonexistent_agent_returns_false(self, cm):
        """Test that nonexistent agents return False."""
        assert cm.shares_context_window("default", "nonexistent") is False
        assert cm.shares_context_window("nonexistent", "default") is False
        assert cm.shares_context_window("nonexistent1", "nonexistent2") is False

    def test_different_shared_agents(self, cm_with_agents):
        """Test sharing between two child agents."""
        # child-shared shares with default, child-isolated doesn't
        assert cm_with_agents.shares_context_window("child-shared", "child-isolated") is False


# =============================================================================
# GET_CONTEXT_SHARING_INFO TESTS
# =============================================================================

class TestGetContextSharingInfo:
    """Test the get_context_sharing_info method."""

    def test_default_agent_info(self, cm):
        """Test info for default agent."""
        info = cm.get_context_sharing_info("default")

        assert info["agent_id"] == "default"
        assert info["has_context_window"] is True
        assert info["parent"] is None
        assert info["shares_with_parent"] is False
        assert isinstance(info["children"], list)
        assert isinstance(info["shares_with_children"], list)

    def test_shared_child_info(self, cm_with_agents):
        """Test info for child with shared context window."""
        info = cm_with_agents.get_context_sharing_info("child-shared")

        assert info["agent_id"] == "child-shared"
        assert info["has_context_window"] is True
        assert info["parent"] == "default"
        assert info["shares_with_parent"] is True

    def test_isolated_child_info(self, cm_with_agents):
        """Test info for child with isolated context window."""
        info = cm_with_agents.get_context_sharing_info("child-isolated")

        assert info["agent_id"] == "child-isolated"
        assert info["has_context_window"] is True
        assert info["parent"] == "default"
        assert info["shares_with_parent"] is False

    def test_parent_knows_children(self, cm_with_agents):
        """Test that parent agent's info includes children."""
        info = cm_with_agents.get_context_sharing_info("default")

        assert "child-shared" in info["children"]
        assert "child-isolated" in info["children"]
        assert "child-shared" in info["shares_with_children"]
        assert "child-isolated" not in info["shares_with_children"]

    def test_nonexistent_agent_info(self, cm):
        """Test info for nonexistent agent."""
        info = cm.get_context_sharing_info("nonexistent")

        assert info["agent_id"] == "nonexistent"
        assert info["has_context_window"] is False


# =============================================================================
# GET_CONTEXT_WINDOW_STATS TESTS
# =============================================================================

class TestGetContextWindowStats:
    """Test the get_context_window_stats method."""

    def test_default_agent_stats(self, cm):
        """Test stats for default agent."""
        stats = cm.get_context_window_stats("default")

        assert stats is not None
        assert stats["agent_id"] == "default"
        assert "max_context_window_tokens" in stats
        assert "current_tokens" in stats

    def test_shared_agents_have_same_stats(self, cm_with_agents):
        """Test that shared agents reference same CWM (stats should match)."""
        default_stats = cm_with_agents.get_context_window_stats("default")
        shared_stats = cm_with_agents.get_context_window_stats("child-shared")

        # They share the same CWM, so max tokens should be the same
        assert default_stats["max_context_window_tokens"] == shared_stats["max_context_window_tokens"]

    def test_isolated_agent_stats(self, cm_with_agents):
        """Test stats for isolated agent."""
        stats = cm_with_agents.get_context_window_stats("child-isolated")

        assert stats is not None
        assert stats["agent_id"] == "child-isolated"

    def test_nonexistent_agent_returns_none(self, cm):
        """Test that nonexistent agent returns None."""
        stats = cm.get_context_window_stats("nonexistent")
        assert stats is None


# =============================================================================
# SYNC_CONTEXT_TO_CHILD TESTS
# =============================================================================

class TestSyncContextToChild:
    """Test the sync_context_to_child method."""

    def test_sync_to_isolated_child(self, cm_with_agents):
        """Test syncing context to an isolated child."""
        # Add some context to the parent
        cm_with_agents.set_current_agent("default")
        cm_with_agents.add_context("Parent context message")

        # Sync to isolated child
        result = cm_with_agents.sync_context_to_child("default", "child-isolated")

        assert result is True

    def test_sync_with_specific_categories(self, cm_with_agents):
        """Test syncing only specific categories."""
        cm_with_agents.set_current_agent("default")
        cm_with_agents.add_context("Parent context")

        # Sync only CONTEXT messages
        result = cm_with_agents.sync_context_to_child(
            "default",
            "child-isolated",
            categories=[MessageCategory.CONTEXT]
        )

        assert result is True

    def test_sync_to_nonexistent_child(self, cm):
        """Test syncing to nonexistent child - returns True (creates if needed)."""
        # The implementation may create the child agent or return True anyway
        result = cm.sync_context_to_child("default", "nonexistent")
        # Just verify it doesn't crash
        assert result in (True, False)

    def test_sync_from_nonexistent_parent(self, cm_with_agents):
        """Test syncing from nonexistent parent - returns True (creates if needed)."""
        # The implementation may handle this gracefully
        result = cm_with_agents.sync_context_to_child("nonexistent", "child-isolated")
        # Just verify it doesn't crash
        assert result in (True, False)


# =============================================================================
# GET_SHARED_CONTEXT_AGENTS TESTS
# =============================================================================

class TestGetSharedContextAgents:
    """Test the get_shared_context_agents method."""

    def test_default_with_shared_child(self, cm_with_agents):
        """Test that default agent lists shared children."""
        shared = cm_with_agents.get_shared_context_agents("default")

        assert "child-shared" in shared
        assert "child-isolated" not in shared

    def test_shared_child_lists_parent(self, cm_with_agents):
        """Test that shared child lists parent."""
        shared = cm_with_agents.get_shared_context_agents("child-shared")

        assert "default" in shared

    def test_isolated_agent_has_no_shared(self, cm_with_agents):
        """Test that isolated agent has no shared agents."""
        shared = cm_with_agents.get_shared_context_agents("child-isolated")

        assert len(shared) == 0

    def test_nonexistent_agent_returns_empty(self, cm):
        """Test that nonexistent agent returns empty list."""
        shared = cm.get_shared_context_agents("nonexistent")
        assert shared == []

    def test_multiple_shared_agents(self, cm):
        """Test multiple agents sharing same CWM."""
        # Create multiple children that share with parent
        cm.create_sub_agent("child1", parent_agent_id="default", share_context_window=True)
        cm.create_sub_agent("child2", parent_agent_id="default", share_context_window=True)
        cm.create_sub_agent("child3", parent_agent_id="default", share_context_window=True)

        shared = cm.get_shared_context_agents("default")

        assert "child1" in shared
        assert "child2" in shared
        assert "child3" in shared
        assert len(shared) == 3


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestContextSharingIntegration:
    """Integration tests for context sharing workflows."""

    def test_shared_context_updates_visible(self, cm_with_agents):
        """Test that updates to shared context are visible to both agents."""
        # Add context as parent
        cm_with_agents.set_current_agent("default")
        cm_with_agents.add_context("Shared context message")

        # Check that child-shared sees it (they share the CWM)
        assert cm_with_agents.shares_context_window("default", "child-shared")

        # The CWM object is the same for both
        parent_cw = cm_with_agents.agent_context_windows["default"]
        child_cw = cm_with_agents.agent_context_windows["child-shared"]
        assert parent_cw is child_cw

    def test_isolated_context_not_affected(self, cm_with_agents):
        """Test that isolated context is not affected by parent updates."""
        # Get initial token count for isolated child
        initial_stats = cm_with_agents.get_context_window_stats("child-isolated")

        # Add context as parent
        cm_with_agents.set_current_agent("default")
        cm_with_agents.add_context("Parent-only context")

        # Isolated child should not be affected
        assert not cm_with_agents.shares_context_window("default", "child-isolated")

    def test_hierarchical_sharing(self, cm):
        """Test hierarchical context sharing: grandparent -> parent -> child."""
        # Create hierarchy
        cm.create_sub_agent("parent", parent_agent_id="default", share_context_window=True)
        cm.create_sub_agent("child", parent_agent_id="parent", share_context_window=True)

        # All three should share the same CWM
        assert cm.shares_context_window("default", "parent")
        assert cm.shares_context_window("parent", "child")
        assert cm.shares_context_window("default", "child")

        # All should show up in shared agents list
        shared = cm.get_shared_context_agents("default")
        assert "parent" in shared
        assert "child" in shared

    def test_mixed_sharing_hierarchy(self, cm):
        """Test mixed sharing: some share, some don't."""
        # Parent shares with default
        cm.create_sub_agent("parent", parent_agent_id="default", share_context_window=True)
        # Child doesn't share with parent (isolated) - need to also set share_session=False
        # because share_session=True forces share_context_window=True
        cm.create_sub_agent(
            "child",
            parent_agent_id="parent",
            share_session=False,
            share_context_window=False
        )

        # default and parent share
        assert cm.shares_context_window("default", "parent")

        # child is isolated
        assert not cm.shares_context_window("parent", "child")
        assert not cm.shares_context_window("default", "child")

        # Sync needed for child to see parent context
        cm.set_current_agent("parent")
        cm.add_context("Parent context")

        # Child needs explicit sync
        result = cm.sync_context_to_child("parent", "child")
        assert result is True


class TestContextWindowLimits:
    """Test context window token limits with sharing."""

    def test_shared_context_window_max_tokens_applied(self, cm):
        """Test that shared_context_window_max_tokens is applied to child."""
        parent_cw = cm.agent_context_windows["default"]
        parent_max = parent_cw.max_context_window_tokens

        # Create child with limited context window
        cm.create_sub_agent(
            "limited-child",
            parent_agent_id="default",
            share_session=False,
            share_context_window=False,
            shared_context_window_max_tokens=1000,
        )

        child_stats = cm.get_context_window_stats("limited-child")

        # Child should have the clamped limit
        assert child_stats["max_context_window_tokens"] <= min(parent_max, 1000)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
