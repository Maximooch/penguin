/**
 * AssistantMessage Component
 *
 * Renders assistant output with "🐧 Penguin:" prefix and markdown support.
 * Supports streaming and finished phases.
 */

import React from 'react';
import { Box, Text } from 'ink';
import { useTheme } from '../../theme/ThemeContext.js';
import { Markdown } from '../Markdown.js';
import type { AssistantLine } from './types.js';

interface AssistantMessageProps {
  line: AssistantLine;
  contentWidth?: number;
}

export function AssistantMessage({ line, contentWidth }: AssistantMessageProps) {
  const { theme } = useTheme();
  const isStreaming = line.phase === 'streaming';

  // Show streaming cursor when content is arriving
  const displayText = isStreaming ? line.text + '▋' : line.text;

  return (
    <Box flexDirection="column" marginTop={1}>
      {/* Role label - Penguin branding */}
      <Text bold color={theme.status.info}>🐧 Penguin:</Text>

      {/* Message content - indented with markdown */}
      <Box paddingLeft={2} flexDirection="column" width={contentWidth}>
        {line.text ? (
          <Markdown content={displayText} />
        ) : isStreaming ? (
          <Text color={theme.text.muted}>▋</Text>
        ) : null}
      </Box>
    </Box>
  );
}
