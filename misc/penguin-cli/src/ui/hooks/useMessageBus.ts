import { useState, useEffect, useCallback, useRef } from 'react';
import { AgentAPI, ProtocolMessage } from '../../core/api/AgentAPI';

export interface UseMessageBusOptions {
  agentId?: string;
  channel?: string;
  messageType?: string;
  includeBus?: boolean;
  includeUI?: boolean;
  autoConnect?: boolean;
}

export interface MessageBusState {
  connected: boolean;
  messages: ProtocolMessage[];
  error: Error | null;
}

export function useMessageBus(options: UseMessageBusOptions = {}) {
  const { autoConnect = true } = options;

  const [state, setState] = useState<MessageBusState>({
    connected: false,
    messages: [],
    error: null,
  });

  const apiRef = useRef<AgentAPI>(new AgentAPI());
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const maxReconnectAttempts = 5;
  const reconnectDelay = 2000; // 2 seconds

  // Message handler
  const handleMessage = useCallback((message: ProtocolMessage) => {
    setState((prev) => ({
      ...prev,
      messages: [...prev.messages, message],
    }));
  }, []);

  // Error handler
  const handleError = useCallback((error: Error) => {
    setState((prev) => ({
      ...prev,
      error,
      connected: false,
    }));
  }, []);

  // Close handler
  const handleClose = useCallback(() => {
    setState((prev) => ({
      ...prev,
      connected: false,
    }));

    // Attempt reconnection
    if (reconnectAttemptsRef.current < maxReconnectAttempts) {
      reconnectTimerRef.current = setTimeout(() => {
        reconnectAttemptsRef.current++;
        console.log(`[MessageBus] Reconnecting (attempt ${reconnectAttemptsRef.current})...`);
        connect();
      }, reconnectDelay);
    } else {
      handleError(new Error('Max reconnection attempts reached'));
    }
  }, []);

  // Connect to WebSocket
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      console.log('[MessageBus] Already connected');
      return;
    }

    try {
      wsRef.current = apiRef.current.connectMessageBus(
        handleMessage,
        {
          agentId: options.agentId,
          channel: options.channel,
          messageType: options.messageType,
          includeBus: options.includeBus,
          includeUI: options.includeUI,
        },
        handleError,
        handleClose
      );

      wsRef.current.onopen = () => {
        console.log('[MessageBus] Connected');
        setState((prev) => ({
          ...prev,
          connected: true,
          error: null,
        }));
        reconnectAttemptsRef.current = 0; // Reset reconnect counter
      };
    } catch (err) {
      const error = err instanceof Error ? err : new Error('Failed to connect to MessageBus');
      handleError(error);
    }
  }, [
    options.agentId,
    options.channel,
    options.messageType,
    options.includeBus,
    options.includeUI,
    handleMessage,
    handleError,
    handleClose,
  ]);

  // Disconnect from WebSocket
  const disconnect = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    setState((prev) => ({
      ...prev,
      connected: false,
    }));
  }, []);

  // Clear messages
  const clearMessages = useCallback(() => {
    setState((prev) => ({
      ...prev,
      messages: [],
    }));
  }, []);

  // Send message and trigger agent response (via REST API, not WebSocket)
  const sendMessage = useCallback(
    async (
      recipient: string,
      content: string,
      opts?: {
        sender?: string;
        message_type?: string;
        channel?: string;
        metadata?: Record<string, any>;
      }
    ) => {
      try {
        // Use humanReplyToAgent to trigger the agent to process and respond
        await apiRef.current.humanReplyToAgent(recipient, content, {
          message_type: opts?.message_type,
          channel: opts?.channel,
          metadata: opts?.metadata,
        });
      } catch (err) {
        const error = err instanceof Error ? err : new Error('Failed to send message');
        handleError(error);
        throw error;
      }
    },
    [handleError]
  );

  // Auto-connect on mount
  useEffect(() => {
    if (autoConnect) {
      connect();
    }

    return () => {
      disconnect();
    };
  }, [autoConnect, connect, disconnect]);

  return {
    connected: state.connected,
    messages: state.messages,
    error: state.error,
    connect,
    disconnect,
    clearMessages,
    sendMessage,
  };
}
