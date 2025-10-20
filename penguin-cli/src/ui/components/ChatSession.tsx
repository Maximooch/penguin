/**
 * Chat session component with streaming message display
 * Handles user input and displays conversation history
 *
 * REFACTORED: Now uses context-based hooks instead of monolithic useChat
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Box, Text, useInput, useApp } from 'ink';
import { useConnection } from '../contexts/ConnectionContext';
import { useCommand } from '../contexts/CommandContext';
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
  const [currentInput, setCurrentInput] = useState('');
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const reasoningRef = useRef(''); // Use ref instead of state to avoid re-renders

  // Hooks (separated by concern)
  const { isConnected, error, client } = useConnection();
  const { parseInput, getSuggestions } = useCommand();
  const { sendMessage } = useWebSocket();
  const { messages, addUserMessage, addAssistantMessage, clearMessages } = useMessageHistory();
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

  const handleTextChange = useCallback((text: string) => {
    setCurrentInput(text);

    // Get autocomplete suggestions if text starts with /
    if (text.startsWith('/')) {
      const sugs = getSuggestions(text);
      setSuggestions(sugs);
    } else {
      setSuggestions([]);
    }
  }, [getSuggestions]);

  const handleSubmit = useCallback((value: string) => {
    const trimmed = value.trim();
    if (!trimmed) return;

    // Reset suggestions
    setSuggestions([]);
    setCurrentInput('');

    // Check if this is a command (starts with /)
    if (trimmed.startsWith('/')) {
      const parsed = parseInput(trimmed);
      if (parsed) {
        // Handle command
        handleCommand(parsed.command.name, parsed.args);
        setInputKey((prev) => prev + 1);
        return;
      }
    }

    // Only allow sending regular messages if connected and not already streaming
    if (isConnected && !isStreaming) {
      addUserMessage(trimmed);
      clearTools(); // Clear previous tool executions
      sendMessage(trimmed);
      // Force input to remount and clear by changing its key
      setInputKey((prev) => prev + 1);
    }
  }, [isConnected, isStreaming, addUserMessage, sendMessage, clearTools, parseInput, getSuggestions]);

  const handleCommand = useCallback((commandName: string, args: Record<string, any>) => {
    // Built-in command handlers
    switch (commandName) {
      case 'help':
      case 'h':
      case '?':
        // Show help as a system message
        addAssistantMessage(
          `# Penguin CLI Commands\n\nType \`/help\` to see this message again.\n\n## Available Commands:\n\n### 💬 Chat\n- \`/help\` (aliases: /h, /?) - Show this help\n- \`/clear\` (aliases: /cls, /reset) - Clear chat history\n\n### 🚀 Workflow\n- \`/init\` - Initialize project with AI assistance\n- \`/review\` - Review code changes and suggest improvements\n- \`/plan <feature>\` - Create implementation plan for a feature\n\n### ⚙️ System\n- \`/quit\` (aliases: /exit, /q) - Exit the CLI\n\nMore commands available! See commands.yml for full list.`
        );
        break;

      case 'clear':
      case 'cls':
      case 'reset':
        // Clear all messages and tool executions
        clearMessages();
        clearTools();
        resetProgress();
        break;

      case 'quit':
      case 'exit':
      case 'q':
        // Exit the application
        if (!isExiting) {
          setIsExiting(true);
          exit();
        }
        break;

      // Workflow prompt commands - send structured prompts to backend
      case 'init':
        if (isConnected) {
          const initPrompt = `🚀 **Project Initialization**\n\nPlease help me initialize this project:\n\n1. Analyze the current project structure and codebase\n2. Identify the main technologies, frameworks, and patterns used\n3. Suggest improvements to architecture, organization, or setup\n4. Recommend next steps for development\n5. Identify any potential issues or missing components\n\nWorkspace: ${process.cwd()}`;
          addUserMessage('/init');
          sendMessage(initPrompt);
          clearTools();
        }
        break;

      case 'review':
        if (isConnected) {
          const reviewPrompt = `🔍 **Code Review Request**\n\nPlease review recent changes in this project:\n\n1. Analyze code quality, patterns, and best practices\n2. Check for potential bugs, security issues, or performance problems\n3. Suggest improvements to readability and maintainability\n4. Verify test coverage and documentation\n5. Provide specific, actionable feedback\n\nWorkspace: ${process.cwd()}\n\n*Tip: Use \`git diff\` or provide specific files to review.*`;
          addUserMessage('/review');
          sendMessage(reviewPrompt);
          clearTools();
        }
        break;

      case 'plan':
        if (isConnected) {
          const feature = args.feature || 'the requested feature';
          const planPrompt = `📋 **Implementation Plan**\n\nCreate a detailed implementation plan for: **${feature}**\n\n1. Break down the feature into concrete tasks\n2. Identify dependencies and prerequisites\n3. Suggest file structure and code organization\n4. List potential challenges and solutions\n5. Estimate complexity and provide implementation order\n6. Include testing strategy\n\nWorkspace: ${process.cwd()}`;
          addUserMessage(`/plan ${feature}`);
          sendMessage(planPrompt);
          clearTools();
        }
        break;

      default:
        // Unknown command
        addAssistantMessage(`Unknown command: /${commandName}. Type \`/help\` for available commands.`);
    }
  }, [addAssistantMessage, addUserMessage, clearMessages, clearTools, resetProgress, exit, isExiting, isConnected, sendMessage]);

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

      {/* Input prompt - Multi-line with autocomplete */}
      <MultiLineInput
        key={inputKey}
        placeholder={isStreaming ? "Waiting for response..." : "Type your message..."}
        isDisabled={!isConnected || isStreaming}
        onSubmit={handleSubmit}
        onTextChange={handleTextChange}
        suggestions={suggestions}
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
