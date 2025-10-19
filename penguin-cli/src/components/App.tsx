/**
 * Main Penguin CLI App Component
 * Phase 1: Basic chat interface with streaming support
 */

import React from 'react';
import { Box, Text } from 'ink';
import { ChatSession } from './ChatSession';

export interface AppProps {
  conversationId?: string;
  agentId?: string;
}

export function App({ conversationId, agentId }: AppProps) {
  return (
    <Box flexDirection="column" padding={1}>
      <Box marginBottom={1}>
        <Text bold color="cyan">
          🐧 Penguin AI - TypeScript CLI (Ink)
        </Text>
      </Box>

      <ChatSession conversationId={conversationId} agentId={agentId} />
    </Box>
  );
}
