/**
 * React hook for managing chat state and WebSocket connection
 * Includes token batching for smooth streaming display
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { ChatClient, Message } from '../api/client';

export interface UseChatOptions {
  url?: string;
  conversationId?: string;
  agentId?: string;
  tokenBatchSize?: number;  // Batch tokens (default: 50)
  tokenBatchDelay?: number; // Batch delay in ms (default: 50ms)
}

export interface UseChatReturn {
  messages: Message[];
  streamingText: string;
  isStreaming: boolean;
  isConnected: boolean;
  error: Error | null;
  sendMessage: (text: string) => void;
  disconnect: () => void;
}

export function useChat(options: UseChatOptions = {}): UseChatReturn {
  const {
    url,
    conversationId,
    agentId,
    tokenBatchSize = 50,
    tokenBatchDelay = 50,
  } = options;

  const [messages, setMessages] = useState<Message[]>([]);
  const [streamingText, setStreamingText] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const clientRef = useRef<ChatClient | null>(null);
  const tokenBufferRef = useRef<string>('');
  const flushTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Token batching: flush buffer when it reaches batchSize or after batchDelay
  const flushTokenBuffer = useCallback(() => {
    if (tokenBufferRef.current) {
      setStreamingText((prev) => prev + tokenBufferRef.current);
      tokenBufferRef.current = '';
    }
    if (flushTimeoutRef.current) {
      clearTimeout(flushTimeoutRef.current);
      flushTimeoutRef.current = null;
    }
  }, []);

  const handleToken = useCallback(
    (token: string) => {
      tokenBufferRef.current += token;

      // Flush if buffer reaches batch size
      if (tokenBufferRef.current.length >= tokenBatchSize) {
        flushTokenBuffer();
      } else {
        // Otherwise, schedule flush after delay
        if (flushTimeoutRef.current) {
          clearTimeout(flushTimeoutRef.current);
        }
        flushTimeoutRef.current = setTimeout(flushTokenBuffer, tokenBatchDelay);
      }
    },
    [tokenBatchSize, tokenBatchDelay, flushTokenBuffer]
  );

  const handleComplete = useCallback(() => {
    flushTokenBuffer(); // Flush any remaining tokens

    // Use functional update to get current streamingText
    setStreamingText((currentStreamingText) => {
      if (currentStreamingText) {
        setMessages((prev) => [
          ...prev,
          {
            id: Date.now().toString(),
            role: 'assistant',
            content: currentStreamingText,
            timestamp: Date.now(),
          },
        ]);
      }
      return ''; // Clear streaming text
    });

    setIsStreaming(false);
  }, [flushTokenBuffer]);

  const handleError = useCallback((err: Error) => {
    setError(err);
    setIsStreaming(false);
    flushTokenBuffer();
  }, [flushTokenBuffer]);

  // Initialize WebSocket client (only on mount or when connection params change)
  useEffect(() => {
    const client = new ChatClient({
      url,
      conversationId,
      agentId,
      onToken: handleToken,
      onComplete: handleComplete,
      onError: handleError,
      onConnect: () => setIsConnected(true),
      onDisconnect: (code, reason) => {
        setIsConnected(false);
        if (code !== 1000) {
          setError(new Error(`Disconnected: ${code} ${reason}`));
        }
      },
    });

    clientRef.current = client;

    client.connect().catch((err) => {
      setError(err);
    });

    return () => {
      client.disconnect();
      if (flushTimeoutRef.current) {
        clearTimeout(flushTimeoutRef.current);
      }
    };
    // Only recreate client when connection params change, NOT when callbacks change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, conversationId, agentId]);

  const sendMessage = useCallback((text: string) => {
    if (!clientRef.current?.isConnected()) {
      setError(new Error('Not connected to server'));
      return;
    }

    // Add user message
    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: text,
      timestamp: Date.now(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setStreamingText('');
    setIsStreaming(true);
    setError(null);

    clientRef.current.sendMessage(text);
  }, []);

  const disconnect = useCallback(() => {
    clientRef.current?.disconnect();
  }, []);

  return {
    messages,
    streamingText,
    isStreaming,
    isConnected,
    error,
    sendMessage,
    disconnect,
  };
}
