/**
 * Message thread component for multi-agent conversations
 * Shows sender → recipient flow with channel awareness
 */

import React from 'react';
import { Box, Text } from 'ink';
import { Markdown } from './Markdown';

export interface AgentMessage {
  id?: string; // Optional for ProtocolMessage compatibility
  sender?: string;
  recipient?: string;
  content: string;
  message_type?: 'message' | 'action' | 'status' | 'event';
  channel?: string;
  timestamp?: string;
  metadata?: Record<string, any>;
}

export interface MessageThreadProps {
  messages: AgentMessage[];
  streamingText?: string;
  streamingSender?: string;
  currentChannel?: string;
  currentUser?: string; // "human" or specific agent ID
  showChannelFilter?: boolean;
}

export function MessageThread({
  messages,
  streamingText,
  streamingSender,
  currentChannel,
  currentUser = 'human',
  showChannelFilter = true,
}: MessageThreadProps) {
  // Filter messages by channel if specified
  const filteredMessages = showChannelFilter && currentChannel
    ? messages.filter((m) => !m.channel || m.channel === currentChannel)
    : messages;

  return (
    <Box flexDirection="column" gap={1}>
      {filteredMessages.map((message, index) => (
        <MessageThreadItem
          key={message.id || `${message.sender}-${message.timestamp || index}`}
          message={message}
          index={index + 1}
          currentUser={currentUser}
        />
      ))}

      {/* Streaming message */}
      {streamingText && (
        <Box flexDirection="column">
          <Text color="blue" bold>
            {streamingSender || 'Assistant'}:
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

interface MessageThreadItemProps {
  message: AgentMessage;
  index: number;
  currentUser: string;
}

function MessageThreadItem({ message, index, currentUser }: MessageThreadItemProps) {
  const sender = message.sender || 'system';
  const recipient = message.recipient;
  const isFromUser = sender === currentUser || sender === 'human';
  const isDirected = recipient && recipient !== 'human' && recipient !== currentUser;

  // Determine message styling based on type and sender
  const getMessageColor = (): string => {
    if (isFromUser) return 'green';
    if (message.message_type === 'status') return 'yellow';
    if (message.message_type === 'action') return 'magenta';
    if (sender === 'system') return 'gray';
    return 'blue'; // Agent messages
  };

  const getMessageLabel = (): string => {
    if (isFromUser) {
      return 'You';
    }

    // Show sender → recipient for directed messages
    if (isDirected && recipient) {
      return `${sender} → ${recipient}`;
    }

    // Show just sender for broadcasts or to user
    return sender;
  };

  const color = getMessageColor();
  const label = getMessageLabel();

  // Format content based on message type
  const formatContent = (content: string): string => {
    if (message.message_type === 'status') {
      return `📊 ${content}`;
    }
    if (message.message_type === 'action') {
      return `⚡ ${content}`;
    }
    return content;
  };

  return (
    <Box flexDirection="column">
      <Box>
        <Text color={color} bold>
          <Text dimColor>[{index}]</Text> {label}:
        </Text>
        {message.channel && (
          <Text dimColor> in {message.channel}</Text>
        )}
      </Box>
      <Box marginLeft={2} flexDirection="column">
        {isFromUser ? (
          <Text>{formatContent(message.content)}</Text>
        ) : (
          <Markdown content={formatContent(message.content)} />
        )}

        {/* Show timestamp for agent messages */}
        {message.timestamp && !isFromUser && (
          <Text dimColor>
            {new Date(message.timestamp).toLocaleTimeString()}
          </Text>
        )}
      </Box>
    </Box>
  );
}
