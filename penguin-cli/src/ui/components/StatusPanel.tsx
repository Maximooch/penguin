import React from 'react';
import { Box, Text } from 'ink';
import { Panel } from './Panel.js';
import { useTheme } from '../theme/ThemeContext.js';

interface StatusPanelProps {
  isConnected: boolean;
  error: Error | null;
  activeTool?: { action: string; status: string } | null;
  progress?: { iteration: number; maxIterations: number; message?: string; isActive: boolean };
}

export function StatusPanel({ isConnected, error, activeTool, progress }: StatusPanelProps) {
  const { theme: tokens } = useTheme();
  return (
    <Panel title="Status" borderColor={error ? tokens.status.error : isConnected ? tokens.status.success : tokens.status.warning}>
      {/* Connection */}
      <Box>
        <Text color={isConnected ? tokens.status.success : error ? tokens.status.error : tokens.status.warning}>
          {isConnected ? '●' : error ? '✗' : '⏳'}
        </Text>
        <Text>{' '}</Text>
        <Text color={tokens.text.primary}>
          {isConnected ? 'Connected' : error ? (error.message?.trim() || 'Connection error') : 'Connecting…'}
        </Text>
      </Box>

      {/* Progress */}
      <Box marginTop={1}>
        {progress?.isActive && progress.maxIterations > 1 ? (
          <Text color={tokens.status.warning}>
            Step {progress.iteration}/{progress.maxIterations} — {progress.message || 'Working…'}
          </Text>
        ) : (
          <Text color={tokens.text.secondary} dimColor>
            No active progress
          </Text>
        )}
      </Box>

      {/* Active tool */}
      <Box marginTop={1}>
        {activeTool ? (
          <Text color={activeTool.status === 'running' ? tokens.status.warning : tokens.status.success}>
            {activeTool.status === 'running' ? 'Running tool: ' : 'Last tool: '}
            <Text bold>{activeTool.action}</Text>
          </Text>
        ) : (
          <Text color={tokens.text.secondary} dimColor>
            No active tool
          </Text>
        )}
      </Box>
    </Panel>
  );
}
