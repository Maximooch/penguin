/**
 * ToolCallMessage Component
 *
 * Renders tool calls with phase-based indicators and collapsible args/results.
 * Phases: streaming → ready → running → finished
 */

import React from 'react';
import { Box, Text } from 'ink';
import { useTheme } from '../../theme/ThemeContext.js';
import type { ToolCallLine, ToolPhase } from './types.js';

interface ToolCallMessageProps {
  line: ToolCallLine;
  contentWidth?: number;
  expanded?: boolean;
}

/**
 * Get phase indicator and color based on tool state
 */
function getPhaseInfo(phase: ToolPhase, theme: any, resultOk?: boolean): { indicator: string; color: string; label: string } {
  switch (phase) {
    case 'streaming':
      return { indicator: '⋯', color: theme.text.muted, label: 'parsing' };
    case 'ready':
      return { indicator: '?', color: theme.status.warning, label: 'awaiting approval' };
    case 'running':
      return { indicator: '⏳', color: theme.status.info, label: 'running' };
    case 'finished':
      return resultOk === false
        ? { indicator: '✗', color: theme.status.error, label: 'failed' }
        : { indicator: '✓', color: theme.status.success, label: 'done' };
  }
}

export function ToolCallMessage({ line, contentWidth, expanded = false }: ToolCallMessageProps) {
  const { theme } = useTheme();
  const { indicator, color, label } = getPhaseInfo(line.phase, theme, line.resultOk);

  // Truncate tool name if needed
  const toolName = line.name || 'tool';
  const maxNameLength = 40;
  const displayName = toolName.length > maxNameLength
    ? toolName.slice(0, maxNameLength - 3) + '...'
    : toolName;

  // Compact single-line format like letta-code
  return (
    <Box flexDirection="column">
      {/* Tool header - compact, dimmed */}
      <Text dimColor>
        <Text color={color}>{indicator}</Text>
        <Text> {displayName}</Text>
        {line.phase !== 'finished' && <Text color={theme.text.muted}> {label}</Text>}
      </Text>

      {/* Only show result on error (collapsed by default) */}
      {line.phase === 'finished' && line.resultOk === false && line.resultText && (
        <Text color={theme.status.error} dimColor>
          ⎿ {formatResult(line.resultText, false)}
        </Text>
      )}

      {/* Show args/result if explicitly expanded */}
      {expanded && line.argsText && (
        <Text dimColor>  args: {formatArgs(line.argsText).slice(0, 100)}</Text>
      )}
      {expanded && line.phase === 'finished' && line.resultText && line.resultOk !== false && (
        <Text dimColor>  ⎿ {formatResult(line.resultText, true)}</Text>
      )}
    </Box>
  );
}

/**
 * Format tool arguments for display
 */
function formatArgs(argsText: string): string {
  try {
    // Try to parse and pretty-print JSON
    const parsed = JSON.parse(argsText);
    return JSON.stringify(parsed, null, 2);
  } catch {
    // Return as-is if not valid JSON
    return argsText;
  }
}

/**
 * Format tool result for display
 */
function formatResult(resultText: string, ok?: boolean): string {
  const prefix = ok === false ? '✗ ' : '→ ';

  // Truncate long results
  const maxLength = 500;
  if (resultText.length > maxLength) {
    return prefix + resultText.slice(0, maxLength) + '... (truncated)';
  }

  return prefix + resultText;
}
