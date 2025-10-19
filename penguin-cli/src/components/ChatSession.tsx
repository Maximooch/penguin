/**
 * Chat session component with streaming message display
 * Handles user input and displays conversation history
 */

import React, { useState, useEffect } from 'react';
import { Box, Text, useInput, useApp } from 'ink';
import { TextInput } from '@inkjs/ui';
import { useChat } from '../hooks/useChat';
import { MessageList } from './MessageList';
import { ConnectionStatus } from './ConnectionStatus';

export interface ChatSessionProps {
  conversationId?: string;
  agentId?: string;
}

export function ChatSession({ conversationId, agentId }: ChatSessionProps) {
  const { exit } = useApp();
  const [inputKey, setInputKey] = useState(0);
  const [isExiting, setIsExiting] = useState(false);

  const {
    messages,
    streamingText,
    isStreaming,
    isConnected,
    error,
    sendMessage,
  } = useChat({ conversationId, agentId });

  // Handle Ctrl+C and Ctrl+D to exit
  useInput((input, key) => {
    if (key.ctrl && (input === 'c' || input === 'd')) {
      if (!isExiting) {
        setIsExiting(true);
        exit();
      }
    }
  });

  const handleSubmit = (value: string) => {
    // Only allow sending if connected and not already streaming
    if (value.trim() && isConnected && !isStreaming) {
      sendMessage(value.trim());
      // Force TextInput to remount and clear by changing its key
      setInputKey((prev) => prev + 1);
    }
  };

  return (
    <Box flexDirection="column" gap={1}>
      {/* Connection status */}
      <ConnectionStatus isConnected={isConnected} error={error} />

      {/* Message history */}
      <MessageList messages={messages} streamingText={streamingText} />

      {/* Input prompt */}
      <Box borderStyle="single" borderColor={!isConnected ? 'gray' : isStreaming ? 'yellow' : 'green'} paddingX={1} flexDirection="row">
        <Box marginRight={1}>
          <Text color={!isConnected ? 'gray' : isStreaming ? 'yellow' : 'green'} bold>
            {'>'}
          </Text>
        </Box>
        <Box flexGrow={1}>
          <TextInput
            key={inputKey}
            placeholder={isStreaming ? "Waiting for response..." : "Type your message..."}
            defaultValue=""
            isDisabled={!isConnected}
            onSubmit={handleSubmit}
          />
        </Box>
      </Box>

      {/* Help text */}
      <Box marginTop={1}>
        <Text dimColor>
          {isStreaming
            ? 'Waiting for response... • Ctrl+C to exit'
            : 'Press Enter to send • Ctrl+C to exit'}
        </Text>
      </Box>
    </Box>
  );
}
