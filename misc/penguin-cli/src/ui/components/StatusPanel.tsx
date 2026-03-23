import React from 'react';
import { Box, Text } from 'ink';
import { useTheme } from '../theme/ThemeContext.js';

interface StatusPanelProps {
  isConnected: boolean;
  error: Error | null;
  activeTool?: { action: string; status: string } | null;
  progress?: { iteration: number; maxIterations: number; message?: string; isActive: boolean };
}

export function StatusPanel({ isConnected, error }: StatusPanelProps) {
  const { theme: tokens } = useTheme();

  // Only show status when there's an issue (not connected or error)
  if (isConnected && !error) {
    return null;
  }

  return (
    <Box>
      <Text color={error ? tokens.status.error : tokens.status.warning}>
        {error ? '✗ ' : '⏳ '}
      </Text>
      <Text color={tokens.text.muted}>
        {error ? (error.message?.trim() || 'Connection error') : 'Connecting…'}
      </Text>
    </Box>
  );
}
