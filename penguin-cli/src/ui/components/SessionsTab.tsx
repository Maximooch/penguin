/**
 * Sessions Tab
 *
 * Full-screen interactive view of all conversations with keyboard navigation
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Box } from 'ink';
import { SessionPickerModal } from './SessionPickerModal.js';
import { SessionAPI } from '../../core/api/SessionAPI.js';
import { useConnection } from '../contexts/ConnectionContext.js';
import { useTab } from '../contexts/TabContext.js';
import type { Session } from '../../core/types.js';

export function SessionsTab() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const sessionAPI = useRef(new SessionAPI('http://localhost:8000'));
  const { currentConversationId, switchConversation } = useConnection();
  const { switchTab, tabs } = useTab();

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
    // Switch to selected conversation
    switchConversation(session.id)
      .then(() => {
        // Switch back to chat tab after selection
        const chatTab = tabs.find(t => t.type === 'chat');
        if (chatTab) {
          switchTab(chatTab.id);
        }
      })
      .catch((err) => {
        console.error('Error switching session:', err);
      });
  }, [switchConversation, switchTab, tabs]);

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
    // Switch back to chat tab
    const chatTab = tabs.find(t => t.type === 'chat');
    if (chatTab) {
      switchTab(chatTab.id);
    }
  }, [switchTab, tabs]);

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
