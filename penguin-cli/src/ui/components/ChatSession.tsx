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
import { SessionList } from './SessionList';
import { SessionPickerModal } from './SessionPickerModal';
import { SessionAPI } from '../../core/api/SessionAPI.js';
import type { Session } from '../../core/types.js';
import { useTab } from '../contexts/TabContext.js';
import { ChatClient } from '../../core/connection/WebSocketClient.js';

interface ChatSessionProps {
  conversationId?: string;
  isActive?: boolean;
}

export function ChatSession({ conversationId: propConversationId, isActive = true }: ChatSessionProps) {
  const { exit } = useApp();
  const [inputKey, setInputKey] = useState(0);
  const [isExiting, setIsExiting] = useState(false);
  const [currentInput, setCurrentInput] = useState('');
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [showingSessionList, setShowingSessionList] = useState(false);
  const [showSessionPicker, setShowSessionPicker] = useState(false);
  const [isLoadingSessions, setIsLoadingSessions] = useState(false);
  const reasoningRef = useRef(''); // Use ref instead of state to avoid re-renders
  const sessionAPI = useRef(new SessionAPI('http://localhost:8000'));
  const clientRef = useRef<any>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  // Each ChatSession creates its own WebSocket client
  useEffect(() => {
    const client = new ChatClient({
      url: 'ws://localhost:8000/api/v1/chat/stream',
      conversationId: propConversationId,
      onConnect: () => {
        setIsConnected(true);
        setError(null);
      },
      onDisconnect: () => {
        setIsConnected(false);
      },
      onError: (err: Error) => {
        setError(err);
        setIsConnected(false);
      },
    });

    client.connect();
    clientRef.current = client;

    return () => {
      client.disconnect();
      clientRef.current = null;
    };
  }, [propConversationId]);

  const { parseInput, getSuggestions } = useCommand();

  const sendMessage = (message: string) => {
    if (clientRef.current && isConnected) {
      clientRef.current.sendMessage(message);
    }
  };
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
    const client = clientRef.current;
    if (!client) return;

    client.callbacks.onToken = (token: string) => {
      console.log(`[ChatSession ${propConversationId}] Received token, length: ${token.length}`);
      processToken(token);
    };

    client.callbacks.onReasoning = (token: string) => {
      console.log(`[ChatSession ${propConversationId}] Received reasoning token`);
      reasoningRef.current += token;
    };

    client.callbacks.onProgress = (iteration: number, maxIterations: number, message?: string) => {
      updateProgress(iteration, maxIterations, message);
    };

    client.callbacks.onComplete = (actionResults: any) => {
      completeProgress();
      if (actionResults && actionResults.length > 0) {
        addActionResults(actionResults);
      }
      complete();
      setTimeout(() => resetProgress(), 1000);
    };
  }, [propConversationId, processToken, complete, addActionResults, updateProgress, completeProgress, resetProgress]);

  const { prevTab, openChatTab, closeTab, activeTab } = useTab();

  // Handle global hotkeys (only when this tab is active)
  useInput((input, key) => {
    if (!isActive) return; // Ignore input if this tab is not active

    // Ctrl+C and Ctrl+D to exit
    if (key.ctrl && (input === 'c' || input === 'd')) {
      if (!isExiting) {
        setIsExiting(true);
        exit();
      }
    }
    // Ctrl+W to close current tab
    else if (key.ctrl && input === 'w') {
      if (activeTab?.type === 'chat') {
        closeTab(activeTab.id);
      }
    }
    // Ctrl+P to toggle between tabs (previous tab)
    else if (key.ctrl && input === 'p') {
      prevTab();
    }
    // Ctrl+O to open session picker
    else if (key.ctrl && input === 'o') {
      if (!showSessionPicker) {
        setIsLoadingSessions(true);
        setShowSessionPicker(true);
        sessionAPI.current
          .listSessions()
          .then((sessionList) => {
            setSessions(sessionList);
            setIsLoadingSessions(false);
          })
          .catch((err) => {
            console.error('Failed to load sessions:', err);
            setIsLoadingSessions(false);
            setShowSessionPicker(false);
          });
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

  const handleCommand = useCallback((commandName: string, args: Record<string, any>) => {
    // Built-in command handlers
    switch (commandName) {
      case 'help':
      case 'h':
      case '?':
        // Show help as a system message
        addAssistantMessage(
          `# Penguin CLI Commands\n\nType \`/help\` to see this message again.\n\n## Available Commands:\n\n### 💬 Chat\n- \`/help\` (aliases: /h, /?) - Show this help\n- \`/clear\` (aliases: /cls, /reset) - Clear chat history\n- \`/chat list\` - List all conversations\n- \`/chat load <id>\` - Load a conversation\n- \`/chat delete <id>\` - Delete a conversation\n- \`/chat new\` - Start a new conversation\n\n### 🚀 Workflow\n- \`/init\` - Initialize project with AI assistance\n- \`/review\` - Review code changes and suggest improvements\n- \`/plan <feature>\` - Create implementation plan for a feature\n\n### ⚙️ System\n- \`/quit\` (aliases: /exit, /q) - Exit the CLI\n\nMore commands available! See commands.yml for full list.`
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

      // Session management commands - use REST API
      case 'chat list':
        addUserMessage('/chat list');
        sessionAPI.current.listSessions()
          .then(sessionList => {
            setSessions(sessionList);
            setShowingSessionList(true);
            // Also show as formatted message
            if (sessionList.length === 0) {
              addAssistantMessage('No conversations found.');
            } else {
              const formatted = `📋 Found ${sessionList.length} conversation(s):\n\n` +
                sessionList.slice(0, 10).map(s =>
                  `• ${s.id.slice(0, 8)}: ${s.title || 'Untitled'} (${s.message_count || 0} messages)`
                ).join('\n');
              addAssistantMessage(formatted);
            }
          })
          .catch(err => {
            addAssistantMessage(`Error listing sessions: ${err.message}`);
          });
        break;

      case 'chat load':
        if (args.session_id) {
          addUserMessage(`/chat load ${args.session_id}`);
          sessionAPI.current.getSession(args.session_id)
            .then(session => {
              openChatTab(session.id, session.title || `Chat ${session.id.slice(0, 8)}`);
            })
            .catch((err: any) => {
              addAssistantMessage(`Error loading session: ${err.message}`);
            });
        } else {
          addAssistantMessage('Error: Missing session ID. Usage: `/chat load <session_id>`');
        }
        break;

      case 'chat delete':
        if (args.session_id) {
          addUserMessage(`/chat delete ${args.session_id}`);
          sessionAPI.current.deleteSession(args.session_id)
            .then(success => {
              if (success) {
                addAssistantMessage(`✓ Deleted session: ${args.session_id.slice(0, 8)}`);
                // Refresh the session list if showing
                if (showingSessionList) {
                  sessionAPI.current.listSessions().then(setSessions);
                }
              } else {
                addAssistantMessage(`Error: Session ${args.session_id} not found.`);
              }
            })
            .catch(err => {
              addAssistantMessage(`Error deleting session: ${err.message}`);
            });
        } else {
          addAssistantMessage('Error: Missing session ID. Usage: `/chat delete <session_id>`');
        }
        break;

      case 'chat new':
        addUserMessage('/chat new');
        sessionAPI.current.createSession()
          .then(newSessionId => {
            // Open new session in a new tab
            openChatTab(newSessionId, `New Chat ${newSessionId.slice(0, 8)}`);
          })
          .catch((err: any) => {
            addAssistantMessage(`Error creating session: ${err.message}`);
          });
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

  const handleSubmit = useCallback((value: string) => {
    const trimmed = value.trim();
    if (!trimmed) return;

    // Reset suggestions
    setSuggestions([]);
    setCurrentInput('');

    // Check if this is a command (starts with /)
    if (trimmed.startsWith('/')) {
      const parsed = parseInput(trimmed);
      console.error(`[ChatSession] Parsed command: ${trimmed} -> ${parsed ? parsed.command.name : 'null'}`);
      if (parsed) {
        // Handle command
        console.error(`[ChatSession] Handling command: ${parsed.command.name} with args:`, parsed.args);
        handleCommand(parsed.command.name, parsed.args);
        setInputKey((prev) => prev + 1);
        return;
      } else {
        console.error(`[ChatSession] Command not recognized, falling through to send as message`);
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
  }, [isConnected, isStreaming, addUserMessage, sendMessage, clearTools, parseInput, handleCommand]);

  // Handle session selection from modal
  const handleSessionSelect = useCallback((session: Session) => {
    setShowSessionPicker(false);
    openChatTab(session.id, session.title || `Chat ${session.id.slice(0, 8)}`);
  }, [openChatTab]);

  // Handle session deletion from modal
  const handleSessionDelete = useCallback((sessionId: string) => {
    sessionAPI.current
      .deleteSession(sessionId)
      .then(() => {
        // Refresh session list
        return sessionAPI.current.listSessions();
      })
      .then((sessionList) => {
        setSessions(sessionList);
      })
      .catch((err) => {
        console.error('Failed to delete session:', err);
      });
  }, []);

  return (
    <Box flexDirection="column" gap={1}>
      {/* Main content */}
      {!showSessionPicker && (
        <>
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
                : 'Enter: Send • Ctrl+P: Switch • Ctrl+W: Close Tab • Ctrl+O: Sessions • Ctrl+C: Exit'}
            </Text>
          </Box>
        </>
      )}

      {/* Session Picker Modal (full screen overlay) */}
      {showSessionPicker && (
        <Box flexDirection="column" width="100%" height="100%" justifyContent="center" alignItems="center">
          <SessionPickerModal
            sessions={sessions}
            currentSessionId={propConversationId}
            onSelect={handleSessionSelect}
            onDelete={handleSessionDelete}
            onClose={() => setShowSessionPicker(false)}
            isLoading={isLoadingSessions}
          />
        </Box>
      )}
    </Box>
  );
}
