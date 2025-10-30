import React from 'react';
import { Box, Text } from 'ink';
import type { Message, ToolEventNormalized, TimelineEvent } from '../../core/types';
import { Markdown } from './Markdown.js';

interface EventTimelineProps {
  messages: Message[];
  streamingText?: string;
  toolEvents?: ToolEventNormalized[];
  pageSize?: number;
  pageOffset?: number; // 0 = latest
  showReasoning?: boolean;
}

export function EventTimeline({ messages, streamingText = '', toolEvents = [], pageSize = 50, pageOffset = 0, showReasoning = false }: EventTimelineProps) {
  // Build a simple timeline: messages (by timestamp), tool end events, and current stream at end
  const messageEvents: TimelineEvent[] = messages.map((m) => ({
    id: m.id,
    kind: 'message',
    ts: m.timestamp,
    role: m.role,
    content: m.content,
    reasoning: m.reasoning,
  } as any));

  const toolEndEvents: TimelineEvent[] = toolEvents
    .filter((e) => e.phase === 'end')
    .map((e) => ({ ...e, kind: 'tool' as const }));

  const streamingEvent: TimelineEvent[] = streamingText
    ? [{ id: 'stream-current', kind: 'stream', ts: Date.now(), role: 'assistant', text: streamingText } as any]
    : [];

  const all: TimelineEvent[] = [...messageEvents, ...toolEndEvents, ...streamingEvent]
    .sort((a, b) => a.ts - b.ts);

  const total = all.length;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const clampedOffset = Math.max(0, Math.min(pageOffset, pages - 1));
  const start = Math.max(0, total - pageSize * (clampedOffset + 1));
  const end = total - pageSize * clampedOffset;
  const events: TimelineEvent[] = all.slice(start, end);
  const hiddenOlder = start;

  return (
    <Box flexDirection="column" gap={1}>
      {hiddenOlder > 0 && (
        <Box>
          <Text color="gray" dimColor>
            {hiddenOlder} older events hidden — Press ↑/PgUp to view
          </Text>
        </Box>
      )}
      {events.map((ev, idx) => (
        <EventItem key={`${ev.kind}:${ev.id}:${idx}`} index={idx + 1 + start} event={ev} showReasoning={showReasoning} />
      ))}
    </Box>
  );
}

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
      // Render compact, dimmed inline summary of finished tool result
      return (
        <Box flexDirection="column" marginLeft={2}>
          <Text color={(event as any).status === 'error' ? 'red' : 'gray'} dimColor>
            ⧗ {(event as any).action}: {(event as any).result?.slice(0, 120) || ''}
          </Text>
        </Box>
      );
    default:
      return null;
  }
}

function MessageEventItem({ event, index, showReasoning }: { event: any; index: number; showReasoning?: boolean }) {
  const isUser = event.role === 'user';
  const color = isUser ? 'green' : 'blue';
  const label = isUser ? 'You' : 'Penguin';
  return (
    <Box flexDirection="column">
      <Text color={color} bold>
        <Text dimColor>[{index}]</Text> {label}:
      </Text>
      <Box marginLeft={2} flexDirection="column">
        {!isUser && event.reasoning && (
          <ReasoningBlock content={event.reasoning} show={!!showReasoning} />
        )}
        {isUser ? <Text>{event.content}</Text> : <Markdown content={event.content} />}
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
