/**
 * ReasoningMessage Component
 *
 * Renders internal reasoning/thinking text in a bordered collapsible box.
 * Toggle visibility with 'r' hotkey.
 */

import React from 'react';
import { Box, Text } from 'ink';
import { useTheme } from '../../theme/ThemeContext.js';
import type { ReasoningLine } from './types.js';

interface ReasoningMessageProps {
  line: ReasoningLine;
  contentWidth?: number;
  visible?: boolean;
}

export function ReasoningMessage({ line, contentWidth, visible = true }: ReasoningMessageProps) {
  const { theme } = useTheme();
  const isStreaming = line.phase === 'streaming';

  // Don't render if reasoning is hidden
  if (!visible) {
    return null;
  }

  // Show streaming cursor when content is arriving
  const displayText = isStreaming ? line.text + '▋' : line.text;

  // Don't render empty reasoning
  if (!line.text && !isStreaming) {
    return null;
  }

  // Calculate box width - use contentWidth or default
  const boxWidth = contentWidth ? Math.min(contentWidth, 100) : 80;

  return (
    <Box flexDirection="column" marginY={0}>
      {/* Bordered reasoning box like the screenshot */}
      <Box
        flexDirection="column"
        borderStyle="round"
        borderColor={theme.text.muted}
        paddingX={1}
        paddingY={0}
        width={boxWidth}
      >
        {/* Header */}
        <Text color={theme.text.muted} dimColor>
          💭 Internal Reasoning
        </Text>

        {/* Content - dimmed and wrapped */}
        <Box marginTop={0}>
          <Text color={theme.text.muted} dimColor wrap="wrap">
            {displayText || (isStreaming ? '▋' : '')}
          </Text>
        </Box>
      </Box>
    </Box>
  );
}
