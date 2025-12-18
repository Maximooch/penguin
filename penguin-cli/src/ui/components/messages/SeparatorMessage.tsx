/**
 * SeparatorMessage Component
 *
 * Renders a visual separator between conversation turns.
 */

import React from 'react';
import { Box, Text } from 'ink';
import { useTheme } from '../../theme/ThemeContext.js';
import type { SeparatorLine } from './types.js';

interface SeparatorMessageProps {
  line: SeparatorLine;
  contentWidth?: number;
}

export function SeparatorMessage({ line, contentWidth }: SeparatorMessageProps) {
  const { theme } = useTheme();

  // Create a separator line of appropriate width
  const separatorChar = '─';
  const separatorWidth = Math.max(20, contentWidth || 60);
  const separatorLine = separatorChar.repeat(separatorWidth);

  return (
    <Box marginY={1}>
      <Text color={theme.border.default}>{separatorLine}</Text>
    </Box>
  );
}
