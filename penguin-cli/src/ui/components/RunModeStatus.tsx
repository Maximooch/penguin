/**
 * RunMode Status Display Component
 *
 * Shows real-time status of autonomous task execution
 */

import React from 'react';
import { Box, Text } from 'ink';
import type { RunModeStatus as RunStatus } from '../../core/api/RunAPI.js';

interface RunModeStatusProps {
  status: RunStatus;
  currentMessage?: string;
  progress?: number;
}

export function RunModeStatus({ status, currentMessage, progress }: RunModeStatusProps) {
  const getStatusColor = (state: string) => {
    switch (state) {
      case 'running':
        return 'green';
      case 'stopped':
        return 'red';
      case 'idle':
      default:
        return 'yellow';
    }
  };

  const getStatusIcon = (state: string) => {
    switch (state) {
      case 'running':
        return '▶';
      case 'stopped':
        return '■';
      case 'idle':
      default:
        return '○';
    }
  };

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor={getStatusColor(status.status)}
      paddingX={1}
      paddingY={1}
      width="100%"
    >
      <Box marginBottom={1}>
        <Text bold color={getStatusColor(status.status)}>
          {getStatusIcon(status.status)} RunMode: {status.status.toUpperCase()}
        </Text>
      </Box>

      {status.current_task && (
        <Box marginBottom={1}>
          <Text dimColor>Task: </Text>
          <Text color="cyan">{status.current_task}</Text>
        </Box>
      )}

      {status.task_id && (
        <Box marginBottom={1}>
          <Text dimColor>Task ID: </Text>
          <Text color="gray">{status.task_id.slice(0, 8)}</Text>
        </Box>
      )}

      {status.start_time && (
        <Box marginBottom={1}>
          <Text dimColor>Started: </Text>
          <Text>{new Date(status.start_time).toLocaleTimeString()}</Text>
        </Box>
      )}

      {progress !== undefined && progress >= 0 && (
        <Box marginBottom={1}>
          <Text dimColor>Progress: </Text>
          <Text color="cyan">{Math.round(progress)}%</Text>
          <Box marginLeft={1}>
            <Text color="cyan">{'█'.repeat(Math.floor(progress / 5))}</Text>
            <Text dimColor>{'░'.repeat(20 - Math.floor(progress / 5))}</Text>
          </Box>
        </Box>
      )}

      {currentMessage && (
        <Box marginTop={1} flexDirection="column">
          <Text dimColor>Latest:</Text>
          <Box paddingLeft={2}>
            <Text>{currentMessage}</Text>
          </Box>
        </Box>
      )}

      <Box marginTop={1}>
        <Text dimColor>Press Ctrl+C or use /run stop to halt execution</Text>
      </Box>
    </Box>
  );
}
