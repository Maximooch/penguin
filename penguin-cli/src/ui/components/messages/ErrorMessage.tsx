/**
 * ErrorMessage Component
 *
 * Renders error messages with prominent red styling.
 */

import React from 'react';
import { Box, Text } from 'ink';
import { useTheme } from '../../theme/ThemeContext.js';
import type { ErrorLine } from './types.js';

interface ErrorMessageProps {
  line: ErrorLine;
  contentWidth?: number;
}

export function ErrorMessage({ line, contentWidth }: ErrorMessageProps) {
  const { theme } = useTheme();

  // Compact error display
  return (
    <Box flexDirection="column">
      <Text color={theme.status.error}>
        <Text bold>✗ </Text>
        <Text wrap="wrap">{line.text}</Text>
      </Text>
    </Box>
  );
}
