/**
 * ChatMessageArea Component
 *
 * Main transcript display area using Ink's Static pattern for performance.
 *
 * Key insight from claude-code issue #769:
 * - Static items are rendered ONCE and never re-render (frozen history)
 * - Dynamic items re-render normally (in-flight content)
 * - This prevents full buffer redraws that cause terminal flickering
 *
 * Pattern:
 * <Static items={staticItems}>  // Finished messages - frozen
 *   {renderItem}
 * </Static>
 * {dynamicItems.map(...)}       // In-flight messages - re-render
 */

import React, { useMemo, useEffect, useRef } from 'react';
import { Box, Static } from 'ink';
import { useTerminalWidth } from '../hooks/useTerminalWidth.js';
import type { Line, StaticItem } from '../../core/accumulator/types.js';
import {
  WelcomeMessage,
  UserMessage,
  AssistantMessage,
  ToolCallMessage,
  ReasoningMessage,
  ErrorMessage,
  StatusMessage,
  SeparatorMessage,
  GUTTER_WIDTH,
} from './messages/index.js';

/** ANSI escape to clear screen and move cursor home - prevents wrapped text artifacts on resize */
const CLEAR_SCREEN_AND_HOME = '\u001B[2J\u001B[H';

interface ChatMessageAreaProps {
  /** Frozen history items (never change after commit) */
  staticItems: StaticItem[];
  /** In-flight items (may change during streaming) */
  dynamicItems: Line[];
  /** Whether to show reasoning/thinking blocks */
  showReasoning?: boolean;
  /** Whether tool calls should be expanded */
  expandedToolCalls?: boolean;
}

/**
 * Render a single line item to the appropriate component
 */
function renderLine(
  line: Line,
  contentWidth: number,
  showReasoning: boolean,
  expandedToolCalls: boolean,
): React.ReactNode {
  switch (line.kind) {
    case 'welcome':
      return <WelcomeMessage line={line} contentWidth={contentWidth} />;

    case 'user':
      return <UserMessage line={line} contentWidth={contentWidth} />;

    case 'assistant':
      return <AssistantMessage line={line} contentWidth={contentWidth} />;

    case 'tool_call':
      return (
        <ToolCallMessage
          line={line}
          contentWidth={contentWidth}
          expanded={expandedToolCalls}
        />
      );

    case 'reasoning':
      return (
        <ReasoningMessage
          line={line}
          contentWidth={contentWidth}
          visible={showReasoning}
        />
      );

    case 'error':
      return <ErrorMessage line={line} contentWidth={contentWidth} />;

    case 'status':
      return <StatusMessage line={line} contentWidth={contentWidth} />;

    case 'separator':
      return <SeparatorMessage line={line} contentWidth={contentWidth} />;

    default:
      // Type safety: exhaustive check
      const _exhaustive: never = line;
      return null;
  }
}


/**
 * ChatMessageArea - Main transcript display
 *
 * Uses Static for frozen history to prevent terminal flickering (claude-code #769).
 * Dynamic items re-render normally during streaming.
 *
 * CRITICAL: Static must NOT have a key prop - that defeats the entire purpose!
 * Static is designed to render items once and never re-render them.
 */
export function ChatMessageArea({
  staticItems,
  dynamicItems,
  showReasoning = true,
  expandedToolCalls = false,
}: ChatMessageAreaProps) {
  const columns = useTerminalWidth();
  const contentWidth = Math.max(40, columns - GUTTER_WIDTH - 4);

  // Track terminal width for screen clearing on shrink
  const prevColumnsRef = useRef(columns);

  // Handle terminal resize - clear screen on shrink to prevent artifacts
  useEffect(() => {
    const prev = prevColumnsRef.current;
    if (columns === prev) return;

    // Clear screen when terminal shrinks (prevents wrapped text leftovers)
    if (
      columns < prev &&
      typeof process !== 'undefined' &&
      process.stdout &&
      'write' in process.stdout &&
      (process.stdout as NodeJS.WriteStream).isTTY
    ) {
      (process.stdout as NodeJS.WriteStream).write(CLEAR_SCREEN_AND_HOME);
    }

    prevColumnsRef.current = columns;
  }, [columns]);

  // Render function for Static items
  const renderStaticItem = useMemo(
    () => (item: StaticItem, index: number) => (
      <Box key={item.id} marginTop={index > 0 ? 0 : 0}>
        {renderLine(item, contentWidth, showReasoning, expandedToolCalls)}
      </Box>
    ),
    [contentWidth, showReasoning, expandedToolCalls]
  );

  return (
    <Box flexDirection="column" flexGrow={1}>
      {/* Static section: Frozen history - items render ONCE and never re-render */}
      <Static items={staticItems}>
        {renderStaticItem}
      </Static>

      {/* Dynamic section: In-flight content - re-renders on changes */}
      {dynamicItems.length > 0 && (
        <Box flexDirection="column">
          {dynamicItems.map((line) => (
            <Box key={line.id}>
              {renderLine(line, contentWidth, showReasoning, expandedToolCalls)}
            </Box>
          ))}
        </Box>
      )}
    </Box>
  );
}

export default ChatMessageArea;
