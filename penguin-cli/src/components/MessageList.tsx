/**
 * Message list component
 * Displays conversation history and streaming text
 */

import React from 'react';
import { Box, Text } from 'ink';
import { Message } from '../api/client';

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
        <Box>
          <Text color="blue" bold>
            Assistant:{' '}
          </Text>
          <Text>{streamingText}</Text>
          <Text color="gray">▊</Text> {/* Cursor */}
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
    <Box>
      <Text color={color} bold>
        {label}:{' '}
      </Text>
      <Text>{message.content}</Text>
    </Box>
  );
}
