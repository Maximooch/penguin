/**
 * Message history hook - Manages message state
 * Separate from connection logic for better testing
 *
 * Performance optimizations:
 * - Batches multiple message additions into single state update
 * - Reduces re-renders during rapid message updates (e.g., 27+ iterations)
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import type { Message } from '../../core/types';

const BATCH_INTERVAL_MS = 100; // Batch updates every 100ms

export function useMessageHistory() {
  const [messages, setMessages] = useState<Message[]>([]);
  const pendingMessages = useRef<Message[]>([]);
  const batchTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Flush pending messages to state
  const flushPendingMessages = useCallback(() => {
    if (pendingMessages.current.length > 0) {
      const toAdd = pendingMessages.current;
      pendingMessages.current = [];
      setMessages((prev) => [...prev, ...toAdd]);
    }
    if (batchTimerRef.current) {
      clearTimeout(batchTimerRef.current);
      batchTimerRef.current = null;
    }
  }, []);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (batchTimerRef.current) {
        clearTimeout(batchTimerRef.current);
      }
    };
  }, []);

  const addMessage = useCallback((message: Message) => {
    // Add to pending batch
    pendingMessages.current.push(message);

    // Schedule flush if not already scheduled
    if (!batchTimerRef.current) {
      batchTimerRef.current = setTimeout(flushPendingMessages, BATCH_INTERVAL_MS);
    }
  }, [flushPendingMessages]);

  const addUserMessage = useCallback((text: string): Message => {
    const message: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: Date.now(),
    };
    addMessage(message);
    // Flush immediately for user messages to feel responsive
    flushPendingMessages();
    return message;
  }, [addMessage, flushPendingMessages]);

  const addAssistantMessage = useCallback((content: string, reasoning?: string): Message => {
    const message: Message = {
      id: `assistant-${Date.now()}`,
      role: 'assistant',
      content,
      timestamp: Date.now(),
      reasoning,
    };
    addMessage(message);
    return message;
  }, [addMessage]);

  const clearMessages = useCallback(() => {
    // Clear pending messages first
    pendingMessages.current = [];
    if (batchTimerRef.current) {
      clearTimeout(batchTimerRef.current);
      batchTimerRef.current = null;
    }
    setMessages([]);
  }, []);

  const getRecentMessages = useCallback(
    (count: number) => {
      return messages.slice(-count);
    },
    [messages]
  );

  return {
    messages,
    addMessage,
    addUserMessage,
    addAssistantMessage,
    clearMessages,
    getRecentMessages,
    flushMessages: flushPendingMessages, // Expose flush for immediate updates when needed
  };
}
