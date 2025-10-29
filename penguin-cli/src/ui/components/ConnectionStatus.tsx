/**
 * Connection status indicator
 * Shows connection state and errors
 */

import React from 'react';
import { Box, Text } from 'ink';

export interface ConnectionStatusProps {
  isConnected: boolean;
  error: Error | null;
  workspace?: string;
  showWorkspace?: boolean;
}

export function ConnectionStatus({ isConnected, error, workspace, showWorkspace = false }: ConnectionStatusProps) {
  // Show workspace info bar when connected (if enabled)
  if (isConnected && showWorkspace && workspace) {
    return (
      <Box borderStyle="single" borderColor="green" paddingX={1} marginBottom={1}>
        <Text color="green">✓ Connected</Text>
        <Text dimColor> • </Text>
        <Text dimColor>📁 {workspace}</Text>
      </Box>
    );
  }

  // Show error
  if (error) {
    const anyErr = error as any;
    const code = anyErr?.code as string | undefined;
    // Helpful fallback message when Node's AggregateError has empty message
    const message = error.message && error.message.trim().length > 0
      ? error.message
      : code === 'ECONNREFUSED'
        ? 'Unable to connect to Penguin server at http://localhost:8000. Start it with: uv run penguin-web'
        : 'Connection error. Is the Penguin server running?';
    return (
      <Box borderStyle="round" borderColor="red" padding={1} marginBottom={1}>
        <Text color="red">
          ❌ Error: {message}
        </Text>
      </Box>
    );
  }

  // Show connecting status
  if (!isConnected) {
    return (
      <Box borderStyle="round" borderColor="yellow" padding={1} marginBottom={1}>
        <Text color="yellow">
          ⏳ Connecting to Penguin backend...
        </Text>
      </Box>
    );
  }

  // Connected - don't show anything by default
  return null;
}
