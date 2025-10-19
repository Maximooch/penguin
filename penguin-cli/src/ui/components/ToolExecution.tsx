/**
 * Component for displaying tool/action execution
 * Shows inline status for active tools and expandable results
 */

import React, { useState } from 'react';
import { Box, Text } from 'ink';
import Spinner from 'ink-spinner';
import type { ToolCall } from '../../core/types';

interface ToolExecutionProps {
  tool: ToolCall;
  expanded?: boolean;
}

export function ToolExecution({ tool, expanded: initialExpanded = false }: ToolExecutionProps) {
  const [isExpanded, setIsExpanded] = useState(initialExpanded);

  const getStatusColor = () => {
    switch (tool.status) {
      case 'running':
      case 'pending':
        return 'yellow';
      case 'completed':
        return 'green';
      case 'error':
        return 'red';
      default:
        return 'gray';
    }
  };

  const getStatusIcon = () => {
    switch (tool.status) {
      case 'running':
        return <Spinner type="dots" />;
      case 'pending':
        return '⏳';
      case 'completed':
        return '✓';
      case 'error':
        return '✗';
      default:
        return '◦';
    }
  };

  const duration =
    tool.startTime && tool.endTime ? `${((tool.endTime - tool.startTime) / 1000).toFixed(2)}s` : '';

  // Truncate long results for inline display
  const truncateResult = (text: string, maxLength: number = 100): string => {
    if (text.length <= maxLength) return text;
    return text.slice(0, maxLength) + '...';
  };

  const hasLongResult = (tool.result && tool.result.length > 100) || (tool.error && tool.error.length > 100);
  const resultText = tool.result || tool.error || '';
  const displayResult = isExpanded ? resultText : truncateResult(resultText);

  return (
    <Box flexDirection="column" marginLeft={2} marginY={0}>
      {/* Tool header */}
      <Box>
        <Box marginRight={1}>
          <Text color={getStatusColor()}>{getStatusIcon()}</Text>
        </Box>
        <Text color={getStatusColor()} bold>
          {tool.action}
        </Text>
        {duration && (
          <Text color="gray" dimColor>
            {' '}
            ({duration})
          </Text>
        )}
      </Box>

      {/* Tool result/error */}
      {(tool.result || tool.error) && (
        <Box flexDirection="column" marginLeft={2} marginTop={0}>
          <Box>
            <Text color={tool.error ? 'red' : 'gray'} dimColor>
              {displayResult}
            </Text>
          </Box>

          {/* Expand/collapse toggle for long results */}
          {hasLongResult && (
            <Box marginTop={0}>
              <Text color="blue" dimColor>
                {isExpanded ? '▼ Show less (press Space to toggle)' : '▶ Show more (press Space to toggle)'}
              </Text>
            </Box>
          )}
        </Box>
      )}
    </Box>
  );
}

interface ToolExecutionListProps {
  tools: ToolCall[];
  showActive?: boolean;
}

export function ToolExecutionList({ tools, showActive = true }: ToolExecutionListProps) {
  if (tools.length === 0) return null;

  return (
    <Box flexDirection="column" marginY={0}>
      {tools
        .filter((tool) => !showActive || tool.status === 'running' || tool.status === 'completed' || tool.status === 'error')
        .map((tool) => (
          <ToolExecution key={tool.id} tool={tool} />
        ))}
    </Box>
  );
}
