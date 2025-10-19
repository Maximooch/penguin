/**
 * WebSocket hook - Manages sending messages via WebSocket
 * Uses ConnectionContext for state
 */

import { useCallback } from 'react';
import { useConnection } from '../contexts/ConnectionContext';
import { useSession } from '../contexts/SessionContext';

export function useWebSocket() {
  const { isConnected, error, client } = useConnection();
  const { currentSession } = useSession();

  const sendMessage = useCallback(
    (text: string) => {
      if (!client?.isConnected()) {
        throw new Error('Not connected to server');
      }
      client.sendMessage(text);
    },
    [client]
  );

  return {
    isConnected,
    error,
    sendMessage,
    conversationId: currentSession.conversationId,
    agentId: currentSession.agentId,
  };
}
