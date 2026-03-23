/**
 * Session List Component
 *
 * Displays a table of conversation sessions with title, message count, and last active time.
 */

import React from 'react';
import { Box, Text } from 'ink';
import type { Session } from '../../core/types.js';

interface SessionListProps {
  sessions: Session[];
  currentSessionId?: string;
}

export function SessionList({ sessions, currentSessionId }: SessionListProps) {
  if (sessions.length === 0) {
    return (
      <Box flexDirection="column" paddingY={1}>
        <Text dimColor>No conversations found.</Text>
      </Box>
    );
  }

  // Sort sessions by last_active (most recent first)
  const sortedSessions = [...sessions].sort((a, b) => {
    const aTime = a.last_active || a.updatedAt?.toString() || '0';
    const bTime = b.last_active || b.updatedAt?.toString() || '0';
    return bTime.localeCompare(aTime);
  });

  return (
    <Box flexDirection="column" paddingY={1}>
      <Box>
        <Text bold color="cyan">
          📋 Conversations ({sessions.length})
        </Text>
      </Box>

      {/* Table header */}
      <Box marginTop={1}>
        <Box width={12}>
          <Text bold dimColor>
            ID
          </Text>
        </Box>
        <Box width={50}>
          <Text bold dimColor>
            Title
          </Text>
        </Box>
        <Box width={10}>
          <Text bold dimColor>
            Messages
          </Text>
        </Box>
        <Box width={20}>
          <Text bold dimColor>
            Last Active
          </Text>
        </Box>
      </Box>

      {/* Divider */}
      <Box>
        <Text dimColor>{'─'.repeat(92)}</Text>
      </Box>

      {/* Session rows */}
      {sortedSessions.map((session) => {
        const isCurrent = session.id === currentSessionId;
        const shortId = session.id.slice(0, 8);
        const title = session.title || `Conversation ${shortId}`;
        const messageCount = session.message_count ?? 0;
        const lastActive = session.last_active || 'Unknown';

        return (
          <Box key={session.id}>
            <Box width={12}>
              <Text color={isCurrent ? 'green' : 'white'}>
                {isCurrent && '▶ '}
                {shortId}
              </Text>
            </Box>
            <Box width={50}>
              <Text color={isCurrent ? 'green' : 'white'}>
                {title.length > 47 ? title.slice(0, 44) + '...' : title}
              </Text>
            </Box>
            <Box width={10}>
              <Text dimColor>{messageCount}</Text>
            </Box>
            <Box width={20}>
              <Text dimColor>{lastActive}</Text>
            </Box>
          </Box>
        );
      })}

      {/* Footer help */}
      <Box marginTop={1}>
        <Text dimColor>
          Use `/chat load {'<id>'}` to switch sessions • `/chat delete {'<id>'}` to delete
        </Text>
      </Box>
    </Box>
  );
}
