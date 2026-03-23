/**
 * Message list component
 * Displays conversation history and streaming text
 */

import React from 'react';
import { Box, Text } from 'ink';
import type { Message } from '../../core/types';
import { Markdown } from './Markdown';

export interface MessageListProps {
  messages: Message[];
  streamingText: string;
}

export function MessageList({ messages, streamingText }: MessageListProps) {
  return (
    <Box flexDirection="column" gap={1}>
      {messages.map((message, index) => (
        <MessageItem key={message.id} message={message} index={index + 1} />
      ))}

      {/* Streaming assistant response */}
      {streamingText && (
        <Box flexDirection="column">
          <Text color="blue" bold>
            Penguin:
          </Text>
          <Box marginLeft={2}>
            <Markdown content={streamingText} />
            <Text color="gray">▊</Text>
          </Box>
        </Box>
      )}
    </Box>
  );
}

interface MessageItemProps {
  message: Message;
  index: number;
}

const MessageItem = React.memo(function MessageItem({ message, index }: MessageItemProps) {
  const isUser = message.role === 'user';
  const color = isUser ? 'green' : 'blue';
  const label = isUser ? 'You' : 'Penguin';

  return (
    <Box flexDirection="column">
      <Text color={color} bold>
        <Text dimColor>[{index}]</Text> {label}:
      </Text>
      <Box marginLeft={2} flexDirection="column">
        {/* Display reasoning if present (for assistant messages) */}
        {!isUser && message.reasoning && (
          <Box flexDirection="column" marginBottom={1} borderStyle="round" borderColor="gray" paddingX={1}>
            <Text color="gray" dimColor italic>
              🧠 Internal Reasoning
            </Text>
            <Text color="gray" dimColor>
              {message.reasoning}
            </Text>
          </Box>
        )}

        {/* Main message content */}
        {isUser ? (
          <Text>{message.content}</Text>
        ) : (
          <Markdown content={message.content} />
        )}
      </Box>
    </Box>
  );
}, (prev, next) => {
  // Avoid re-rendering finalized messages unless their id or content changes
  return (
    prev.message.id === next.message.id &&
    prev.message.content === next.message.content &&
    prev.message.reasoning === next.message.reasoning &&
    prev.index === next.index
  );
});
