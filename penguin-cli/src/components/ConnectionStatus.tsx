/**
 * Connection status indicator
 * Shows connection state and errors
 */

import React from 'react';
import { Box, Text } from 'ink';

export interface ConnectionStatusProps {
  isConnected: boolean;
  error: Error | null;
}

export function ConnectionStatus({ isConnected, error }: ConnectionStatusProps) {
  // Only show status when there's an error or connecting
  // Once connected, hide to reduce clutter
  if (error) {
    return (
      <Box borderStyle="round" borderColor="red" padding={1} marginBottom={1}>
        <Text color="red">
          ❌ Error: {error.message}
        </Text>
      </Box>
    );
  }

  if (!isConnected) {
    return (
      <Box borderStyle="round" borderColor="yellow" padding={1} marginBottom={1}>
        <Text color="yellow">
          ⏳ Connecting to Penguin backend...
        </Text>
      </Box>
    );
  }

  // Connected - don't show anything
  return null;
}
