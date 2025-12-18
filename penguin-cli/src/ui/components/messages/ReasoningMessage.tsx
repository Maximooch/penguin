/**
 * ReasoningMessage Component
 *
 * Renders internal reasoning/thinking text with "💭 Internal Reasoning" header.
 * Can be collapsed/expanded by user preference.
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

  return (
    <Box flexDirection="column" paddingLeft={2} marginTop={1}>
      {/* Header - collapsible indicator */}
      <Text color={theme.text.muted}>💭 Internal Reasoning</Text>

      {/* Reasoning content - indented and dimmed */}
      <Box paddingLeft={2} width={contentWidth}>
        <Text color={theme.text.muted} dimColor wrap="wrap">
          {displayText || (isStreaming ? '▋' : '')}
        </Text>
      </Box>
    </Box>
  );
}
