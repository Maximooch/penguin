/**
 * StatusMessage Component
 *
 * Renders system status messages (multi-line).
 */

import React from 'react';
import { Box, Text } from 'ink';
import { useTheme } from '../../theme/ThemeContext.js';
import type { StatusLine } from './types.js';

interface StatusMessageProps {
  line: StatusLine;
  contentWidth?: number;
}

export function StatusMessage({ line, contentWidth }: StatusMessageProps) {
  const { theme } = useTheme();

  return (
    <Box flexDirection="column" paddingLeft={2}>
      {line.lines.map((text, index) => (
        <Text key={index} color={theme.text.muted} dimColor wrap="wrap">
          {text}
        </Text>
      ))}
    </Box>
  );
}
