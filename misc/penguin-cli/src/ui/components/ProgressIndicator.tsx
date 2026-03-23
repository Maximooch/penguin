/**
 * Progress indicator for multi-step reasoning/execution
 * Shows current iteration and progress bar
 */

import React from 'react';
import { Box, Text } from 'ink';
import Spinner from 'ink-spinner';

interface ProgressIndicatorProps {
  iteration: number;
  maxIterations: number;
  message?: string;
  isActive?: boolean;
}

export function ProgressIndicator({
  iteration,
  maxIterations,
  message,
  isActive = true,
}: ProgressIndicatorProps) {
  const percentage = Math.round((iteration / maxIterations) * 100);
  const barLength = 20;
  const filledLength = Math.round((iteration / maxIterations) * barLength);
  const progressBar = '█'.repeat(filledLength) + '░'.repeat(barLength - filledLength);

  return (
    <Box flexDirection="column" marginY={0}>
      <Box>
        {isActive && (
          <Box marginRight={1}>
            <Text color="yellow">
              <Spinner type="dots" />
            </Text>
          </Box>
        )}
        <Text color="yellow">
          Step {iteration}/{maxIterations}
        </Text>
        <Text color="gray" dimColor>
          {' '}
          ({percentage}%)
        </Text>
      </Box>

      {/* Progress bar */}
      <Box marginLeft={isActive ? 2 : 0}>
        <Text color="yellow">{progressBar}</Text>
      </Box>

      {/* Optional message */}
      {message && (
        <Box marginLeft={isActive ? 2 : 0}>
          <Text color="gray" dimColor>
            {message}
          </Text>
        </Box>
      )}
    </Box>
  );
}
