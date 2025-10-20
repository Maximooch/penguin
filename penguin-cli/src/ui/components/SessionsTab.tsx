/**
 * Sessions Tab
 *
 * Full-screen interactive view of all conversations with keyboard navigation
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Box } from 'ink';
import { SessionPickerModal } from './SessionPickerModal.js';
import { SessionAPI } from '../../core/api/SessionAPI.js';
import { useTab } from '../contexts/TabContext.js';
import type { Session } from '../../core/types.js';

export function SessionsTab() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const sessionAPI = useRef(new SessionAPI('http://localhost:8000'));
  const { openChatTab, prevTab, activeTab } = useTab();

  useEffect(() => {
    // Load sessions when tab mounts
    sessionAPI.current
      .listSessions()
      .then((sessionList) => {
        setSessions(sessionList);
        setIsLoading(false);
      })
      .catch((err) => {
        console.error('Failed to load sessions:', err);
        setIsLoading(false);
      });
  }, []);

  const handleSessionSelect = useCallback((session: Session) => {
    // Open or switch to chat tab for this conversation
    openChatTab(session.id, session.title || `Chat ${session.id.slice(0, 8)}`);
  }, [openChatTab]);

  const handleSessionDelete = useCallback((sessionId: string) => {
    sessionAPI.current
      .deleteSession(sessionId)
      .then(() => {
        // Refresh session list
        return sessionAPI.current.listSessions();
      })
      .then((sessionList) => {
        setSessions(sessionList);
      })
      .catch((err) => {
        console.error('Failed to delete session:', err);
      });
  }, []);

  const handleClose = useCallback(() => {
    // Use Ctrl+P functionality to go to previous tab
    prevTab();
  }, [prevTab]);

  // Get current conversation ID from active chat tab
  const currentConversationId = activeTab?.type === 'chat' ? activeTab.conversationId : undefined;

  return (
    <Box flexDirection="column" width="100%" height="100%">
      <SessionPickerModal
        sessions={sessions}
        currentSessionId={currentConversationId}
        onSelect={handleSessionSelect}
        onDelete={handleSessionDelete}
        onClose={handleClose}
        isLoading={isLoading}
      />
    </Box>
  );
}
