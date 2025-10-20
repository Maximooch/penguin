/**
 * Chat session component with streaming message display
 * Handles user input and displays conversation history
 *
 * REFACTORED: Now uses context-based hooks instead of monolithic useChat
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Box, Text, useInput, useApp } from 'ink';
import { useConnection } from '../contexts/ConnectionContext';
import { useWebSocket } from '../hooks/useWebSocket';
import { useMessageHistory } from '../hooks/useMessageHistory';
import { useStreaming } from '../hooks/useStreaming';
import { useToolExecution } from '../hooks/useToolExecution';
import { useProgress } from '../hooks/useProgress';
import { MessageList } from './MessageList';
import { ConnectionStatus } from './ConnectionStatus';
import { ToolExecutionList } from './ToolExecution';
import { ProgressIndicator } from './ProgressIndicator';
import { MultiLineInput } from './MultiLineInput';

export function ChatSession() {
  const { exit } = useApp();
  const [inputKey, setInputKey] = useState(0);
  const [isExiting, setIsExiting] = useState(false);
  const reasoningRef = useRef(''); // Use ref instead of state to avoid re-renders

  // Hooks (separated by concern)
  const { isConnected, error, client } = useConnection();
  const { sendMessage } = useWebSocket();
  const { messages, addUserMessage, addAssistantMessage } = useMessageHistory();
  const { activeTool, completedTools, clearTools, addActionResults } = useToolExecution();
  const { progress, updateProgress, resetProgress, completeProgress } = useProgress();

  const { streamingText, isStreaming, processToken, complete, reset } = useStreaming({
    onComplete: (finalText: string) => {
      // Add completed streaming message to history with reasoning if present
      if (finalText) {
        console.error(`[ChatSession] onComplete - finalText length: ${finalText.length}, starts with: "${finalText.substring(0, 100)}"`);
        addAssistantMessage(finalText, reasoningRef.current || undefined);
        reasoningRef.current = ''; // Clear reasoning for next message
        reset(); // Clear streaming text immediately after adding to history
      }
    },
  });

  // Set up WebSocket event handlers
  useEffect(() => {
    if (!client) return;

    client.callbacks.onToken = (token: string) => {
      console.log(`[ChatSession] Received token, length: ${token.length}, preview: "${token.substring(0, 50)}..."`);
      processToken(token);
    };

    client.callbacks.onReasoning = (token: string) => {
      console.log(`[ChatSession] Received reasoning token, length: ${token.length}`);
      reasoningRef.current += token;
    };

    client.callbacks.onProgress = (iteration: number, maxIterations: number, message?: string) => {
      updateProgress(iteration, maxIterations, message);
    };

    client.callbacks.onComplete = (actionResults) => {
      // Complete progress tracking
      completeProgress();

      // Process any action results first
      if (actionResults && actionResults.length > 0) {
        addActionResults(actionResults);
      }

      // Then complete streaming
      complete();

      // Reset progress after a delay
      setTimeout(() => resetProgress(), 1000);
    };
  }, [client, processToken, complete, addActionResults, updateProgress, completeProgress, resetProgress]);

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
      clearTools(); // Clear previous tool executions
      sendMessage(value.trim());
      // Force TextInput to remount and clear by changing its key
      setInputKey((prev) => prev + 1);
    }
  }, [isConnected, isStreaming, addUserMessage, sendMessage, clearTools]);

  return (
    <Box flexDirection="column" gap={1}>
      {/* Connection status */}
      <ConnectionStatus isConnected={isConnected} error={error} />

      {/* Message history */}
      <MessageList messages={messages} streamingText={streamingText} />

      {/* Progress indicator for multi-step execution */}
      {progress.isActive && progress.maxIterations > 1 && (
        <Box marginY={0}>
          <ProgressIndicator
            iteration={progress.iteration}
            maxIterations={progress.maxIterations}
            message={progress.message}
            isActive={progress.isActive}
          />
        </Box>
      )}

      {/* Tool execution display (inline during streaming) */}
      {(activeTool || completedTools.length > 0) && (
        <Box flexDirection="column" marginY={0}>
          <ToolExecutionList tools={[...completedTools, ...(activeTool ? [activeTool] : [])]} />
        </Box>
      )}

      {/* Input prompt - Multi-line */}
      <MultiLineInput
        key={inputKey}
        placeholder={isStreaming ? "Waiting for response..." : "Type your message..."}
        isDisabled={!isConnected || isStreaming}
        onSubmit={handleSubmit}
      />

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
