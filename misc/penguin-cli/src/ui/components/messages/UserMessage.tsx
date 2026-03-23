/**
 * UserMessage Component
 *
 * Renders user input with ">" prefix.
 * Always "finished" - no streaming state.
 */

import React from 'react';
import { Box, Text } from 'ink';
import { useTheme } from '../../theme/ThemeContext.js';
import type { UserLine } from './types.js';

interface UserMessageProps {
  line: UserLine;
  contentWidth?: number;
}

export function UserMessage({ line, contentWidth }: UserMessageProps) {
  const { theme } = useTheme();

  // User messages get a small top margin for visual separation from assistant output
  return (
    <Box flexDirection="row" marginTop={1}>
      <Text color={theme.brand.primary} bold>{'❯ '}</Text>
      <Text color={theme.text.primary} wrap="wrap">
        {line.text}
      </Text>
    </Box>
  );
}
