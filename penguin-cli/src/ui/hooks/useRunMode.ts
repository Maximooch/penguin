/**
 * RunMode Hook - Autonomous task execution state management
 *
 * Handles RunMode state, WebSocket streaming, and task lifecycle.
 * Extracted from ChatSession to reduce complexity.
 */

import { useState, useRef, useCallback } from 'react';
import { RunAPI, type TaskStreamMessage, type RunModeStatus } from '../../core/api/RunAPI.js';

export interface UseRunModeOptions {
  conversationId?: string;
  onMessage?: (content: string, role: 'assistant' | 'system') => void;
  onError?: (error: string) => void;
}

export interface UseRunModeReturn {
  // State
  status: RunModeStatus;
  isActive: boolean;
  message: string;
  progress: number;

  // Actions
  startContinuous: (taskName?: string, description?: string) => void;
  startTask: (taskName: string, description?: string) => void;
  stop: () => Promise<void>;

  // API instance (for advanced usage)
  runAPI: RunAPI;
}

export function useRunMode(options: UseRunModeOptions = {}): UseRunModeReturn {
  const { conversationId, onMessage, onError } = options;

  // State
  const [status, setStatus] = useState<RunModeStatus>({ status: 'idle' });
  const [isActive, setIsActive] = useState(false);
  const [message, setMessage] = useState('');
  const [progress, setProgress] = useState(0);

  // Refs
  const runAPI = useRef(new RunAPI('http://localhost:8000')).current;
  const wsRef = useRef<WebSocket | null>(null);

  // Handle stream messages
  const handleStreamMessage = useCallback((msg: TaskStreamMessage) => {
    switch (msg.type) {
      case 'task_started':
        setMessage(`Started: ${msg.task_name}`);
        setProgress(0);
        onMessage?.(`▶ Task started: **${msg.task_name}**`, 'assistant');
        break;

      case 'task_progress':
        setMessage(msg.content || '');
        setProgress(msg.progress || 0);
        break;

      case 'task_completed_eventbus':
      case 'task_completed':
        setMessage('Completed');
        setProgress(100);
        onMessage?.('✅ Task completed!', 'assistant');
        if (msg.result) {
          onMessage?.(JSON.stringify(msg.result, null, 2), 'system');
        }
        break;

      case 'task_failed':
        setMessage(`Failed: ${msg.error}`);
        onError?.(`Task failed: ${msg.error}`);
        break;

      case 'message': {
        const content = (msg as any).data?.content || (msg as any).content;
        const role = (msg as any).data?.role || (msg as any).role || 'system';
        const category = (msg as any).data?.category || (msg as any).category || 'SYSTEM';

        if (content) {
          if (role === 'assistant' && category === 'DIALOG') {
            onMessage?.(content, 'assistant');
          } else if (category === 'SYSTEM_OUTPUT' || category === 'SYSTEM') {
            onMessage?.(`_${content}_`, 'system');
          }
        }
        break;
      }

      case 'error':
        onError?.(msg.error || 'Unknown error');
        break;

      case 'shutdown_completed':
      case 'run_mode_ended':
        setIsActive(false);
        setStatus({ status: 'idle' });
        break;
    }
  }, [onMessage, onError]);

  // Handle stream close
  const handleStreamClose = useCallback(() => {
    setIsActive(false);
    setStatus({ status: 'idle' });
    wsRef.current = null;
  }, []);

  // Handle stream error
  const handleStreamError = useCallback((error: Error) => {
    onError?.(`Stream error: ${error.message}`);
    setIsActive(false);
    setStatus({ status: 'idle' });
  }, [onError]);

  // Start continuous autonomous execution
  const startContinuous = useCallback((taskName?: string, description?: string) => {
    if (wsRef.current) {
      onError?.('RunMode is already running. Use stop() first.');
      return;
    }

    const name = taskName || 'Autonomous Task';
    setStatus({ status: 'running', current_task: name });
    setIsActive(true);
    setMessage('Starting...');
    setProgress(0);

    wsRef.current = runAPI.connectStreamAndExecute(
      name,
      description,
      true, // continuous mode
      conversationId,
      handleStreamMessage,
      handleStreamError,
      handleStreamClose
    );
  }, [conversationId, runAPI, handleStreamMessage, handleStreamError, handleStreamClose, onError]);

  // Start a single task
  const startTask = useCallback((taskName: string, description?: string) => {
    if (wsRef.current) {
      onError?.('A task is already running. Use stop() first.');
      return;
    }

    setStatus({ status: 'running', current_task: taskName });
    setIsActive(true);
    setMessage('Starting...');
    setProgress(0);

    wsRef.current = runAPI.connectStreamAndExecute(
      taskName,
      description,
      false, // not continuous
      conversationId,
      (msg) => {
        handleStreamMessage(msg);
        // Auto-close on completion for single tasks
        if (msg.type === 'task_completed' || msg.type === 'task_failed') {
          setIsActive(false);
          setStatus({ status: 'idle' });
        }
      },
      handleStreamError,
      handleStreamClose
    );
  }, [conversationId, runAPI, handleStreamMessage, handleStreamError, handleStreamClose, onError]);

  // Stop execution
  const stop = useCallback(async () => {
    try {
      await runAPI.stop();
      setStatus({ status: 'stopped' });
      setIsActive(false);

      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    } catch (err: any) {
      onError?.(`Failed to stop: ${err.message}`);
      throw err;
    }
  }, [runAPI, onError]);

  return {
    status,
    isActive,
    message,
    progress,
    startContinuous,
    startTask,
    stop,
    runAPI,
  };
}
