/**
 * ChatSession - Refactored with hooks and Static pattern
 *
 * Reduced from 1,124 lines to ~350 lines through:
 * - useChatState: Consolidated UI state management
 * - useChatCommands: Extracted command handling
 * - useChatAccumulator: Transcript state with Static pattern
 * - useRunMode: RunMode state and WebSocket streaming
 * - ChatMessageArea: Static + dynamic message rendering
 */

import React, { useEffect, useCallback, useState, useMemo, useRef } from 'react';
import { Box, Text, useInput, useApp } from 'ink';
import { useCommand } from '../contexts/CommandContext.js';
import { useTab } from '../contexts/TabContext.js';
import { useConnection } from '../contexts/ConnectionContext.js';
import { useChatState } from '../hooks/useChatState.js';
import { useChatAccumulator } from '../hooks/useChatAccumulator.js';
import { useChatCommands } from '../hooks/useChatCommands.js';
import { useRunMode } from '../hooks/useRunMode.js';
import { ChatMessageArea } from './ChatMessageArea.js';
import { MultiLineInput } from './MultiLineInput.js';
import { StatusPanel } from './StatusPanel.js';
import { SessionPickerModal } from './SessionPickerModal.js';
import { ModelSelectorModal } from './ModelSelectorModal.js';
import { SettingsModal } from './SettingsModal.js';
import { ProjectList } from './ProjectList.js';
import { TaskList } from './TaskList.js';
import { RunModeStatus } from './RunModeStatus.js';
import { logger } from '../../utils/logger.js';
import { existsSync } from 'fs';
import { homedir } from 'os';
import type { Session } from '../../core/types.js';

interface ChatSessionProps {
  conversationId?: string;
}

export function ChatSession({ conversationId: propConversationId }: ChatSessionProps) {
  const { exit } = useApp();
  const { parseInput, getSuggestions } = useCommand();
  const { switchConversation } = useTab();

  // Consolidated state management
  const chatState = useChatState();
  const {
    sessions,
    projects,
    tasks,
    openModal,
    closeModal,
    setLoadingModal,
    setSuggestions,
    clearInput,
    adjustTimelineOffset,
    toggleReasoning,
    setExiting,
    setSessions,
    setProjects,
    setTasks,
    showSessionPicker,
    showModelSelector,
    showSettings,
    showingProjectList,
    showingTaskList,
    isLoadingSessions,
    inputKey,
    suggestions,
    showReasoning,
    isExiting,
  } = chatState;

  // Get workspace from current directory - memoized
  const workspace = useMemo(() => process.cwd().split('/').pop() || process.cwd(), []);

  // Accumulator for transcript management with Static pattern
  const accumulator = useChatAccumulator({ version: '0.1.0', workspace });
  const {
    staticLines,
    dynamicLines,
    onChunk,
    addUserMessage,
    addErrorMessage,
    addStatusMessage,
    reset: resetAccumulator,
  } = accumulator;

  // Use shared connection from context
  const { client, isConnected, error: connectionError } = useConnection();
  const [isStreaming, setIsStreaming] = useState(false);
  const isSendingRef = useRef(false); // Synchronous guard to prevent double-sends

  // RunMode hook
  const runMode = useRunMode({
    conversationId: propConversationId,
    onMessage: (content, role) => {
      if (role === 'assistant') {
        onChunk({
          event: 'token',
          data: { content, id: `run-${Date.now()}` },
        });
        onChunk({ event: 'complete', data: {} });
      }
    },
    onError: (error) => {
      addErrorMessage(error);
    },
  });

  // Create sendMessage helper using context client
  const sendMessage = useCallback((message: string, options?: { image_path?: string }) => {
    if (client?.isConnected()) {
      client.sendMessage(message, options);
    }
  }, [client]);

  // Command handler dependencies - wire up to new hooks
  const commandDeps = {
    addUserMessage: (text: string) => addUserMessage(text),
    addAssistantMessage: (text: string) => {
      onChunk({ event: 'token', data: { content: text, id: `cmd-${Date.now()}` } });
      onChunk({ event: 'complete', data: {} });
    },
    clearMessages: resetAccumulator,
    clearTools: () => {},
    clearToolEvents: () => {},
    resetProgress: () => {},
    isConnected,
    sendMessage,
    conversationId: propConversationId,
    switchConversation,
    setShowModelSelector: (show: boolean) => show ? openModal('model') : closeModal(),
    setShowSettings: (show: boolean) => show ? openModal('settings') : closeModal(),
    setShowSessionPicker: (show: boolean) => show ? openModal('sessions') : closeModal(),
    setIsLoadingSessions: setLoadingModal,
    setSessions,
    setProjects,
    setTasks,
    setShowingProjectList: (show: boolean) => show ? openModal('projects') : closeModal(),
    setShowingTaskList: (show: boolean) => show ? openModal('tasks') : closeModal(),
    setShowingSessionList: () => {},
    setRunModeStatus: () => {},
    setShowingRunMode: () => {},
    setRunModeMessage: () => {},
    setRunModeProgress: () => {},
  };

  // Command handling hook
  const { handleCommand, sessionAPI, modelAPI } = useChatCommands(commandDeps);

  // Wire up WebSocket callbacks to accumulator (using context client)
  // NOTE: Only depend on client - callbacks use refs to avoid stale closures
  useEffect(() => {
    if (!client) return;

    client.callbacks.onToken = (token: string) => {
      setIsStreaming(true);
      isSendingRef.current = false; // Response started
      onChunk({ event: 'token', data: { content: token } });
    };

    client.callbacks.onReasoning = (token: string) => {
      onChunk({ event: 'reasoning', data: { content: token } });
    };

    client.callbacks.onProgress = (iteration: number, maxIterations: number, message?: string) => {
      if (message) {
        addStatusMessage([`Progress: ${iteration}/${maxIterations} - ${message}`]);
      }
    };

    client.callbacks.onToolEvent = (data: any) => {
      if (data.phase === 'start') {
        onChunk({
          event: 'tool_call',
          data: {
            tool_call_id: data.id,
            tool_name: data.action,
            tool_args: JSON.stringify(data),
          },
        });
      } else if (data.phase === 'end') {
        onChunk({
          event: 'tool_result',
          data: {
            tool_call_id: data.id,
            result: data.result || '',
            status: data.status === 'error' ? 'error' : 'success',
          },
        });
      }
    };

    client.callbacks.onComplete = () => {
      setIsStreaming(false);
      isSendingRef.current = false; // Allow new messages
      onChunk({ event: 'complete', data: {} });
    };

    client.callbacks.onError = (error: Error) => {
      setIsStreaming(false);
      isSendingRef.current = false; // Allow retry on error
      addErrorMessage(error.message);
    };
  }, [client, onChunk, addStatusMessage, addErrorMessage]);

  // Handle global hotkeys
  useInput((input, key) => {
    if (showSettings || showSessionPicker || showModelSelector) {
      return;
    }

    if (showingProjectList || showingTaskList) {
      closeModal();
      return;
    }

    if (key.ctrl && input === 's') {
      openModal('settings');
      return;
    }

    if (!key.ctrl && (input === 'r' || input === 'R')) {
      toggleReasoning();
      return;
    }

    const totalEvents = staticLines.length + dynamicLines.length;
    const pageSize = 50;
    const maxOffset = Math.max(0, Math.ceil(totalEvents / pageSize) - 1);

    if (key.pageUp || (key.ctrl && key.upArrow)) {
      adjustTimelineOffset(1, maxOffset);
      return;
    }
    if (key.pageDown || (key.ctrl && key.downArrow)) {
      adjustTimelineOffset(-1, maxOffset);
      return;
    }

    if (key.ctrl && (input === 'c' || input === 'd')) {
      if (!isExiting) {
        setExiting(true);
        exit();
      }
    }

    if (key.ctrl && input === 'o') {
      if (!showSessionPicker) {
        setLoadingModal(true);
        openModal('sessions');
        sessionAPI.listSessions()
          .then((sessionList) => {
            setSessions(sessionList);
            setLoadingModal(false);
          })
          .catch((err) => {
            logger.warn('Failed to load sessions:', err);
            setLoadingModal(false);
            closeModal();
          });
      }
    }
  });

  // Handle text input change
  const handleTextChange = useCallback((text: string) => {
    if (text.startsWith('/')) {
      const sugs = getSuggestions(text);
      setSuggestions(sugs);
    } else {
      setSuggestions([]);
    }
  }, [getSuggestions, setSuggestions]);

  // Handle message submit
  const handleSubmit = useCallback((value: string) => {
    const trimmed = value.trim();
    if (!trimmed) return;

    setSuggestions([]);

    const imageExtensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg'];
    const lines = trimmed.split('\n').map(l => l.trim()).filter(l => l.length > 0);
    let imagePath: string | null = null;
    let messageText: string | null = null;

    for (const line of lines) {
      const cleanedLine = line.replace(/^['"]|['"]$/g, '');
      const lowerLine = cleanedLine.toLowerCase();
      const isImage = imageExtensions.some(ext => lowerLine.endsWith(ext)) &&
                     (cleanedLine.startsWith('/') || cleanedLine.startsWith('~') || cleanedLine.startsWith('.'));

      if (isImage) {
        let expandedPath = cleanedLine.startsWith('~')
          ? cleanedLine.replace('~', homedir())
          : cleanedLine;
        if (existsSync(expandedPath)) {
          imagePath = expandedPath;
        }
      } else {
        messageText = messageText ? `${messageText}\n${line}` : line;
      }
    }

    if (imagePath) {
      addUserMessage(messageText ? `${messageText}\n\n📎 ${imagePath}` : `📎 ${imagePath}`);
      sendMessage(messageText || 'What do you see in this image?', { image_path: imagePath });
      clearInput();
      return;
    }

    if (trimmed.startsWith('/')) {
      const parsed = parseInput(trimmed);
      if (parsed) {
        handleCommand(parsed.command.name, parsed.args);
        clearInput();
        return;
      }
    }

    if (isConnected && !isStreaming && !isSendingRef.current) {
      isSendingRef.current = true; // Synchronous - prevents race condition
      addUserMessage(trimmed);
      sendMessage(trimmed);
      clearInput();
    }
  }, [isConnected, isStreaming, addUserMessage, sendMessage, clearInput, parseInput, handleCommand, setSuggestions]);

  // Session handlers
  const handleSessionSelect = useCallback((session: Session) => {
    closeModal();
    resetAccumulator();
    switchConversation(session.id);
  }, [switchConversation, resetAccumulator, closeModal]);

  const handleSessionDelete = useCallback((sessionId: string) => {
    sessionAPI.deleteSession(sessionId)
      .then(() => sessionAPI.listSessions())
      .then((sessionList) => setSessions(sessionList))
      .catch((err) => logger.warn('Failed to delete session:', err));
  }, [sessionAPI, setSessions]);

  // Model selection handler
  const handleModelSelect = useCallback(async (modelId: string) => {
    closeModal();
    const success = await modelAPI.setModel(modelId);
    if (success) {
      onChunk({
        event: 'token',
        data: { content: `✅ Model changed to: **${modelId}**`, id: `model-${Date.now()}` },
      });
      onChunk({ event: 'complete', data: {} });
    } else {
      addErrorMessage('Failed to change model. Please try again.');
    }
  }, [modelAPI, closeModal, onChunk, addErrorMessage]);

  return (
    <Box flexDirection="column" flexGrow={1}>
      {!showSessionPicker && (
        <>
          <StatusPanel
            isConnected={isConnected}
            error={connectionError}
          />

          <ChatMessageArea
            staticItems={staticLines}
            dynamicItems={dynamicLines}
            showReasoning={showReasoning}
          />

          {/* Streaming indicator - visible while response is being generated */}
          {isStreaming && (
            <Box marginLeft={2} marginY={1}>
              <Text color="cyan">▋ </Text>
              <Text dimColor>Generating response...</Text>
            </Box>
          )}

          <Box minHeight={8}>
            <MultiLineInput
              key={inputKey}
              placeholder={isStreaming ? "Waiting for response..." : "Type your message..."}
              isDisabled={!isConnected || isStreaming}
              onSubmit={handleSubmit}
              onTextChange={handleTextChange}
              suggestions={suggestions}
            />
          </Box>

          <Box marginTop={1}>
            <Text dimColor>
              {isStreaming
                ? 'Waiting for response... • Ctrl+C to exit'
                : 'Enter: Send • Ctrl+P: Dashboard • Ctrl+O: Sessions • Ctrl+S: Settings • Ctrl+C: Exit'}
            </Text>
          </Box>
        </>
      )}

      {runMode.isActive && !showSessionPicker && (
        <Box flexDirection="column" width="100%" paddingX={2}>
          <RunModeStatus
            status={runMode.status}
            currentMessage={runMode.message}
            progress={runMode.progress}
          />
        </Box>
      )}

      {showingProjectList && !showSessionPicker && (
        <Box flexDirection="column" width="100%" paddingX={2}>
          <ProjectList projects={projects} />
          <Box marginTop={1}>
            <Text dimColor>Press any key to continue...</Text>
          </Box>
        </Box>
      )}

      {showingTaskList && !showSessionPicker && !showingProjectList && (
        <Box flexDirection="column" width="100%" paddingX={2}>
          <TaskList tasks={tasks} />
          <Box marginTop={1}>
            <Text dimColor>Press any key to continue...</Text>
          </Box>
        </Box>
      )}

      {showSessionPicker && (
        <Box flexDirection="column" width="100%" height="100%" justifyContent="center" alignItems="center">
          <SessionPickerModal
            sessions={sessions}
            currentSessionId={propConversationId}
            onSelect={handleSessionSelect}
            onDelete={handleSessionDelete}
            onClose={closeModal}
            isLoading={isLoadingSessions}
          />
        </Box>
      )}

      {showModelSelector && (
        <Box flexDirection="column" width="100%" height="100%" justifyContent="center" alignItems="center">
          <ModelSelectorModal
            onSelect={handleModelSelect}
            onClose={closeModal}
          />
        </Box>
      )}

      {showSettings && (
        <Box flexDirection="column" width="100%" height="100%" justifyContent="center" alignItems="center">
          <SettingsModal
            onClose={closeModal}
            modelAPI={modelAPI}
          />
        </Box>
      )}
    </Box>
  );
}
