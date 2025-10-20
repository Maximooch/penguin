/**
 * Connection Context - Manages WebSocket connection state
 * Provides connection status and client instance to all components
 */

import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { ChatClient } from '../../core/connection/WebSocketClient';
import type { ConnectionState } from '../../core/types';

interface ConnectionContextValue extends ConnectionState {
  client: ChatClient | null;
  switchConversation: (newConversationId: string) => Promise<void>;
  currentConversationId: string | undefined;
}

const ConnectionContext = createContext<ConnectionContextValue | null>(null);

export interface ConnectionProviderProps {
  children: ReactNode;
  url?: string;
  conversationId?: string;
  agentId?: string;
}

export function ConnectionProvider({
  children,
  url = 'ws://localhost:8000/api/v1/chat/stream',
  conversationId: initialConversationId,
  agentId,
}: ConnectionProviderProps) {
  const [conversationId, setConversationId] = useState(initialConversationId);
  const [state, setState] = useState<ConnectionContextValue>({
    isConnected: false,
    isConnecting: true,
    error: null,
    reconnectAttempts: 0,
    client: null,
    currentConversationId: conversationId,
    switchConversation: async () => {}, // Will be set properly below
  });

  useEffect(() => {
    const client = new ChatClient({
      url,
      conversationId,
      agentId,
      onConnect: () => {
        setState((s) => ({
          ...s,
          isConnected: true,
          isConnecting: false,
          error: null,
          reconnectAttempts: 0,
          currentConversationId: conversationId,
        }));
      },
      onDisconnect: (code, reason) => {
        setState((s) => ({
          ...s,
          isConnected: false,
          isConnecting: false,
          error: code !== 1000 ? new Error(`Disconnected: ${code} ${reason}`) : null,
          reconnectAttempts: s.reconnectAttempts + (code !== 1000 ? 1 : 0),
        }));
      },
      onError: (error) => {
        setState((s) => ({
          ...s,
          error,
          isConnecting: false,
        }));
      },
    });

    const switchConversation = async (newConversationId: string) => {
      // Disconnect current client
      if (state.client) {
        state.client.disconnect();
      }

      // Update conversation ID which will trigger reconnection
      setConversationId(newConversationId);
    };

    setState((s) => ({ ...s, client, isConnecting: true, switchConversation }));

    client.connect().catch((error) => {
      setState((s) => ({
        ...s,
        error,
        isConnecting: false,
      }));
    });

    return () => {
      client.disconnect();
    };
  }, [url, conversationId, agentId]);

  return (
    <ConnectionContext.Provider value={state}>
      {children}
    </ConnectionContext.Provider>
  );
}

export function useConnection(): ConnectionContextValue {
  const context = useContext(ConnectionContext);
  if (!context) {
    throw new Error('useConnection must be used within ConnectionProvider');
  }
  return context;
}
