/**
 * Shared types for Penguin CLI
 * Used across core services and UI components
 */

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
}

export interface StreamEvent {
  event: 'token' | 'tool_start' | 'tool_end' | 'complete' | 'error';
  data: any;
}

export interface Session {
  id: string;
  conversationId?: string;
  agentId?: string;
  createdAt: number;
  updatedAt: number;
}

export interface ChatConfig {
  apiUrl: string;
  conversationId?: string;
  agentId?: string;
}

export interface StreamConfig {
  batchSize: number;      // Number of tokens to batch (default: 50)
  batchDelay: number;     // Delay in ms before flushing (default: 50)
}

export interface ConnectionState {
  isConnected: boolean;
  isConnecting: boolean;
  error: Error | null;
  reconnectAttempts: number;
}
