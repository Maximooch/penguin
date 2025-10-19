/**
 * Chat session component with streaming message display
 * Handles user input and displays conversation history
 */

import React, { useState } from 'react';
import { Box, Text, useInput, useApp } from 'ink';
import { useChat } from '../hooks/useChat';
import { MessageList } from './MessageList';
import { InputPrompt } from './InputPrompt';
import { ConnectionStatus } from './ConnectionStatus';

export interface ChatSessionProps {
  conversationId?: string;
  agentId?: string;
}

export function ChatSession({ conversationId, agentId }: ChatSessionProps) {
  const { exit } = useApp();
  const [inputValue, setInputValue] = useState('');

  const {
    messages,
    streamingText,
    isStreaming,
    isConnected,
    error,
    sendMessage,
  } = useChat({ conversationId, agentId });

  // Handle keyboard input
  useInput((input, key) => {
    // Ctrl+C or Ctrl+D to exit
    if (key.ctrl && (input === 'c' || input === 'd')) {
      exit();
      return;
    }

    // Enter to send message (if not streaming)
    if (key.return && !isStreaming && inputValue.trim()) {
      sendMessage(inputValue.trim());
      setInputValue('');
      return;
    }

    // Backspace
    if (key.backspace || key.delete) {
      setInputValue((prev) => prev.slice(0, -1));
      return;
    }

    // Regular character input (not streaming and not special keys)
    if (!isStreaming && !key.ctrl && !key.meta && input.length === 1) {
      setInputValue((prev) => prev + input);
    }
  });

  return (
    <Box flexDirection="column" gap={1}>
      {/* Connection status */}
      <ConnectionStatus isConnected={isConnected} error={error} />

      {/* Message history */}
      <MessageList messages={messages} streamingText={streamingText} />

      {/* Input prompt */}
      <InputPrompt
        value={inputValue}
        isStreaming={isStreaming}
        isConnected={isConnected}
      />

      {/* Help text */}
      <Box marginTop={1}>
        <Text dimColor>
          Press Enter to send • Ctrl+C to exit
        </Text>
      </Box>
    </Box>
  );
}
