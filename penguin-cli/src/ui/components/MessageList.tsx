/**
 * Message list component
 * Displays conversation history and streaming text
 */

import React from 'react';
import { Box, Text } from 'ink';
import type { Message } from '../../core/types';

export interface MessageListProps {
  messages: Message[];
  streamingText: string;
}

export function MessageList({ messages, streamingText }: MessageListProps) {
  return (
    <Box flexDirection="column" gap={1}>
      {messages.map((message) => (
        <MessageItem key={message.id} message={message} />
      ))}

      {/* Streaming assistant response */}
      {streamingText && (
        <Box flexDirection="row">
          <Text color="blue" bold>
            Assistant:{' '}
          </Text>
          <Text>
            {streamingText}
            <Text color="gray">▊</Text>
          </Text>
        </Box>
      )}
    </Box>
  );
}

interface MessageItemProps {
  message: Message;
}

function MessageItem({ message }: MessageItemProps) {
  const isUser = message.role === 'user';
  const color = isUser ? 'green' : 'blue';
  const label = isUser ? 'You' : 'Assistant';

  return (
    <Box flexDirection="row">
      <Text color={color} bold>
        {label}:{' '}
      </Text>
      <Text>{message.content}</Text>
    </Box>
  );
}
