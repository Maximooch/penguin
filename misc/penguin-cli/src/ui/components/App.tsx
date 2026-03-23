/**
 * Main Penguin CLI App Component
 * Simplified: Direct ChatSession rendering (tabs deferred until multi-agent ready)
 */

import React from 'react';
import { Box } from 'ink';
import { useTab } from '../contexts/TabContext.js';
import { ChatSession } from './ChatSession.js';

export function App() {
  const { currentConversationId } = useTab();

  return (
    <Box flexDirection="column" padding={1}>
      <ChatSession conversationId={currentConversationId} />
    </Box>
  );
}
