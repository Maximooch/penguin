/**
 * Session Picker Modal
 *
 * Interactive modal for selecting and loading conversation sessions.
 * Features:
 * - Arrow key navigation
 * - Search/filter
 * - Delete sessions with confirmation
 * - Esc to close
 */

import React, { useState, useEffect } from 'react';
import { Box, Text, useInput } from 'ink';
import type { Session } from '../../core/types.js';

interface SessionPickerModalProps {
  sessions: Session[];
  currentSessionId?: string;
  onSelect: (session: Session) => void;
  onDelete: (sessionId: string) => void;
  onClose: () => void;
  isLoading?: boolean;
}

export function SessionPickerModal({
  sessions,
  currentSessionId,
  onSelect,
  onDelete,
  onClose,
  isLoading = false,
}: SessionPickerModalProps) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);

  // Use all sessions (no filtering)
  const filteredSessions = sessions;

  // Keyboard navigation
  useInput((input, key) => {
    // Escape closes modal or cancels delete confirmation
    if (key.escape) {
      if (deleteConfirmId) {
        setDeleteConfirmId(null);
      } else {
        onClose();
      }
      return;
    }

    // If in delete confirmation mode
    if (deleteConfirmId) {
      if (input === 'y' || input === 'Y') {
        onDelete(deleteConfirmId);
        setDeleteConfirmId(null);
      } else if (input === 'n' || input === 'N') {
        setDeleteConfirmId(null);
      }
      return;
    }

    // Arrow key navigation
    if (key.upArrow) {
      setSelectedIndex((prev) => Math.max(0, prev - 1));
    } else if (key.downArrow) {
      setSelectedIndex((prev) => Math.min(filteredSessions.length - 1, prev + 1));
    }
    // Enter to select
    else if (key.return) {
      if (filteredSessions[selectedIndex]) {
        onSelect(filteredSessions[selectedIndex]);
      }
    }
    // 'd' key to delete session
    else if (input === 'd' || input === 'D') {
      if (filteredSessions[selectedIndex]) {
        setDeleteConfirmId(filteredSessions[selectedIndex].id);
      }
    }
  });

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor="cyan"
      paddingX={2}
      paddingY={1}
      width="90%"
    >
      {/* Header */}
      <Box marginBottom={1} justifyContent="space-between">
        <Text bold color="cyan">
          📂 Conversations
        </Text>
        <Text dimColor>
          {sessions.length} total
        </Text>
      </Box>

      {/* Delete confirmation banner */}
      {deleteConfirmId && (
        <Box marginBottom={1} borderStyle="bold" borderColor="red" paddingX={2} paddingY={0}>
          <Text color="red" bold>
            ⚠️  Delete "{filteredSessions.find(s => s.id === deleteConfirmId)?.title?.slice(0, 30) || deleteConfirmId.slice(0, 8)}"?
          </Text>
          <Text dimColor> (y/n)</Text>
        </Box>
      )}

      {/* Column headers */}
      <Box marginBottom={0} paddingX={1}>
        <Box width={45}>
          <Text bold dimColor>Title</Text>
        </Box>
        <Box width={12}>
          <Text bold dimColor>Messages</Text>
        </Box>
        <Box width={20}>
          <Text bold dimColor>Last Active</Text>
        </Box>
      </Box>

      {/* Divider */}
      <Box marginBottom={1}>
        <Text dimColor>{'─'.repeat(80)}</Text>
      </Box>

      {/* Session list */}
      <Box flexDirection="column" marginBottom={1} height={10}>
        {isLoading ? (
          <Box paddingX={1}>
            <Text dimColor>⏳ Loading sessions...</Text>
          </Box>
        ) : filteredSessions.length === 0 ? (
          <Box paddingX={1}>
            <Text dimColor>No sessions found. Press Esc to close.</Text>
          </Box>
        ) : (
          filteredSessions.slice(0, 10).map((session, index) => {
            const isSelected = index === selectedIndex;
            const isCurrent = session.id === currentSessionId;
            const title = session.title || `Session ${session.id.slice(0, 8)}`;
            const messageCount = session.message_count || 0;
            const lastActive = session.last_active || 'Unknown';

            // Truncate title to fit
            const displayTitle = title.length > 42 ? title.slice(0, 39) + '...' : title;

            return (
              <Box
                key={session.id}
                paddingX={1}
              >
                <Box width={2}>
                  <Text color={isSelected ? 'cyan' : 'gray'} bold={isSelected}>
                    {isSelected ? '▶' : ' '}
                  </Text>
                </Box>
                <Box width={2}>
                  <Text color={isCurrent ? 'green' : 'gray'}>
                    {isCurrent ? '●' : ' '}
                  </Text>
                </Box>
                <Box width={42}>
                  <Text
                    color={isSelected ? 'cyan' : isCurrent ? 'green' : undefined}
                    bold={isSelected}
                    inverse={isSelected}
                  >
                    {displayTitle}
                  </Text>
                </Box>
                <Box width={12}>
                  <Text color={isSelected ? 'cyan' : undefined} dimColor={!isSelected} inverse={isSelected}>
                    {messageCount} msg{messageCount !== 1 ? 's' : ''}
                  </Text>
                </Box>
                <Box width={20}>
                  <Text color={isSelected ? 'cyan' : undefined} dimColor={!isSelected} inverse={isSelected}>
                    {lastActive}
                  </Text>
                </Box>
              </Box>
            );
          })
        )}
      </Box>

      {/* Footer help */}
      <Box borderStyle="single" borderColor="gray" paddingX={1} marginTop={1}>
        <Text dimColor>
          ↑/↓ Navigate  •  Enter Select  •  D Delete  •  Esc Close
        </Text>
      </Box>
    </Box>
  );
}
