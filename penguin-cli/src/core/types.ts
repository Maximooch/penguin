/**
 * Shared types for Penguin CLI
 * Used across core services and UI components
 */

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
  toolCalls?: ToolCall[];
  reasoning?: string; // Internal reasoning from the model (if available)
}

export interface ToolCall {
  id: string;
  action: string;
  status: 'pending' | 'running' | 'completed' | 'error';
  result?: string;
  error?: string;
  startTime?: number;
  endTime?: number;
}

export interface StreamEvent {
  event: 'start' | 'token' | 'reasoning' | 'progress' | 'complete' | 'error';
  data: any;
}

export interface ActionResult {
  action: string;
  result: string;
  status: 'completed' | 'error' | 'interrupted';
  timestamp?: number;
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
