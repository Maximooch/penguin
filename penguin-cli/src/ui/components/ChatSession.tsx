/**
 * Chat session component with streaming message display
 * Handles user input and displays conversation history
 *
 * REFACTORED: Now uses context-based hooks instead of monolithic useChat
 */

import React, { useState, useEffect, useCallback } from 'react';
import { Box, Text, useInput, useApp } from 'ink';
import { TextInput } from '@inkjs/ui';
import { useConnection } from '../contexts/ConnectionContext';
import { useWebSocket } from '../hooks/useWebSocket';
import { useMessageHistory } from '../hooks/useMessageHistory';
import { useStreaming } from '../hooks/useStreaming';
import { MessageList } from './MessageList';
import { ConnectionStatus } from './ConnectionStatus';

export function ChatSession() {
  const { exit } = useApp();
  const [inputKey, setInputKey] = useState(0);
  const [isExiting, setIsExiting] = useState(false);

  // Hooks (separated by concern)
  const { isConnected, error, client } = useConnection();
  const { sendMessage } = useWebSocket();
  const { messages, addUserMessage, addAssistantMessage } = useMessageHistory();
  const { streamingText, isStreaming, processToken, complete, reset } = useStreaming({
    onComplete: () => {
      // Add completed streaming message to history
      if (streamingText) {
        addAssistantMessage(streamingText);
        reset();
      }
    },
  });

  // Set up WebSocket event handlers
  useEffect(() => {
    if (!client) return;

    client.callbacks.onToken = (token: string) => {
      processToken(token);
    };

    client.callbacks.onComplete = () => {
      complete();
    };
  }, [client, processToken, complete]);

  // Handle Ctrl+C and Ctrl+D to exit
  useInput((input, key) => {
    if (key.ctrl && (input === 'c' || input === 'd')) {
      if (!isExiting) {
        setIsExiting(true);
        exit();
      }
    }
  });

  const handleSubmit = useCallback((value: string) => {
    // Only allow sending if connected and not already streaming
    if (value.trim() && isConnected && !isStreaming) {
      addUserMessage(value.trim());
      sendMessage(value.trim());
      // Force TextInput to remount and clear by changing its key
      setInputKey((prev) => prev + 1);
    }
  }, [isConnected, isStreaming, addUserMessage, sendMessage]);

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
