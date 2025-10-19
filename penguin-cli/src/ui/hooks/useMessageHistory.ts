/**
 * Message history hook - Manages message state
 * Separate from connection logic for better testing
 */

import { useState, useCallback } from 'react';
import type { Message } from '../../core/types';

export function useMessageHistory() {
  const [messages, setMessages] = useState<Message[]>([]);

  const addMessage = useCallback((message: Message) => {
    setMessages((prev) => [...prev, message]);
  }, []);

  const addUserMessage = useCallback((text: string): Message => {
    const message: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, message]);
    return message;
  }, []);

  const addAssistantMessage = useCallback((content: string, reasoning?: string): Message => {
    const message: Message = {
      id: `assistant-${Date.now()}`,
      role: 'assistant',
      content,
      timestamp: Date.now(),
      reasoning,
    };
    setMessages((prev) => [...prev, message]);
    return message;
  }, []);

  const clearMessages = useCallback(() => {
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
  };
}
