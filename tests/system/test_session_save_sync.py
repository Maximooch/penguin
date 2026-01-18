"""
Tests for session save synchronization fix.

These tests verify that:
1. ConversationSystem.add_message() properly syncs with SessionManager's cache
2. Auto-save correctly identifies modified sessions
3. Sessions are reliably persisted after message additions
"""

import os
import tempfile
import pytest
from pathlib import Path

from penguin.system.conversation import ConversationSystem
from penguin.system.session_manager import SessionManager
from penguin.system.state import MessageCategory


class TestSessionSaveSync:
    """Tests for session save synchronization between ConversationSystem and SessionManager."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.session_manager = SessionManager(
            base_path=self.temp_dir,
            auto_save_interval=0,  # Disable auto-save for controlled testing
        )
        self.conversation = ConversationSystem(
            session_manager=self.session_manager,
            system_prompt="Test system prompt",
        )

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_add_message_marks_session_modified_in_cache(self):
        """Test that add_message() marks the session as modified in SessionManager cache."""
        session = self.session_manager.create_session()
        self.conversation.session = session
        # Mark as modified since we're assigning session directly (mimics real creation flow)
        self.conversation._modified = True
        
        # Initially, session should be marked as modified (from creation)
        assert session.id in self.session_manager.sessions
        _, is_modified = self.session_manager.sessions[session.id]
        assert is_modified, "Session should be modified after creation"
        
        # Save to clear modified flags
        success = self.conversation.save()
        assert success, "Save should succeed"
        
        # Both flags should be cleared after save
        assert not self.conversation._modified, "ConversationSystem._modified should be False after save"
        _, is_modified = self.session_manager.sessions[session.id]
        assert not is_modified, "Session should not be modified after save"
        
        # Add a message
        self.conversation.add_message(
            role="user",
            content="Test message",
            category=MessageCategory.DIALOG,
        )
        
        # Session should now be marked as modified in cache
        _, is_modified = self.session_manager.sessions[session.id]
        assert is_modified, "Session should be modified after add_message()"
        
        # And ConversationSystem._modified should also be True
        assert self.conversation._modified, "ConversationSystem._modified should be True after add_message()"

    def test_modified_session_saved_on_explicit_save(self):
        """Test that modified session is properly saved on explicit save call."""
        session = self.session_manager.create_session()
        self.conversation.session = session
        
        # Add a message
        self.conversation.add_message(
            role="user",
            content="Persisted message",
            category=MessageCategory.DIALOG,
        )
        
        # Verify modified flag is set
        assert self.conversation._modified
        
        # Save
        success = self.conversation.save()
        assert success, "Save should succeed"
        
        # Modified flag should be cleared
        assert not self.conversation._modified
        
        # Cache should also be updated
        _, is_modified = self.session_manager.sessions[session.id]
        assert not is_modified, "Cache modified flag should be cleared after save"
        
        # Verify file exists
        session_path = Path(self.temp_dir) / f"{session.id}.json"
        assert session_path.exists(), "Session file should exist"

    def test_session_persists_across_reload(self):
        """Test that saved sessions can be reloaded with all messages."""
        # Create and populate session
        session = self.session_manager.create_session()
        self.conversation.session = session
        session_id = session.id
        
        self.conversation.add_message(
            role="user",
            content="Message 1",
            category=MessageCategory.DIALOG,
        )
        self.conversation.add_message(
            role="assistant",
            content="Response 1",
            category=MessageCategory.DIALOG,
        )
        
        # Save explicitly
        self.conversation.save()
        
        # Create new session manager and load
        new_sm = SessionManager(
            base_path=self.temp_dir,
            auto_save_interval=0,
        )
        loaded_session = new_sm.load_session(session_id)
        
        assert loaded_session is not None, "Session should be loadable"
        assert len(loaded_session.messages) == 2, "All messages should be persisted"
        assert loaded_session.messages[0].content == "Message 1"
        assert loaded_session.messages[1].content == "Response 1"

    def test_auto_save_finds_modified_sessions(self):
        """Test that _auto_save_sessions correctly identifies and saves modified sessions."""
        session = self.session_manager.create_session()
        self.conversation.session = session
        
        # Clear initial modified flag
        self.conversation.save()
        
        # Add message (should mark modified)
        self.conversation.add_message(
            role="user",
            content="Auto-save test",
            category=MessageCategory.DIALOG,
        )
        
        # Verify session is marked modified
        _, is_modified = self.session_manager.sessions[session.id]
        assert is_modified, "Session should be marked modified"
        
        # Trigger auto-save
        self.session_manager._auto_save_sessions()
        
        # Session should no longer be marked modified
        _, is_modified = self.session_manager.sessions[session.id]
        assert not is_modified, "Session should not be modified after auto-save"

    def test_new_conversation_session_is_in_cache(self):
        """Test that when ConversationSystem creates a new session, it's added to the cache.
        
        This tests the fix for the bug where sessions created via ConversationSystem.__init__
        were not added to SessionManager.sessions cache, causing mark_session_modified()
        to silently fail and preventing auto-save from working.
        """
        # Create a fresh SessionManager with no current_session
        temp_dir_2 = tempfile.mkdtemp()
        try:
            sm = SessionManager(
                base_path=temp_dir_2,
                auto_save_interval=0,
            )
            
            # Verify no current session
            assert sm.current_session is None
            
            # Create ConversationSystem - this should create a new session via create_session()
            conv = ConversationSystem(
                session_manager=sm,
                system_prompt="Test prompt",
            )
            
            # The session should now be the current_session
            assert sm.current_session is not None
            assert conv.session is sm.current_session
            
            # CRITICAL: The session should be in the cache
            assert conv.session.id in sm.sessions, \
                "Session created by ConversationSystem should be in SessionManager.sessions cache"
            
            # And it should be marked as modified (new sessions are dirty)
            _, is_modified = sm.sessions[conv.session.id]
            assert is_modified, "New session should be marked as modified"
            
            # Now add a message
            conv.add_message(
                role="user",
                content="Test message for cache verification",
                category=MessageCategory.DIALOG,
            )
            
            # Session should still be in cache and marked modified
            assert conv.session.id in sm.sessions
            _, is_modified = sm.sessions[conv.session.id]
            assert is_modified, "Session should be marked modified after add_message"
            
            # Save and verify it clears modified flag
            conv.save()
            _, is_modified = sm.sessions[conv.session.id]
            assert not is_modified, "Session should not be modified after save"
            
        finally:
            import shutil
            shutil.rmtree(temp_dir_2, ignore_errors=True)

    def test_mark_session_modified_adds_current_session_to_cache(self):
        """Test that mark_session_modified adds current_session to cache if not present.
        
        This tests the fallback behavior where if a session somehow exists as 
        current_session but is not in the cache, mark_session_modified will add it.
        """
        # Create a session directly (simulating legacy behavior)
        from penguin.system.state import Session
        direct_session = Session()
        
        # Set it as current_session but NOT in cache (old buggy state)
        self.session_manager.current_session = direct_session
        
        # Verify it's NOT in cache initially (simulating the bug)
        assert direct_session.id not in self.session_manager.sessions
        
        # Now call mark_session_modified - this should add it to cache
        self.session_manager.mark_session_modified(direct_session.id)
        
        # Session should now be in cache and marked modified
        assert direct_session.id in self.session_manager.sessions, \
            "mark_session_modified should add current_session to cache if not present"
        _, is_modified = self.session_manager.sessions[direct_session.id]
        assert is_modified, "Session should be marked as modified"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
