import React from 'react';
import { Box, Text, Static } from 'ink';
import type { Message, ToolEventNormalized, TimelineEvent } from '../../core/types';
import { Markdown } from './Markdown.js';

interface EventTimelineProps {
  messages: Message[];
  streamingText?: string;
  toolEvents?: ToolEventNormalized[];
  pageSize?: number;
  pageOffset?: number; // 0 = latest
  showReasoning?: boolean;
  header?: React.ReactNode; // Optional header (banner) to display as first Static item
}

export const EventTimeline = React.memo(function EventTimeline({ messages, streamingText = '', toolEvents = [], pageSize = 50, pageOffset = 0, showReasoning = false, header }: EventTimelineProps) {
  // Split into completed (static) vs streaming (dynamic) events
  // Completed: all messages except potentially the last if streaming
  // Streaming: current streaming text if present

  const isStreaming = streamingText.length > 0;

  // All completed messages
  const completedMessages = messages;
  const messageEvents: TimelineEvent[] = completedMessages.map((m) => ({
    id: m.id,
    kind: 'message',
    // Ensure timestamp is a number for proper sorting with tool events
    // Backend may send ISO strings, frontend creates with Date.now()
    ts: typeof m.timestamp === 'string' ? new Date(m.timestamp).getTime() : m.timestamp,
    role: m.role,
    content: m.content,
    reasoning: m.reasoning,
  } as any));

  const toolEndEvents: TimelineEvent[] = toolEvents
    .filter((e) => e.phase === 'end')
    .map((e) => ({ ...e, kind: 'tool' as const }));

  // All completed events (messages + tools), sorted chronologically
  const completedEvents: TimelineEvent[] = [...messageEvents, ...toolEndEvents]
    .sort((a, b) => a.ts - b.ts);

  // Pagination for completed events
  const total = completedEvents.length;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const clampedOffset = Math.max(0, Math.min(pageOffset, pages - 1));
  const start = Math.max(0, total - pageSize * (clampedOffset + 1));
  const end = total - pageSize * clampedOffset;
  const visibleCompleted = completedEvents.slice(start, end);
  const hiddenOlder = start;

  // Current streaming event (if any) - rendered separately in dynamic Box
  const streamingEvent: TimelineEvent | null = isStreaming
    ? ({ id: 'stream-current', kind: 'stream', ts: Date.now(), role: 'assistant', text: streamingText } as any)
    : null;

  // Build array of React elements for Static component (Gemini CLI pattern)
  // Include header as first element if provided
  const staticItems: React.ReactNode[] = [];

  if (header) {
    staticItems.push(
      <React.Fragment key="header">{header}</React.Fragment>
    );
  }

  // Add all visible event items
  visibleCompleted.forEach((ev, idx) => {
    staticItems.push(
      <EventItem
        key={`${ev.kind}:${ev.id}:${idx}`}
        index={idx + 1 + start}
        event={ev}
        showReasoning={showReasoning}
      />
    );
  });

  return (
    <Box flexDirection="column" gap={1}>
      {hiddenOlder > 0 && (
        <Box>
          <Text color="gray" dimColor>
            {hiddenOlder} older events hidden — Press ↑/PgUp to view
          </Text>
        </Box>
      )}

      {/* Single Static component with header + all events (Gemini CLI pattern) */}
      {/* This ensures banner always appears first and never scrolls away */}
      <Static items={staticItems}>
        {(item) => item}
      </Static>

      {/* Dynamic box: only streaming event can update */}
      {streamingEvent && (
        <EventItem key="stream-current" index={total + 1} event={streamingEvent} showReasoning={showReasoning} />
      )}
    </Box>
  );
});

function EventItem({ event, index, showReasoning }: { event: TimelineEvent; index: number; showReasoning?: boolean }) {
  switch (event.kind) {
    case 'message':
      return <MessageEventItem index={index} event={event} showReasoning={showReasoning} />;
    case 'stream':
      return (
        <Box flexDirection="column">
          <Text color="blue" bold>
            Penguin:
          </Text>
          <Box marginLeft={2}>
            <Markdown content={(event as any).text} />
            <Text color="gray">▊</Text>
          </Box>
        </Box>
      );
    case 'tool':
      // Render compact, minimal tool usage (Codex/Cursor style: just "using X")
      const action = (event as any).action || 'unknown';
      // Simplify action names: "enhanced_read" -> "read", "apply_diff" -> "edit", etc.
      const toolName = action
        .replace(/^enhanced_/, '')
        .replace(/_/g, ' ')
        .replace(/^apply /, 'edit ')
        .trim();
      const status = (event as any).status;
      const hasError = status === 'error';
      
      return (
        <Box flexDirection="column" marginLeft={2}>
          <Text color={hasError ? 'red' : 'gray'} dimColor>
            {hasError ? '✗' : '✓'} using {toolName}
            {(event as any).result && !hasError && (
              <Text> — {(event as any).result.slice(0, 60)}</Text>
            )}
            {hasError && (event as any).result && (
              <Text> — {(event as any).result.slice(0, 60)}</Text>
            )}
          </Text>
        </Box>
      );
    default:
      return null;
  }
}

// Preprocess message to extract action tags before markdown rendering
// Includes all action types from penguin/utils/parser.py ActionType enum
function preprocessMessage(content: string): { displayContent: string; actionCount: number } {
  // Match all action tags - comprehensive list from parser.py ActionType enum
  const actionTypes = [
    'execute',
    'execute_command',
    'search',
    'memory_search',
    'add_declarative_note',
    'list_files_filtered',
    'find_files_enhanced',
    'enhanced_diff',
    'analyze_project',
    'enhanced_read',
    'enhanced_write',
    'apply_diff',
    'multiedit',
    'edit_with_pattern',
    'add_summary_note',
    'perplexity_search',
    'process_start',
    'process_stop',
    'process_status',
    'process_list',
    'process_enter',
    'process_send',
    'process_exit',
    'workspace_search',
    'task_create',
    'task_update',
    'task_complete',
    'task_delete',
    'task_list',
    'task_display',
    'project_create',
    'project_update',
    'project_delete',
    'project_list',
    'project_display',
    'dependency_display',
    'analyze_codebase',
    'reindex_workspace',
    'send_message',
    'browser_navigate',
    'browser_interact',
    'browser_screenshot',
    'pydoll_browser_navigate',
    'pydoll_browser_interact',
    'pydoll_browser_screenshot',
    'pydoll_browser_scroll',
    'pydoll_debug_toggle',
    'spawn_sub_agent',
    'stop_sub_agent',
    'resume_sub_agent',
    'delegate',
    'get_repository_status',
    'create_and_switch_branch',
    'commit_and_push_changes',
    'create_improvement_pr',
    'create_feature_pr',
    'create_bugfix_pr',
  ];
  
  // Build regex pattern: <(action1|action2|...)>.*?</\1>
  const actionTagPattern = new RegExp(`<(${actionTypes.join('|')})[^>]*>.*?<\\/\\1>`, 'gis');
  const matches = content.match(actionTagPattern) || [];
  let displayContent = content;
  
  // Remove action tags but preserve code block structure
  matches.forEach(tag => {
    displayContent = displayContent.replace(tag, '');
  });
  
  // Clean up empty code blocks that might remain
  displayContent = displayContent.replace(/```[\s\n]*```/g, '');
  // Clean up code blocks with only whitespace/comments
  displayContent = displayContent.replace(/```[a-z]*\n[\s#]*```/g, '');
  
  return { displayContent: displayContent.trim(), actionCount: matches.length };
}

// Detect completion markers (TASK_COMPLETED, etc.)
function isCompletionMarker(content: string): boolean {
  const trimmed = content.trim();
  return (
    trimmed === 'TASK_COMPLETED' ||
    trimmed === 'TASK_COMPLETE' ||
    (trimmed.length < 30 && /^(✓|✅|Done|Complete|TASK_COMPLETED)/i.test(trimmed))
  );
}

function MessageEventItem({ event, index, showReasoning }: { event: any; index: number; showReasoning?: boolean }) {
  const isUser = event.role === 'user';
  const color = isUser ? 'green' : 'blue';
  const label = isUser ? 'You' : 'Penguin';
  
  // Filter completion markers (already shown via tool results)
  if (!isUser && isCompletionMarker(event.content)) {
    return null; // Skip rendering - completion already indicated by tool events
  }
  
  // Preprocess to remove action tags from display
  const { displayContent, actionCount } = preprocessMessage(event.content);
  
  // Skip empty messages after preprocessing
  if (!displayContent.trim() && actionCount > 0) {
    // Message was only action tags - already shown in timeline via toolEvents
    return null;
  }
  
  return (
    <Box flexDirection="column">
      <Text color={color} bold>
        <Text dimColor>[{index}]</Text> {label}:
      </Text>
      <Box marginLeft={2} flexDirection="column">
        {!isUser && event.reasoning && (
          <ReasoningBlock content={event.reasoning} show={!!showReasoning} />
        )}
        {isUser ? (
          <Text>{event.content}</Text>
        ) : (
          <>
            <Markdown content={displayContent} />
            {actionCount > 0 && displayContent.trim() && (
              <Text color="gray" dimColor>
                ({actionCount} action{actionCount > 1 ? 's' : ''} executed)
              </Text>
            )}
          </>
        )}
      </Box>
    </Box>
  );
}

function ReasoningBlock({ content, show }: { content: string; show: boolean }) {
  return (
    <Box flexDirection="column" marginBottom={1} borderStyle="round" borderColor="gray" paddingX={1}>
      <Text color="gray" dimColor italic>
        🧠 Internal Reasoning {show ? '' : '(hidden — press r to show)'}
      </Text>
      {show && (
        <Text color="gray" dimColor>
          {content}
        </Text>
      )}
    </Box>
  );
}
