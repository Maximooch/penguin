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
    return (
      <Box borderStyle="round" borderColor="red" padding={1} marginBottom={1}>
        <Text color="red">
          ❌ Error: {error.message}
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
