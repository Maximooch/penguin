/**
 * Main Penguin CLI App Component
 * Phase 1: Basic chat interface with streaming support
 *
 * REFACTORED: No longer passes props - uses contexts instead
 */

import React from 'react';
import { Box, Text } from 'ink';
import { ChatSession } from './ChatSession';

export function App() {
  return (
    <Box flexDirection="column" padding={1}>
      <Box marginBottom={1}>
        <Text bold color="cyan">
          🐧 Penguin AI - TypeScript CLI (Ink)
        </Text>
      </Box>

      <ChatSession />
    </Box>
  );
}
